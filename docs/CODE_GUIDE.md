# GWA Brain — Code Guide

A per-file, per-function walkthrough of the codebase. (← back to the [README](../README.md))

This guide explains **every source file and the functions/classes inside it**, grouped by subsystem and following the request flow: configuration → HTTP/LLM stack → data model → ingestion → the brain → retrieval → the Q&A pipeline → the web app → the UI → Docker.

For the *why* (design rationale, the term-specificity filter, the heading scope, derivation provenance), see the [README](../README.md). This document is the *what/where*.

## Contents

- **Configuration & entrypoint** — `gwa/config.py`, `gwa/deps.py`, `run.py`
- **HTTP / LLM / embeddings stack** — `gwa/transport.py`, `gwa/llm.py`, `gwa/embedder.py`
- **Data model** — `gwa/__init__.py`, `gwa/models.py`
- **Ingestion** — `gwa/ingestion/extractor.py`, `gwa/ingestion/fact_parser.py`, `gwa/ingestion/ingest.py`
- **The brain (Qdrant + graphs + persistence)** — `gwa/graph/brain.py`
- **Retrieval & term-specificity filter** — `gwa/qa/term_filter.py`, `gwa/qa/retriever.py`
- **Q&A pipeline, guard & prompts** — `gwa/qa/guard.py`, `gwa/qa/pipeline.py`, `gwa/qa/prompts.py`
- **FastAPI app & SSE** — `gwa/ui/app.py`
- **Web UI (vanilla HTML/CSS/SVG)** — `gwa/ui/static/tree.js`, `gwa/ui/static/index.html`, `gwa/ui/static/style.css`
- **Docker & dependencies** — `Dockerfile`, `docker-compose.yml`, `.env.example`, `requirements.txt`

---

## Configuration & entrypoint

### `gwa/config.py`

Central configuration management that reads environment variables and provides settings for the chat LLM, embeddings, Qdrant vector database, and optional guard. Supports OpenAI-compatible endpoints (hosted APIs or local servers like vLLM/Ollama) with sensible defaults and validation.

- `_env(name, default=None)` — Helper to read environment variable and return it, or the default if empty/None.
- `_env_bool(name, default=False)` — Helper to read environment variable as a boolean, interpreting "1", "true", "yes", "on" (case-insensitive).
- `_env_int(name, default)` — Helper to read environment variable as an integer, returning default on parse failure.
- `_env_float(name, default)` — Helper to read environment variable as a float, returning default on parse failure.
- `Settings` — Dataclass holding all configuration fields (LLM, embeddings, Qdrant, storage, retrieval params, guard settings, mock mode).
- `Settings.__post_init__(self)` — Ensures embeddings default to the chat endpoint and API key if not explicitly overridden.
- `Settings.llm_api_key` (property) — Returns the chat API key by reading the environment variable named in `llm_api_key_env`.
- `Settings.embed_api_key` (property) — Returns the embedding API key by reading the environment variable named in `embed_api_key_env`.
- `Settings.missing(self)` — Returns a list of required configuration fields that are absent (empty list in mock mode); used for startup validation.
- `Settings.llm_cfg(self)` — Returns a configuration dict for `gwa.llm.make_llm`, including provider ("mock" or "openai-compatible"), model, max tokens, and endpoint settings.
- `Settings.embed_cfg(self)` — Returns a configuration dict for the embeddings system, including embeddings type ("lexical" or "api"), model, batch size, and endpoint.
- `Settings.guard_cross_cfg(self)` — Returns config dict for the optional cross-model guard (None if disabled), allowing a different model/endpoint for safety checks.
- `get_settings()` — Factory function that returns a new Settings instance initialized from environment variables.

### `gwa/deps.py`

Dependency injection layer that wires Settings into concrete client instances (LLM, embedder, Qdrant, optional guard). Uses a shared RateLimiter to govern both chat and embedding API calls together.

- `build_limiter(settings: Settings) -> RateLimiter` — Constructs a rate limiter from the configured requests-per-second setting.
- `build_llm(settings: Settings, limiter=None)` — Creates the chat LLM client using the llm config from Settings, optionally sharing a rate limiter.
- `build_embedder(settings: Settings, limiter=None)` — Creates the embeddings client using the embed config and API key from Settings, optionally sharing a rate limiter.
- `build_guard_cross(settings: Settings, limiter=None)` — Creates an optional second LLM client for the cross-model guard; returns None if disabled.
- `build_qdrant(settings: Settings)` — Constructs a QdrantClient, using in-memory location for tests or a remote host:port for production.
- `wait_for_qdrant(client, attempts=60, delay=1.0)` — Blocking readiness check that polls Qdrant's `get_collections()` until it succeeds or raises after 60 attempts; used for startup synchronization in compose environments.

### `run.py`

Local development entry point that launches the FastAPI app via Uvicorn. Configurable host (default localhost) and port (default 8000), and supports offline mock mode with in-memory storage for testing without external services.

---

## HTTP / LLM / embeddings stack

### `gwa/transport.py`

