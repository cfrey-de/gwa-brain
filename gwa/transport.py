"""Shared HTTP transport for any OpenAI-compatible endpoint (hosted API or a local
server such as vLLM / Ollama / TGI).

A client-side rate limiter + POST-with-retry that honors the Retry-After header.
The SAME RateLimiter instance is shared by the chat LLM and the embedder, so chat
and embedding calls together respect one provider's rate limit (free tiers are tight,
and ingestion + Q&A make several of each).

This module is synchronous (urllib + time.sleep) on purpose: it is reused verbatim
from the parent research project. FastAPI handlers call it via asyncio.to_thread so
the blocking I/O never stalls the event loop. See gwa.ui.app.
"""
import json
import os
import random
import time
import urllib.error
import urllib.request

# A default "Python-urllib/3.x" User-Agent gets blocked by Cloudflare-fronted providers
# (e.g. Together via the Hugging Face router) as a bot -> HTTP 403. Send a well-behaved,
# identifiable one instead; override with GWA_USER_AGENT if a provider needs something else.
_USER_AGENT = (os.environ.get("GWA_USER_AGENT")
               or "Mozilla/5.0 (compatible; GWA-Brain/1.0; +https://github.com/cfrey-de/gwa-brain)")


class RateLimiter:
    def __init__(self, requests_per_second):
        self.min_interval = (1.0 / requests_per_second) if requests_per_second and requests_per_second > 0 else 0.0
        self._last = 0.0

    def wait(self):
        if self.min_interval <= 0:
            return
        delay = self._last + self.min_interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


def _retry_delay(headers, attempt, base=1.0, cap=60.0):
    if headers is not None:
        ra = headers.get("Retry-After")
        if ra:
            try:
                return float(ra)
            except ValueError:
                pass
    return min(base * (2 ** attempt) + random.uniform(0, 0.5), cap)


def post_json(url, payload, api_key=None, limiter=None, max_retries=5, timeout=180):
    """POST JSON, retrying 429/5xx/connection errors with backoff. Returns parsed dict."""
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(max_retries + 1):
        if limiter:
            limiter.wait()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", _USER_AGENT)
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if (e.code == 429 or e.code >= 500) and attempt < max_retries:
                d = _retry_delay(e.headers, attempt)
                print(f"[transport] {url} HTTP {e.code}; backing off {d:.1f}s ({attempt + 1}/{max_retries})")
                time.sleep(d)
                continue
            detail = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"HTTP {e.code} from {url}: {detail}") from e
        except urllib.error.URLError as e:  # connection refused / DNS / timeout
            if attempt < max_retries:
                d = _retry_delay(None, attempt)
                print(f"[transport] {url} unreachable ({e.reason}); retrying {d:.1f}s ({attempt + 1}/{max_retries})")
                time.sleep(d)
                continue
            raise RuntimeError(f"could not reach {url}: {e.reason}") from e
    raise RuntimeError(f"{url}: retries exhausted")
