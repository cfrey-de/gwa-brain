"""FastAPI app: REST + Server-Sent-Events for upload and Q&A.

The reusable LLM/embedding stack is synchronous (urllib + sleep). Rather than port it,
the blocking pipeline runs in a thread and pushes events into an asyncio.Queue that the
SSE response drains — so a slow model call never stalls the event loop. A single
asyncio write-lock serializes upload/ask/reset so the accumulating brain stays
consistent (single-user PoC; see README). Brain reads are additionally guarded by the
brain's own internal lock.
"""
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gwa.config import get_settings
from gwa.deps import (build_embedder, build_guard_cross, build_limiter, build_llm,
                      build_qdrant, wait_for_qdrant)
from gwa.graph.brain import KnowledgeBrain
from gwa.ingestion.ingest import ingest_document
from gwa.qa.pipeline import run as run_pipeline

STATIC_DIR = Path(__file__).parent / "static"
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
SSE_QUEUE_MAX = 2048   # bound the producer->consumer buffer (drop-on-full; never block the worker)
MAX_CONCURRENT_STREAMS = int(os.getenv("GWA_MAX_STREAMS", "16"))  # reject excess streams with 429


class _UploadTooLarge(Exception):
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    missing = s.missing()
    if missing:
        raise RuntimeError(
            "missing configuration: " + ", ".join(missing) +
            " — set these in .env (see .env.example) or run offline with GWA_MOCK=1.")
    limiter = build_limiter(s)
    app.state.settings = s
    app.state.llm = build_llm(s, limiter=limiter)
    app.state.guard_cross = build_guard_cross(s, limiter=limiter)
    embedder = build_embedder(s, limiter=limiter)
    qdrant = build_qdrant(s)
    if not s.qdrant_location:  # real server: wait for readiness before serving
        await asyncio.to_thread(wait_for_qdrant, qdrant)
    app.state.brain = KnowledgeBrain(qdrant, embedder, data_dir=s.data_dir,
                                     collection=s.collection)
    app.state.uploads = Path(s.data_dir) / "uploads"
    app.state.uploads.mkdir(parents=True, exist_ok=True)
    app.state.write_lock = asyncio.Lock()
    # dedicated pool for blocking stream workers, separate from the default
    # to_thread pool (file writes, status reads) so an orphaned worker cannot starve it
    app.state.worker_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gwa-stream")
    app.state.jobs = set()   # strong refs to in-flight guarded jobs (survive client disconnect)
    app.state.sse_dropped = 0   # count of SSE events dropped due to a full/slow consumer buffer
    print(f"[app] ready — chat={s.model or 'mock'} embed={s.embed_model or 'lexical'} "
          f"mock={s.mock} cross_guard={'on' if app.state.guard_cross else 'off'} "
          f"facts={len(app.state.brain.facts)}")
    try:
        yield
    finally:
        app.state.worker_pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="GWA Brain", lifespan=lifespan)


# ---- SSE bridge: run a blocking producer in a thread, stream its events ------
def _sse_payload(ev) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


def _client_error(e: Exception) -> str:
    """User-facing error text. Our own ValueErrors (e.g. unsupported file type) are
    safe and helpful; anything else may carry internal URLs / raw model output, so it
    is logged server-side and replaced with a generic message."""
    if isinstance(e, ValueError):
        return str(e)
    print(f"[stream] worker error: {e!r}")
    return "Internal processing error."


