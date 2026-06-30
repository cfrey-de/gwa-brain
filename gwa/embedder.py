"""Embeddings. All embedders return L2-normalized vectors, so dot == cosine.

- OpenAICompatEmbedder : any OpenAI-compatible /embeddings endpoint, via the shared
  rate-limited transport. Batched (<= embed_batch per request) so large documents do
  not exceed the provider's request-size limit during ingestion.
- LexicalEmbedder      : deterministic hashed bag-of-words, zero deps. Used by the
  test suite (mock) so tests need no key and no network.

The vector dimension is never hard-coded against the store: the brain creates its
Qdrant collection from the first vector's length, so a 1024-dim model and the 256-dim
lexical test embedder both work.
"""
import hashlib
import math
import re

from gwa.transport import post_json

_TOK = re.compile(r"[a-z0-9äöüß]+")


def tokenize(text):
    return _TOK.findall(text.lower())


def _l2(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class LexicalEmbedder:
    name = "lexical"

    def __init__(self, dim=256):
        self.dim = dim

    def embed(self, texts):
        return [self._vec(t) for t in texts]

    def _vec(self, text):
        v = [0.0] * self.dim
        for tok in tokenize(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            v[h % self.dim] += 1.0
        return _l2(v)


class OpenAICompatEmbedder:
    name = "api"

    def __init__(self, model, base_url, api_key=None, limiter=None, max_retries=5, batch=64):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.limiter = limiter
        self.max_retries = max_retries
        self.batch = max(1, int(batch))

    def embed(self, texts):
        texts = list(texts)
        if not texts:
            return []
        out = []
        for i in range(0, len(texts), self.batch):
            chunk = texts[i:i + self.batch]
            body = post_json(self.base_url + "/embeddings",
                             {"model": self.model, "input": chunk},
                             self.api_key, self.limiter, self.max_retries)
            rows = sorted(body["data"], key=lambda d: d.get("index", 0))  # keep input order
            out.extend(_l2(r["embedding"]) for r in rows)
        return out


def make_embedder(cfg, limiter=None, api_key=None):
    mode = cfg.get("embeddings", "api")
    if mode == "lexical":
        return LexicalEmbedder()
    m = cfg.get("endpoint", {})
    return OpenAICompatEmbedder(
        cfg.get("embeddings_api_model", ""),
        base_url=m.get("base_url", ""),
        api_key=api_key, limiter=limiter, max_retries=m.get("max_retries", 5),
        batch=cfg.get("embed_batch", 64),
    )