Provides shared HTTP transport for OpenAI-compatible endpoints with client-side rate limiting and automatic retry logic that respects Retry-After headers. A single RateLimiter instance is shared between the LLM and embedder to enforce provider rate limits on combined traffic.

- `class RateLimiter` — Enforces a per-request minimum interval to limit outgoing requests to a configured rate (requests per second).
- `RateLimiter.wait()` — Blocks (via time.sleep) until the next request is permitted under the rate limit.
- `_retry_delay(headers, attempt, base=1.0, cap=60.0)` — Calculates exponential backoff with jitter, extracting Retry-After from response headers if available and capping at 60 seconds.
- `post_json(url, payload, api_key=None, limiter=None, max_retries=5, timeout=180)` — POSTs JSON to a URL, automatically retrying transient errors (429, 5xx, connection failures) with backoff; applies rate limiting if a limiter is provided; returns the parsed response dict.

### `gwa/llm.py`

Provides uniform LLM access via OpenAI-compatible chat/completions endpoints, with both a live API client and a deterministic mock for testing that performs real text transformations (sentence splitting, token overlap filtering, fact formatting).

- `extract_json(text: str) -> dict` — Tolerantly parses JSON from model output, stripping markdown code fences and falling back to extracting the first {...} span if direct parsing fails.
- `_content_tokens(text)` — Extracts content tokens (non-stop-words, length > 1) from text, used by the MockLLM for relevance filtering.
- `class OpenAICompatLLM` — Client for any OpenAI-compatible chat/completions endpoint, configured with model, max_tokens, and optional rate limiter.
- `OpenAICompatLLM.complete(role, system, user, temperature=None) -> str` — Calls /chat/completions with the given system/user messages and optional temperature override; returns the assistant's content as a string.
- `class MockLLM` — Deterministic test stub that responds based on role: 'extract' sentence-splits into facts, 'decompose' splits questions on separators, 'guard' filters candidates by token overlap, 'formulate' builds cited prose from facts.
- `MockLLM.complete(role, system, user, temperature=None) -> str` — Returns role-specific deterministic output as a JSON string, performing real transformations so tests exercise the full pipeline.
- `make_llm(cfg, limiter=None)` — Factory that instantiates either MockLLM or OpenAICompatLLM based on the provider config key; reads API key from environment on demand.

### `gwa/embedder.py`

Provides embeddings as L2-normalized vectors via OpenAI-compatible endpoints (with automatic batching) or a deterministic lexical hash-based embedder for testing without external dependencies.

- `tokenize(text)` — Lowercases text and extracts tokens using a regex that captures alphanumerics and certain accented characters (for German support).
- `_l2(v)` — L2-normalizes a vector so that dot product equals cosine similarity.
- `class LexicalEmbedder` — Deterministic, dependency-free embedder that hashes tokens into a fixed-dimensional bag-of-words vector; used for testing.
- `LexicalEmbedder.__init__(dim=256)` — Initializes with a configurable vector dimension (default 256).
- `LexicalEmbedder.embed(texts)` — Returns L2-normalized vectors for a list of texts by hashing each token into a fixed dimension.
- `LexicalEmbedder._vec(text)` — Internal method that builds a raw vector by accumulating token hashes and normalizes it.
- `class OpenAICompatEmbedder` — Calls an OpenAI-compatible /embeddings endpoint with automatic batching to respect provider limits; normalizes all returned vectors to L2.
- `OpenAICompatEmbedder.__init__(model, base_url, api_key=None, limiter=None, max_retries=5, batch=64)` — Configures the API endpoint, model, and batch size (default 64 texts per request).
- `OpenAICompatEmbedder.embed(texts)` — Sends texts in batches to the API, sorts results to maintain input order, and returns L2-normalized embedding vectors.
- `make_embedder(cfg, limiter=None, api_key=None)` — Factory that returns either a LexicalEmbedder (if config specifies "lexical") or an OpenAICompatEmbedder; reads batch size and retry limits from config.

---

## Data model

### `gwa/__init__.py`

Package initialization for GWA Brain, a document-grounded Q&A system that traces every answer to named sources with full provenance tracking. Defines package metadata and grounding guarantees.

- `__version__ = "0.1.0"` — Semantic version identifier for the package.
- `__author__ = "Carsten Frey"` — Package author attribution.
- `__license__ = "Apache-2.0"` — License identifier.

### `gwa/models.py`

Core data structures for the fact extraction and answer generation pipeline: `Fact` (a source-bound statement with deduplication via deterministic UUID), `Candidate` (a fact under scoring and filtering), and `QAResult` (the structured answer bundle with provenance).