async def _guarded_sse(app: FastAPI, produce):
    """Bridge a blocking producer to SSE.

    The guarded work runs as a SEPARATE task (`job`) that holds the write-lock for the
    whole operation. The streaming generator only *forwards* the job's events. If the
    client disconnects, the generator is cancelled but `job` is NOT — it keeps the lock
    until its worker thread finishes, so the brain is never mutated by two requests at
    once. (A naive `async with write_lock` inside the generator would release the lock
    on cancellation while the worker kept running — the bug this avoids.)"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=SSE_QUEUE_MAX)
    SENTINEL = object()

    def emit(ev):
        # Non-blocking hand-off. If the consumer is gone or too slow and the buffer is full,
        # DROP the event rather than (a) grow the queue unbounded or (b) block the worker
        # thread — which holds the write-lock, so blocking here could deadlock later
        # requests. A healthy client keeps the queue near-empty, so drops never happen.
        def _put():
            try:
                queue.put_nowait(ev)
            except asyncio.QueueFull:
                app.state.sse_dropped += 1
        loop.call_soon_threadsafe(_put)

    def worker():
        try:
            produce(emit)
        except Exception as e:  # noqa: BLE001 — surface as an error event, never crash the stream
            emit({"type": "error", "message": _client_error(e)})
        finally:
            def _end():
                try:
                    queue.put_nowait(SENTINEL)
                except asyncio.QueueFull:
                    pass  # generator falls back to the task.done() check below
            loop.call_soon_threadsafe(_end)

    async def job():
        async with app.state.write_lock:
            await loop.run_in_executor(app.state.worker_pool, worker)

    task = asyncio.ensure_future(job())
    app.state.jobs.add(task)

    def _done(t):
        app.state.jobs.discard(t)
        if not t.cancelled() and t.exception():
            print(f"[stream] job failed: {t.exception()!r}")
    task.add_done_callback(_done)

    while True:
        try:
            ev = await asyncio.wait_for(queue.get(), timeout=1.0)  # cancelled on disconnect
        except asyncio.TimeoutError:
            if task.done():     # worker finished; the SENTINEL may have been dropped if full
                while not queue.empty():
                    ev = queue.get_nowait()
                    if ev is not SENTINEL:
                        yield _sse_payload(ev)
                break
            continue
        if ev is SENTINEL:
            break
        yield _sse_payload(ev)


# ---- static ------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# ---- brain status / graph ----------------------------------------------------
@app.get("/brain/status")
async def brain_status(request: Request):
    status = await asyncio.to_thread(request.app.state.brain.status)
    status["readonly"] = request.app.state.settings.readonly   # UI hides upload/reset controls
    return status


@app.get("/graph")
async def graph(request: Request):
    return await asyncio.to_thread(request.app.state.brain.whole_graph)


@app.post("/brain/reset")
async def brain_reset(request: Request):
    app = request.app
    if app.state.settings.readonly:
        return JSONResponse({"error": "This demo is read-only."}, status_code=403)
    async with app.state.write_lock:
        await asyncio.to_thread(app.state.brain.reset)
    return {"ok": True}


def _safe_name(raw) -> str:
    name = Path(raw or "").name.replace("\x00", "")
    return "upload.txt" if name in ("", ".", "..") else name


# ---- upload (SSE) ------------------------------------------------------------
_MODES = {"auto", "factual", "prose", "derivation"}


@app.post("/upload/stream")
async def upload_stream(request: Request, file: UploadFile = File(...),
                        mode: str = Form(None)):
    app = request.app
    if app.state.settings.readonly:
        return JSONResponse({"error": "This demo is read-only; uploads are disabled."},
                            status_code=403)
    if len(app.state.jobs) >= MAX_CONCURRENT_STREAMS:
        return JSONResponse({"error": "Too many concurrent streams; please retry shortly."},
                            status_code=429)
    s = app.state.settings
    extract_mode = mode if mode in _MODES else s.extract_mode
    filename = _safe_name(file.filename)
    dest = app.state.uploads / filename

    # bounded, streamed-to-disk write so a huge upload cannot OOM the process
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > s.max_upload_bytes:
        return JSONResponse({"error": f"File too large (max {s.max_upload_bytes} bytes)."},
                            status_code=413)
    total = 0
    try:
        with open(dest, "wb") as f:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > s.max_upload_bytes:
                    raise _UploadTooLarge()
                f.write(chunk)
    except _UploadTooLarge:
        dest.unlink(missing_ok=True)
        return JSONResponse({"error": f"File too large (max {s.max_upload_bytes} bytes)."},
                            status_code=413)

    def produce(emit):
        for ev in ingest_document(str(dest), filename, app.state.brain, app.state.llm,
                                  extract_mode=extract_mode):
            emit(ev)

    return StreamingResponse(_guarded_sse(app, produce),
                             media_type="text/event-stream", headers=SSE_HEADERS)


# ---- ask (SSE) ---------------------------------------------------------------
class AskBody(BaseModel):
    question: str


@app.post("/ask/stream")
async def ask_stream(request: Request, body: AskBody):
    app = request.app
    if len(app.state.jobs) >= MAX_CONCURRENT_STREAMS:
        return JSONResponse({"error": "Too many concurrent streams; please retry shortly."},
                            status_code=429)
    q = body.question

    def produce(emit):
        run_pipeline(q, app.state.brain, app.state.llm, app.state.settings,
                     guard_cross=app.state.guard_cross, emit=emit)

    return StreamingResponse(_guarded_sse(app, produce),
                             media_type="text/event-stream", headers=SSE_HEADERS)


# allow `python -m gwa.ui.app`
def main():
    import uvicorn
    # default to loopback for local dev; the container CMD sets 0.0.0.0 explicitly
    host = os.getenv("BRAIN_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("gwa.ui.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
