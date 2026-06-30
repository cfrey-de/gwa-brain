"""Central configuration — every env variable lives here.

The chat LLM and the embedder target any OpenAI-compatible `/chat/completions` and
`/embeddings` endpoint (a hosted API, or a local server such as vLLM / Ollama / TGI).
Point them at your endpoint via .env (see .env.example). The embedder defaults to the
same endpoint and key as the chat model, but can be configured separately.

The guard runs on the same chat model by default (a conservative, UNMEASURED product
guard — see README); an optional cross-model hook (GUARD_CROSS_*) is off by default.
"""
import os
from dataclasses import dataclass, field


def _env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _env_bool(name, default=False):
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    # --- chat LLM (OpenAI-compatible /chat/completions) ---
    model: str = field(default_factory=lambda: _env("GWA_MODEL", ""))
    # generous ceiling, not a target: reasoning models spend tokens on internal reasoning
    # BEFORE emitting the JSON answer, so a low cap truncates content to empty
    # (finish_reason=length). You only pay for tokens actually generated.
    max_tokens: int = field(default_factory=lambda: _env_int("GWA_MAX_TOKENS", 8192))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", ""))
    llm_api_key_env: str = field(default_factory=lambda: _env("LLM_API_KEY_ENV", "LLM_API_KEY"))
    temperature: float = field(default_factory=lambda: _env_float("GWA_TEMPERATURE", 0.2))
    requests_per_second: float = field(default_factory=lambda: _env_float("GWA_RPS", 1.0))
    max_retries: int = field(default_factory=lambda: _env_int("GWA_MAX_RETRIES", 5))

    # --- embeddings (OpenAI-compatible /embeddings; default = same endpoint as chat) ---
    embed_model: str = field(default_factory=lambda: _env("GWA_EMBED_MODEL", ""))
    embed_base_url: str = field(default_factory=lambda: _env("EMBED_BASE_URL", ""))
    embed_api_key_env: str = field(default_factory=lambda: _env("EMBED_API_KEY_ENV", ""))
    embed_batch: int = field(default_factory=lambda: _env_int("GWA_EMBED_BATCH", 64))
    # auto = lexical in mock, else API. Force "lexical" to run a REAL chat LLM with the
    # zero-dependency lexical embedder (e.g. a hosted demo whose chat endpoint has no
    # /embeddings route, like Hugging Face's router). "api" forces the embedding endpoint.
    embed_backend: str = field(default_factory=lambda: _env("GWA_EMBED", "auto"))

    # --- Qdrant ---
    qdrant_host: str = field(default_factory=lambda: _env("QDRANT_HOST", "localhost"))
    qdrant_port: int = field(default_factory=lambda: _env_int("QDRANT_PORT", 6333))
    qdrant_location: str = field(default_factory=lambda: _env("QDRANT_LOCATION", ""))  # ":memory:" for tests
    collection: str = field(default_factory=lambda: _env("QDRANT_COLLECTION", "gwa_facts"))

    # --- Storage ---
    data_dir: str = field(default_factory=lambda: _env("BRAIN_DATA_DIR", "./data"))
    max_upload_bytes: int = field(default_factory=lambda: _env_int("BRAIN_MAX_UPLOAD_BYTES", 25 * 1024 * 1024))

    # --- Ingestion: factual | prose | auto (factual, prose-fallback on empty) | derivation ---
    extract_mode: str = field(default_factory=lambda: _env("GWA_EXTRACT_MODE", "auto"))

    # --- Retrieval / pipeline params (fixed once; per-query tuning = nothing measured) ---
    top_k: int = field(default_factory=lambda: _env_int("GWA_TOP_K", 20))
    min_sim: float = field(default_factory=lambda: _env_float("GWA_MIN_SIM", 0.30))
    accumulation_weight: float = field(default_factory=lambda: _env_float("GWA_ACCUM_WEIGHT", 0.15))

    # --- Guard (optional cross-model hook; OFF by default) ---
    guard_cross_enabled: bool = field(default_factory=lambda: _env_bool("GUARD_CROSS_ENABLED", False))
    guard_cross_model: str = field(default_factory=lambda: _env("GUARD_CROSS_MODEL", ""))
    guard_cross_base_url: str = field(default_factory=lambda: _env("GUARD_CROSS_BASE_URL", ""))
    guard_cross_api_key_env: str = field(default_factory=lambda: _env("GUARD_CROSS_API_KEY_ENV", ""))

    # --- Mode ---
    mock: bool = field(default_factory=lambda: _env_bool("GWA_MOCK", False))
    # Read-only demo: disable uploads + brain reset (a public hosted demo with a fixed brain,
    # whose single shared brain must not be polluted or wiped by anonymous visitors).
    readonly: bool = field(default_factory=lambda: _env_bool("GWA_READONLY", False))

    def __post_init__(self):
        # the embedder defaults to the chat endpoint/key unless explicitly overridden
        self.embed_base_url = self.embed_base_url or self.llm_base_url
        self.embed_api_key_env = self.embed_api_key_env or self.llm_api_key_env

    # ---- derived helpers ----
    @property
    def llm_api_key(self):
        return os.environ.get(self.llm_api_key_env) if self.llm_api_key_env else None

    @property
    def embed_api_key(self):
        return os.environ.get(self.embed_api_key_env) if self.embed_api_key_env else None

    @property
    def use_lexical_embeddings(self) -> bool:
        """True when the zero-dependency lexical embedder should be used instead of an
        embedding API — forced by GWA_EMBED=lexical, or implied by mock mode."""
        b = (self.embed_backend or "auto").lower()
        if b == "lexical":
            return True
        if b == "api":
            return False
        return self.mock   # auto

    def missing(self):
        """Required config that is absent (for a clear startup error; empty in mock)."""
        if self.mock:
            return []
        need = []
        if not self.llm_base_url:
            need.append("LLM_BASE_URL")
        if not self.model:
            need.append("GWA_MODEL")
        if not self.llm_api_key:
            need.append(f"{self.llm_api_key_env} (chat API key)")
        if not self.use_lexical_embeddings:   # API embeddings need their own model + key
            if not self.embed_model:
                need.append("GWA_EMBED_MODEL")
            if not self.embed_api_key:
                need.append(f"{self.embed_api_key_env} (embedding API key)")
        return need

    def llm_cfg(self):
        """cfg dict for gwa.llm.make_llm (OpenAI-compatible path)."""
        return {
            "provider": "mock" if self.mock else "openai-compatible",
            "model": self.model,
            "max_tokens": self.max_tokens,
            "endpoint": {
                "base_url": self.llm_base_url,
                "api_key_env": self.llm_api_key_env,
                "requests_per_second": self.requests_per_second,
                "max_retries": self.max_retries,
                "temperature": self.temperature,
            },
        }

    def embed_cfg(self):
        return {
            "embeddings": "lexical" if self.use_lexical_embeddings else "api",
            "embeddings_api_model": self.embed_model,
            "embed_batch": self.embed_batch,
            "endpoint": {
                "base_url": self.embed_base_url,
                "max_retries": self.max_retries,
            },
        }

    def guard_cross_cfg(self):
        """cfg dict for the OPTIONAL cross-model guard (None when disabled)."""
        if not self.guard_cross_enabled or not self.guard_cross_model:
            return None
        return {
            "provider": "openai-compatible",
            "model": self.guard_cross_model,
            "max_tokens": self.max_tokens,
            "endpoint": {
                "base_url": self.guard_cross_base_url or self.llm_base_url,
                "api_key_env": self.guard_cross_api_key_env or self.llm_api_key_env,
                "requests_per_second": self.requests_per_second,
                "max_retries": self.max_retries,
                "temperature": 0.0,
            },
        }


def get_settings():
    return Settings()