- `_now()` — Returns current UTC datetime in ISO format as a string; used as default factory for timestamp fields.
- `fact_id(source_doc: str, text: str) -> str` — Generates a deterministic UUID v5 from document and text pair, enabling content-based deduplication when re-ingesting documents and serving as the Qdrant vector DB point id.
- `Fact.__post_init__(self)` — Auto-computes fact id if not provided during initialization, ensuring every Fact has a stable, reproducible identifier.
- `Fact.searchable` — Property that returns the fact text prefixed with document scope/heading for embedding and matching, improving recall on entity questions while keeping clean text for answers.
- `Fact.source_label` — Property that formats the citation string with document name, page number, or paragraph number depending on available metadata.
- `Fact.to_dict(self) -> dict` — Converts Fact instance to plain dictionary via dataclass asdict utility.
- `Fact.from_dict(cls, d: dict) -> Fact` — Class method that reconstructs a Fact from a dictionary, filtering to only known dataclass fields for robustness.
- `Candidate.to_dict(self) -> dict` — Serializes Candidate to a flat dict combining fact metadata with scoring and filtering metadata (score, term_score, final_score, status, reason), used for pipeline logging and result display.
- `QAResult.to_dict(self) -> dict` — Converts the complete Q&A result (question, answer, sub-requirements, facts, gaps, sources, dependency graph) to a dictionary.

---

## Ingestion

### `gwa/ingestion/extractor.py`

Converts documents (PDF, Word, text/markdown) into logical text chunks (~300 tokens) with stable citations (page number for PDFs, paragraph index otherwise). Chunks respect paragraph and heading boundaries to maintain coherent units.

- `Chunk` — Dataclass representing a single extracted text chunk with source document reference, index, optional page/paragraph metadata, and optional document context (heading/title) for resolving implicit fact subjects.
- `_ntok(text: str) -> int` — Counts word tokens by splitting on whitespace; used to measure chunk sizes against the target token threshold.
- `_doc_heading(units)` — Extracts the document's title/heading from the first unit if it looks like one (short, no terminal punctuation); used as context to resolve implicit fact references.
- `_pack(units, source_doc, target=TARGET_TOKENS, context=None)` — Groups paragraphs into chunks sized around ~300 tokens; returns list of Chunk objects with stable chunk IDs and citation metadata.
- `_pdf_units(path)` — Extracts paragraphs from a PDF file via pdfplumber, associating each paragraph with its page number; returns (units_list, page_count).
- `_docx_units(path)` — Extracts paragraph text from a Word document via python-docx; returns (units_list, None).
- `_text_units(path)` — Extracts double-newline-separated paragraphs from text or markdown files; returns (units_list, None).
- `extract(path, filename)` — Main entry point; routes to the appropriate extraction function by file extension (.pdf, .docx, .txt, .md, .markdown, .text) and returns (chunks, page_count), or raises ValueError for unsupported types.

### `gwa/ingestion/fact_parser.py`

Extracts atomic facts from chunk text via an LLM with three parsing modes: "factual" (concrete numbers/units/conditions), "prose" (narrative propositions), and "auto" (tries factual first, falls back to prose if empty). Conservative design: parse failures yield no facts, never hallucinations.

- `_extract(chunk_text: str, llm, system: str) -> list` — Calls the LLM to extract facts using a system prompt, parses the JSON response, and deduplicates fact strings; silently returns empty list on any error or malformed response.
- `parse_facts(chunk_text: str, llm, mode: str = "auto") -> list` — Extracts and returns a deduped list of fact strings from one chunk, with fallback logic: in "auto" mode, if no facts are found with the factual prompt, retries with the prose prompt.
- `parse_steps(text: str, llm) -> list` — Derivation mode: extracts ordered steps with ids, text, and dependencies from a full document; restricts dependencies to earlier, previously-seen step ids; returns empty list on parse failure or malformed response.

### `gwa/ingestion/ingest.py`

Orchestrates the full ingestion pipeline (document → chunks → facts → brain mutation) as a generator that yields progress events (start, chunk, done) for streaming to SSE clients and test consumption.

- `_now()` — Returns current UTC time as an ISO 8601 string for event timestamps.
- `ingest_document(path, filename, brain, llm, extract_mode="auto")` — Generator that extracts a document into chunks, parses facts from each chunk (or steps in derivation mode), adds them to the brain, and yields progress events (start, chunk*, done); mutates the brain object and saves it.
- `_ingest_derivation(chunks, filename, brain, llm)` — Special mode handler that treats the entire document as one derivation, parses interdependent steps, creates facts with resolved dependencies, and yields a single chunk event; returns the count of new facts added.
- `ingest_collect(path, filename, brain, llm, extract_mode="auto") -> dict` — Synchronous wrapper that drains the ingest_document generator and returns the final `done` event; used by tests and non-streaming contexts.

---

## The brain (Qdrant + graphs + persistence)

### `gwa/graph/brain.py`

Persistent memory system for accumulating facts and their co-usage patterns. Maintains a dual-store architecture: Qdrant for vector similarity search and NetworkX for a co-usage graph where edge weights reflect how often facts are cited together; the graph feeds back into retrieval as a re-ranking signal.

- `class KnowledgeBrain` — The core in-memory+persistent knowledge store. Manages fact metadata, embeddings in Qdrant, a co-usage graph, derivation dependencies, and document registry; threads safely via RLock for data structures and a separate save lock for atomic file writes.

