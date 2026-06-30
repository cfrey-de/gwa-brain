"""Dependency construction — wires Settings into concrete clients.

One shared RateLimiter governs chat + embedding calls together (provider free tiers are
tight). The optional cross-model guard gets its own client only when enabled.
"""
from gwa.config import Settings
from gwa.embedder import make_embedder
from gwa.llm import make_llm
from gwa.transport import RateLimiter


def build_limiter(settings: Settings) -> RateLimiter:
    return RateLimiter(settings.requests_per_second)


def build_llm(settings: Settings, limiter=None):
    return make_llm(settings.llm_cfg(), limiter=limiter)


def build_embedder(settings: Settings, limiter=None):
    return make_embedder(settings.embed_cfg(), limiter=limiter, api_key=settings.embed_api_key)


def build_guard_cross(settings: Settings, limiter=None):
    """Optional cross-model guard (None unless GUARD_CROSS_ENABLED)."""
    cfg = settings.guard_cross_cfg()
    if cfg is None:
        return None
    return make_llm(cfg, limiter=limiter)


def build_qdrant(settings: Settings):
    from qdrant_client import QdrantClient
    if settings.qdrant_location:  # ":memory:" for tests / single-process
        return QdrantClient(location=settings.qdrant_location)
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port,
                        check_compatibility=False)


def wait_for_qdrant(client, attempts=60, delay=1.0):
    """Block until Qdrant answers (or raise). App-side readiness wait — robust to the
    qdrant image lacking curl/wget for a compose healthcheck."""
    import time
    last = None
    for _ in range(attempts):
        try:
            client.get_collections()
            return True
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(delay)
    raise RuntimeError(f"Qdrant not reachable after {int(attempts * delay)}s: {last}")
