"""LLM access — any OpenAI-compatible /chat/completions endpoint.

One uniform call:
    complete(role, system, user, temperature=None) -> str

Backends:
- OpenAICompatLLM : any OpenAI-compatible endpoint (hosted API or a local server)
                    via the shared rate-limited, retrying transport.
- MockLLM         : deterministic, role-aware stub. No key / no network. It really
                    transforms its input (sentence-splits for extract, token-overlap
                    for guard, builds cited prose for formulate) so the test suite
                    exercises the pipeline meaningfully.

We ask for JSON in the prompt and parse it ourselves (extract_json), so nothing
depends on a provider's structured-output API.
"""
import json
import re

from gwa.transport import RateLimiter, post_json

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_TOK = re.compile(r"[a-zA-Z0-9äöüÄÖÜß]+")
# English + German function words (used by the MockLLM token-overlap heuristic). The
# list just needs the languages you ingest; the logic itself is language-agnostic.
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "is", "are",
    "was", "were", "be", "by", "with", "as", "that", "this", "it", "its",
    "der", "die", "das", "und", "oder", "von", "zu", "im", "in", "auf", "bei", "für",
    "ist", "sind", "war", "den", "dem", "des", "ein", "eine", "einer", "mit", "wie",
    "nach", "aus", "an", "am", "als", "nicht", "auch",
}


def extract_json(text: str) -> dict:
    """Tolerant JSON parse: strips ``` fences, falls back to the first {...} span."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j > i:
            return json.loads(s[i:j + 1])
        raise ValueError(f"could not parse JSON from model output:\n{text}")


def _content_tokens(text):
    return {t for t in _TOK.findall((text or "").lower()) if t not in _STOP and len(t) > 1}


class OpenAICompatLLM:
    """Any OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, model, max_tokens, base_url, api_key=None,
                 default_temperature=None, limiter=None, max_retries=5, timeout=180):
        self.model = model
        self.max_tokens = max_tokens
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_temperature = default_temperature
        self.limiter = limiter
        self.max_retries = max_retries
        self.timeout = timeout

    def complete(self, role, system, user, temperature=None) -> str:
        temp = temperature if temperature is not None else self.default_temperature
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if temp is not None:
            payload["temperature"] = temp
        body = post_json(self.base_url + "/chat/completions", payload,
                         self.api_key, self.limiter, self.max_retries, self.timeout)
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"unexpected response shape from {self.base_url}: {str(body)[:300]}")
        if content is None:
            raise RuntimeError(f"empty response content from {self.base_url}: {str(body)[:300]}")
        return content


class MockLLM:
    """Deterministic, role-aware stub used by the test suite (no key, no network).

    It genuinely transforms its input so the pipeline does real work under test:
      - role 'extract'   : sentence-splits the chunk -> {"facts": [...]}
      - role 'decompose' : splits the question on separators -> {"sub_requirements": [...]}
      - role 'guard'     : token-overlap keep/strike over a JSON candidate list
      - role 'formulate' : builds cited prose from a JSON fact list (+ gap note)
    """

    def complete(self, role, system, user, temperature=None) -> str:
        if role == "extract":
            facts, seen = [], set()
            for s in _SENT.split(user or ""):
                s = s.strip().strip("-*•").strip()
                if len(_TOK.findall(s)) >= 3 and s.lower() not in seen:
                    seen.add(s.lower())
                    facts.append(s if s[-1:] in ".!?" else s + ".")
            return json.dumps({"facts": facts}, ensure_ascii=False)

        if role == "decompose":
            q = (user or "").strip()
            parts = re.split(r",| und | and |;|\?", q)
            subs = [p.strip(" .?") for p in parts if len(_TOK.findall(p)) >= 1]
            subs = [s for s in subs if s] or ([q.strip(" ?")] if q else [])
            return json.dumps({"sub_requirements": subs}, ensure_ascii=False)

        if role == "guard":
            data = extract_json(user)
            req_toks = set()
            for r in data.get("requirements", []):
                req_toks |= _content_tokens(r)
            verdicts = []
            for c in data.get("candidates", []):
                overlap = _content_tokens(c.get("text", "")) & req_toks
                keep = len(overlap) >= 1
                verdicts.append({
                    "id": c.get("id"),
                    "keep": keep,
                    "reason": ("covers: " + ", ".join(sorted(overlap))) if keep
                    else "off-target: no content term of the requirement covered",
                })
            return json.dumps({"verdicts": verdicts}, ensure_ascii=False)

        if role == "formulate":
            data = extract_json(user)
            lines = []
            for f in data.get("facts", []):
                txt = f.get("text", "").strip()
                src = f.get("source", "")
                if txt:
                    lines.append(f"{txt} [{src}]" if src else txt)
            if not lines and not data.get("gaps"):
                return "No supported facts available to answer."
            out = " ".join(lines)
            gaps = data.get("gaps", [])
            if gaps:
                out += " ⚠ Not supported: " + "; ".join(gaps) + "."
            return out

        return "{}"


def make_llm(cfg, limiter=None):
    provider = cfg.get("provider", "openai-compatible").lower()
    if provider == "mock":
        return MockLLM()
    if provider == "openai-compatible":
        import os
        m = cfg.get("endpoint", {})
        if limiter is None:
            limiter = RateLimiter(m.get("requests_per_second", 1.0))
        key_env = m.get("api_key_env", "LLM_API_KEY")
        api_key = os.environ.get(key_env) if key_env else None
        return OpenAICompatLLM(
            cfg["model"], cfg["max_tokens"],
            base_url=m.get("base_url", ""),
            api_key=api_key, default_temperature=m.get("temperature"),
            limiter=limiter, max_retries=m.get("max_retries", 5),
        )
    raise ValueError(f"unknown provider: {provider!r} (use 'openai-compatible' or 'mock')")