- `__init__(self, qdrant, embedder, data_dir, collection="gwa_facts")` — Initialize the brain by setting up client references, data directory, and in-memory structures (facts dict, graph, deps, docs), then load from persisted `brain.json` if it exists.

- `_ensure_collection(self, dim)` — Create a Qdrant collection if it doesn't exist, sized for the given embedding dimension.

- `add_facts(self, facts: list) -> int` — Embed a list of new facts and store them (deduped by id) in both Qdrant and the in-memory graph; returns count of newly added facts. Embedding is done outside the lock for performance.

- `add_dependencies(self, fact_id, dep_ids)` — Record directed derivation edges from `fact_id` to prerequisite facts, building a fact-to-fact dependency DAG used by `dependency_subtree()`.

- `dependency_subtree(self, root_ids) -> dict` — BFS the derivation DAG from given root facts to collect all prerequisite facts and the "derives" edges; returns a node/link structure for visualization.

- `register_doc(self, name, n_facts, ts)` — Register or update a document record with fact count and upload timestamp; used to track the source documents.

- `search(self, query_text: str, top_k: int)` — Embed the query and return the top_k facts by cosine similarity from Qdrant, with scores.

- `record_usage(self, kept_facts: list, question: str)` — Increment weight and use count on cited facts; add or strengthen edges in the co-usage graph between all pairs of cited facts; returns list of updated fact ids (the accumulation feature).

- `_node_view(self, fid)` — Convert a fact id into a view dict with label, text, source, weight for graph export.

- `whole_graph(self) -> dict` — Export the full co-usage graph (all nodes and edges) with metadata (fact count, document count).

- `co_usage_subgraph(self, fact_ids) -> dict` — Extract and export the induced subgraph over a list of fact ids, preserving edge weights.

- `status(self) -> dict` — Return a summary of fact count, document count, and list of all documents.

- `save(self)` — Serialize facts, graph, dependencies, and document registry to `brain.json` atomically using a temp file + fsync + atomic rename, ensuring durability even on crash.

- `load(self)` — Deserialize `brain.json` into memory and restore the co-usage graph; on parse error, back up the corrupt file to `.corrupt` and start fresh; then call `_reconcile_qdrant()` to sync Qdrant.

- `_reconcile_qdrant(self)` — Verify Qdrant collection exists and has correct dimension; if embedder changed, recreate the collection; if vectors are missing or incomplete, re-embed and upsert all facts (self-healing after Qdrant volume loss).

- `reset(self)` — Clear all in-memory data (facts, graph, deps, docs), delete the Qdrant collection, and remove `brain.json`.

---

## Retrieval & term-specificity filter

### `gwa/qa/term_filter.py`

Implements a deterministic term-specificity filter (Stufe B) that guards against semantic similarity confusing near-facts by comparing numeric quantities and their qualifiers. It scores candidates based on content overlap and flags numeric near-neighbours (same qualifier, different number) to prevent substitution of distinct facts.

- `content_tokens(text)` — Extracts non-stopword tokens (>1 character) from text in lowercase; used as the basis for content overlap scoring between requirements and candidates.

- `numbers(text)` — Extracts all numeric values from text, normalizing comma and period separators to periods for comparison.

- `quantity_terms(text)` — Returns (number, qualifier) pairs where a qualifier word (unit or measurement type) immediately precedes or follows a number; captures the load-bearing numerical conditions in a fact.

- `_score_one(req: str, cand: str)` — Scores a single requirement-candidate pair and returns (term_score, on_target, covers, conflict): on_target indicates strict filter passage (high coverage or matching numbers), covers indicates lenient coverage for gap attribution, and conflict flags numeric near-neighbours (same qualifier, different number).

- `term_specificity_filter(candidates, sub_requirements)` — Mutates each candidate by computing term_score (best match across all sub-requirements), covers (list of matching sub-requirement indices), on_target (strict filter pass), and quantity_conflict (vetoed near-neighbour with no coverage).

### `gwa/qa/retriever.py`

Orchestrates two-stage retrieval: broad semantic search (Stufe A) via Qdrant vectors, term-specificity filtering (Stufe B) to score content alignment, and accumulation-weight reranking that blends semantic and term scores with graph citation weight to surface both highly similar and frequently co-cited facts.

- `_broad_search(brain, sub_requirements, top_k)` — Performs union of per-sub-requirement semantic searches against the brain (Qdrant), deduplicating by fact ID and keeping the highest cosine score per fact.

- `_apply_accumulation(candidates, weight)` — Applies the final scoring formula: base_score = 0.6×cosine + 0.4×term_score, then blends with normalized graph weight via weight parameter to balance semantic relevance against citation frequency.

- `retrieve(brain, sub_requirements, settings)` — Main retrieval entry point that calls broad_search, applies term-specificity filtering, computes accumulation scores, sorts by on_target strictness then final_score (best first), and returns top_k candidates; ensures covering facts are not truncated by higher-cosine off-target near-neighbours.

---

## Q&A pipeline, guard & prompts

### `gwa/qa/guard.py`

Implements Stufe C — the semantic guard that partitions candidates into kept/struck by detecting non-entailment and topic drift. Hard-vetoes numeric near-neighbours (quantity_conflict), while delegating other semantic decisions to the LLM with optional cross-model verification.

- `_verdicts(llm, sub_requirements, candidates)` — Sends candidates to the LLM with a guard prompt and extracts JSON verdicts mapping short integer indices to {keep, reason} pairs; returns empty dict on any parse failure (conservative default to strike).

- `guard(candidates, sub_requirements, llm, guard_cross=None)` — Partitions candidates into (kept, struck) lists by checking quantity_conflict first (hard veto), then querying the LLM for semantic coverage verdicts, and optionally requiring secondary cross-model confirmation; mutates status and reason fields on each candidate.

### `gwa/qa/pipeline.py`

The main Q&A pipeline orchestrating six stages: decompose question → retrieve candidates → guard filter → detect gaps → formulate answer → accumulate usage. Emits events at each stage for live SSE streaming and returns a complete QAResult with the answer, sources, dependency tree, and provenance.

- `decompose(question, llm)` — Splits a question into concrete sub-requirements via LLM; returns the original question if decomposition fails or yields no valid pieces.

- `gap_check(sub_requirements, kept)` — Returns the list of sub-requirements not covered by any kept candidate's `covers` metadata.

- `formulate(question, kept, gaps, llm)` — Generates the final answer by prompting the LLM to synthesize only the kept facts with citations, declaring any uncovered gaps; falls back to a source-only format if formulation fails.

- `_node(c, status)` — Builds a node dict for the dependency tree from a candidate and status string, truncating the label to 48 chars.

- `build_tree(answer, kept, struck, gaps, brain)` — Constructs a full provenance tree with answer node, kept/struck/gap nodes, dependency links from the brain, and co-usage edges; deduplicates nodes so a struck fact shown as a dependency prerequisite is not repeated.

- `run(question, brain, llm, settings, guard_cross=None, emit=None)` — Orchestrates all six pipeline stages, emitting events after each, recording usage statistics via `brain.record_usage()`, and returning the QAResult with full tree and source tracking.

- `ask(question, brain, llm, settings, guard_cross=None)` — Convenience synchronous wrapper around `run()` for tests and simple callers.

### `gwa/qa/prompts.py`

Centralizes all LLM prompts and their builder functions; prompts are English-language instructions that direct the model to output in the same language as the input (German documents → German facts, English documents → English facts).

- `EXTRACT_SYSTEM` — System prompt for factual mode: extracts self-contained facts from passages with strict rules (one sentence per fact, exact numbers/units, no interpretation).

- `PROSE_EXTRACT_SYSTEM` — System prompt for prose/narrative mode: extracts key assertions and depicted actions without interpretation or moral judgment.

- `DERIVATION_EXTRACT_SYSTEM` — System prompt for derivation/calculation mode: extracts ordered steps with explicit dependency declarations (id, text, depends_on).

- `DECOMPOSE_SYSTEM` — System prompt for question decomposition: breaks a question into minimal sub-requirements, staying close to wording, rejecting textbook knowledge and formulas not asked for.

- `GUARD_SYSTEM` — System prompt for the semantic guard: judges whether each candidate content-covers a sub-requirement (not just topical similarity), defaulting to false on doubt.

- `build_guard_user(requirements, candidates)` — Serializes requirements and candidates (with short indices) into a JSON user message for the guard LLM.

- `FORMULATE_SYSTEM` — System prompt for answer formulation: instructs the model to synthesize only the verified facts with citations in square brackets, declare gaps honestly, and use the input language.

- `build_formulate_user(question, facts, gaps)` — Serializes question, facts (with text/source tuples), and gaps into a JSON user message for the formulate LLM.

---

## FastAPI app & SSE

### `gwa/ui/app.py`

This module implements a FastAPI REST API with Server-Sent-Events (SSE) streaming for document uploads and Q&A operations. It uses a threading architecture where blocking model calls run in a separate thread pool and emit events into an asyncio Queue that the SSE response drains, preventing blocking operations from stalling the event loop.

- `lifespan(app: FastAPI)` — Async context manager that initializes the FastAPI app's lifecycle: validates configuration, builds the LLM, embedder, vector database (Qdrant), and knowledge brain, sets up the uploads directory, creates a write-lock for serializing brain mutations, and spawns a dedicated ThreadPoolExecutor for blocking stream workers; ensures Qdrant readiness before serving.

- `_sse_payload(ev) -> str` — Formats an event dictionary as an SSE data line (JSON-serialized with `data:` prefix and double newline).

- `_client_error(e: Exception) -> str` — Converts exceptions to user-facing error text; returns the exception message for ValueError (safe/helpful errors) and logs other exceptions server-side before returning a generic message to avoid leaking internal details.

- `async def _guarded_sse(app: FastAPI, produce)` — Core async generator that bridges a blocking producer function to SSE output; runs the producer in a separate task that holds the write-lock for the entire operation, ensuring the brain is never mutated concurrently; drops SSE events if the consumer is too slow (full buffer) rather than blocking the worker thread and risking deadlock.

- `async def index()` — Serves the static index.html file as the root endpoint.

- `async def healthz()` — Simple health check endpoint that returns `{"ok": True}`.

- `async def brain_status(request: Request)` — Returns the current status of the knowledge brain (fact count, collection info, etc.) by calling `brain.status()` in a thread.

- `async def graph(request: Request)` — Returns the entire knowledge graph as a JSON-serializable structure via `brain.whole_graph()`.

- `async def brain_reset(request: Request)` — Clears all facts and embeddings from the knowledge brain; acquires the write-lock during the operation to prevent concurrent mutations.

- `_safe_name(raw) -> str` — Sanitizes uploaded filenames by extracting the base name and removing null bytes; returns "upload.txt" for empty or invalid names.

- `async def upload_stream(request: Request, file: UploadFile, mode: str)` — Accepts a file upload and streams back ingestion progress as SSE events; validates file size against `max_upload_bytes`, writes the file to disk in bounded 1MB chunks to prevent OOM, then runs document ingestion (fact extraction, embedding, vector storage) via `ingest_document()` with the specified extraction mode (auto, factual, prose, derivation).

- `AskBody` — Pydantic model for the `/ask/stream` request body containing a `question` string.

- `async def ask_stream(request: Request, body: AskBody)` — Accepts a question and streams back Q&A pipeline results as SSE events; runs the full answer pipeline (retrieval, ranking, cross-guard validation, LLM synthesis) via `run_pipeline()` and emits progress events.

- `main()` — Entry point for `python -m gwa.ui.app`; starts the Uvicorn ASGI server on the host and port specified by `BRAIN_HOST` (default 127.0.0.1) and `PORT` (default 8000) environment variables.

---

## Web UI (vanilla HTML/CSS/SVG)

### `gwa/ui/static/tree.js`

Renders an interactive SVG-based node-link visualization of either a dependency tree (hierarchical, answering a question) or a co-usage graph overview (circular layout). Supports pan, zoom (mouse wheel + desktop drag, two-finger pinch on touch), and tooltips on node click/tap. Uses vanilla SVG with no external libraries.

**Public API:**
- `GWATree(hostElement)` — factory function returning the tree controller; initializes SVG, viewport, placeholder, and tooltip elements within the host.
- `tree.render(treeData)` — renders nodes and links from `{nodes: [...], links: [...]}` data; null/empty shows placeholder; automatically chooses hierarchical vs. circular layout based on link types.
- `tree.reset()` — recenters and resets zoom level to fit all nodes in view.
- `tree.clear()` — empties the tree and shows the default placeholder message.

**Internal layout & rendering helpers:**
- `layout(data)` — circular/radial layout for co-usage graphs: answer at center, kept facts left, struck facts right, gaps far right; for overview (no answer node), arranges only connected facts in a circle.
- `layoutHier(data)` — hierarchical top-down tree layout rooted at the answer node; uses longest-path depth traversal to position shared prerequisites, keeps struck facts and gaps in side columns; returns both nodes and edges with parent-child directives.
- `draw(nodes, links)` — renders flat co-usage graph with simple lines; no arrowheads or hierarchy.
- `drawHier(nodes, edges, links)` — renders hierarchical tree; dashed lines for struck/gap links, solid lines with arrowheads for support/derives edges; omits co-usage edges for clarity.
- `fit(nodes)` — zooms and pans to fit all nodes in view with padding, clamping scale between 0.05–1.4.
- `appendNode(n)` — creates an SVG group with rounded rect and text label, applies node-type CSS class, and appends to node container.
- `nodeClass(n)` — returns CSS class (`tnode-answer`, `tnode-kept`, `tnode-struck`, `tnode-gap`, `tnode-derived`, or `tnode-fact`) based on node type and status.
- `linkClass(l)` — returns CSS class (`tlink-support`, `tlink-derives`, `tlink-struck`, `tlink-gap`, `tlink-cousage`) based on link kind.

**Transform & viewport:**
- `apply()` — applies the current transform (translate + scale) to the viewport and repositions tooltip if open.
- `zoomAround(px, py, factor)` — zooms around a point (e.g., mouse cursor) by adjusting scale and translation; clamps scale to 0.15–4.
- `size()` — returns the container's client width/height (or fallback 600x400).

**Tooltip:**
- `showTip(id)` — displays tooltip for a node with source, text, reason (if struck), weight/uses metadata.
- `positionTip(id)` — positions tooltip near node, flipping above if it would overflow bottom.
- `hideTip()` — hides tooltip and clears the open node ID.
- `tipHtml(n)` — generates HTML for tooltip content with HTML-escaped node data.

**Pan & zoom interaction (Pointer Events):**
- `pointerdown` — captures pointer, tracks for single-finger drag (pan) or two-finger pinch (zoom); records initial position to distinguish pan from tap.
- `pointermove` — handles drag (pan when one pointer) or pinch (zoom when two pointers); updates position and applies transform.
- `endPointer(e)` — releases pointer; if not moved and target is a node, shows tooltip; otherwise hides it.
- `wheel` — mouse wheel zoom centered at cursor; prevents default and applies smooth zoom factor.

**Utility helpers:**
- `el(tag, attrs)` — creates an SVG element with optional attributes.
- `clamp(v, lo, hi)` — clamps value between bounds.
- `dist(a, b)` — Euclidean distance between two points.
- `esc(s)` — HTML-escapes a string to prevent injection.
- `trunc(s, n)` — truncates string to n chars, replacing overflow with "…".
- `stackCol(arr, x, rowY)`, `stackRow(arr, y, colX)`, `stackColAt(arr, x, midY, rowGap)` — position helpers that evenly space and center groups of nodes along an axis.

---

### `gwa/ui/static/index.html`

Single-page HTML structure for the GWA Brain interface. Three-column layout on desktop (answer + log panes on left, tree on right); mobile tabs switch between Answer, Tree, and Live log. Includes header with upload/mode/menu controls, ask row footer, and inline script for state, I/O, and event streaming.

**Key sections:**

- **Header** — brand logo, upload button (file input for .pdf/.txt/.md/.docx), mode dropdown (Auto/Factual/Prose/Derivation), status pill (fact/document count), and document menu button.
- **Tabs (mobile)** — switches active pane; state persists via localStorage.
- **Workspace** — flex layout containing:
  - **Answer pane** — displays substantiated answer prose with citations, sources (docs), and gaps (uncovered sub-requirements).
  - **Log pane** — scrollable event log with auto-scroll badge; shows upload progress, fact assessments (kept/struck), and errors.
  - **Tree pane** — SVG tree host with Overview/Reset buttons in header.
- **Ask row** — question input field and Send button (with spinner when busy).
- **Drag-drop overlay** — full-window visual feedback on desktop when dragging file (hidden on mobile).
- **Inline script** — handles state (busy, autoscroll), tab switching, upload/ask flows via SSE streams, log rendering, tree rendering, and brain reset.

**Inline script main sections:**

- `esc(s)`, `withCites(s)` — HTML-escape and citation highlight helpers.
- `setTab(tab)` — switches active pane and localStorage tab key; resets tree view if switching to Tree.
- `refreshStatus()`, `renderDocs(docs)` — fetch brain status and populate document list in menu.
- `setBusy(on)` — disables inputs and shows spinners while upload/ask is in flight.
- `streamSSE(resp, onEvent)` — parses ReadableStream + TextDecoder for multi-line SSE events (handles partial chunks).
- `uploadFile(file)` — POSTs file to `/upload/stream` with extraction mode; streams SSE events (start, chunk, done, error).
- `onUploadEvent(ev)` — processes upload events: logs file/page info, extracted facts per chunk, new fact count.
- `ask()` — POSTs question to `/ask/stream`; streams SSE events (decompose, retrieve, guard_keep, guard_strike, gap, answer, error).
- `onAskEvent(ev)` — processes ask events: logs sub-requirements, candidates, fact assessments, gaps, final answer with tree rendering.
- `renderAnswer(result, fallbackText)` — displays answer prose with sources and gaps.
- Menu toggle and document list click handling.
- Drag-drop event listeners for desktop file upload.
- Upload input file change listener.
- Scroll badge and log auto-scroll behavior.
- Viewport resize debouncer to refit tree.
- Boot: fetch status on page load.

---

### `gwa/ui/static/style.css`

Vanilla CSS (no framework), mobile-first, responsive breakpoint at 768px. Defines component styles, grid/flex layout, color scheme (teal/amber/red/grey), and tree node/link visualization.

**Key sections:**

- **CSS variables** — defines color palette (teal for kept facts, amber for answer, red for gaps, grey for struck), soft backgrounds, and layout constants (header height 56px, ask row height 60px).
- **Global** — system font stack, full-height flex layout, antialiased text rendering.
- **Header** — fixed navigation bar with brand, icon buttons (upload, menu), mode dropdown, status pill (teal-soft background with fact/doc count), and flexbox spacing.
- **Mode field & dropdown** — compact mode selector styled to match header buttons.
- **Menu panel** — absolute-positioned dropdown for document list with hover states and danger-colored reset button.
- **Tabs (mobile)** — bottom-of-header tab strip with teal underline for active tab; hidden on desktop (>768px).
- **Workspace panes** — flex/grid layout; `.pane` stacking on mobile (tab-switched), `.col-left` / `.col-right` grid columns on desktop; scrollable overflow.
- **Answer pane** — prose text, citations (styled badges with amber-soft background), sections (Sources/Gaps with chips and gap-line alerts).
- **Log pane** — item cards with icons, colored left borders (teal for kept, grey for struck, red for gaps/errors), nested lists, reason explanations, and auto-scroll badge.
- **Tree pane** — SVG host with dot-grid background, grab cursor, node/link styling (colored rects with text, stroke outlines, arrowhead marker), tooltip (dark overlay with teal source, white text).
- **Ask row** — bottom input bar with question text field (teal focus outline on white), primary button (solid teal background, spinner animation), flex spacing.
- **Spinner animation** — CSS keyframes rotating border; triggered via `.busy` class on buttons.
- **Drag-drop overlay** — full-viewport blur + semi-transparent teal background with dashed card when dragging files (hidden on mobile).
- **Desktop layout (>=768px)** — workspace becomes 2-column grid; left column (answer + log, 50/50 split) and right column (tree full height); all panes visible regardless of tab.

---

## Docker & dependencies

### `Dockerfile`

Containerizes the GWA application using Python 3.13 slim base image with optimized Docker layers. Builds an image that serves the Uvicorn-based FastAPI app on port 8000, running as a non-root user to keep host-mounted data ownership clean.

**Build sections:**
- **Base image & environment (lines 1–5)**: Sets Python 3.13 slim with buffering and cache disabled for lean, efficient logging.
- **Dependencies layer (lines 9–11)**: Installs requirements.txt in a cached Docker layer; pins pip and disables cache for reproducibility.
- **Application copy (lines 13–15)**: Copies the `gwa/` package and `run.py` into `/app`.
- **Non-root user setup (lines 17–20)**: Creates unprivileged `app` user (uid 10001) and prepares `/app/data` volume directory with correct ownership.
- **Service startup (lines 22–26)**: Exposes port 8000 and launches Uvicorn with `0.0.0.0` binding (required for Docker port publishing to work).

---

### `docker-compose.yml`

Orchestrates a two-container stack: the GWA brain service and a Qdrant vector database, with persistent storage and host-network binding configured via environment variables for a single-user development setup.

**Services:**
- **`brain` (lines 2–26)**: Builds and runs the GWA app from the Dockerfile; runs as the host user (uid 1000/gid 1000 by default, overridable via `BRAIN_UID`/`BRAIN_GID`) so data files remain host-owned; publishes port 8000 to localhost only (or `0.0.0.0` if `BRAIN_BIND` is set); mounts `./data` for persistent state; loads `.env` for app config; overrides `QDRANT_HOST` and `QDRANT_PORT` in-compose so the app always reaches the local Qdrant instance; depends on Qdrant and restarts unless explicitly stopped.
- **`qdrant` (lines 28–36)**: Runs Qdrant v1.12.0 (pinned for Query API compatibility); exposes port 6333 internally and on host; persists embeddings in a named volume `qdrant_data` across restarts.

**Volumes:**
- **`qdrant_data`**: Named volume storing Qdrant embeddings and metadata.

---

### `.env.example`

Template configuration file documenting all environment variables required to run GWA, with sensible defaults, commented-out optional tuning knobs, and examples for different LLM providers (Mistral, local servers, etc.).

**Configuration sections:**
- **Chat LLM (lines 1–10)**: `LLM_BASE_URL`, `GWA_MODEL`, `GWA_MAX_TOKENS`, `LLM_API_KEY_ENV` (name of env var holding the key), and optional rate-limiting/retry parameters.
- **Embeddings (lines 12–17)**: `GWA_EMBED_MODEL`, with optional overrides for non-standard embedding endpoint/key; batch size tuning.
- **Provider examples (lines 19–28)**: Quick copy-paste configs for hosted providers, Mistral, and local servers (Ollama/vLLM/TGI).
- **Qdrant (lines 30–32)**: `QDRANT_HOST`, `QDRANT_PORT`, optional collection name override.
- **Storage/ingestion (lines 35–38)**: `BRAIN_DATA_DIR`, max upload size, extraction mode (factual/prose/auto/derivation).
- **Retrieval/accumulation (lines 40–43)**: `GWA_TOP_K`, similarity threshold, accumulation weighting (fixed once set).
- **Cross-model guard (lines 45–49)**: Optional separate guard LLM configuration (disabled by default).
- **Docker compose only (lines 51–55)**: `BRAIN_PORT`, `BRAIN_BIND`, `BRAIN_UID`, `BRAIN_GID` for compose orchestration.
- **Offline/mock mode (lines 57–59)**: `GWA_MOCK=1` and in-memory Qdrant location for testing without network/keys.

---

### `requirements.txt`

Python package dependencies pinned to specific versions for the GWA FastAPI application, its web server, ORM/validation, vector database client, and document processing libraries.

- **`fastapi==0.138.1`**: Web framework for building the REST/WebSocket API.
- **`uvicorn[standard]==0.49.0`**: ASGI server to run FastAPI with standard extras (HTTP/2, WebSocket, etc.).
- **`python-multipart==0.0.32`**: Multipart form data parsing for file uploads.
- **`pydantic==2.13.4`**: Data validation and serialization for request/response models.
- **`qdrant-client==1.18.0`**: Python client for Qdrant vector database (pinned to support v1.10+ Query API).
- **`networkx==3.6.1`**: Graph algorithms library (used internally by GWA for reasoning/traversal).
- **`pdfplumber==0.11.10`**: PDF extraction and parsing for document ingestion.
- **`python-docx==1.2.0`**: Microsoft Word document parsing for `.docx` file ingestion.

---
