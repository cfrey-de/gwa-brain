"""Local dev entrypoint.

    python run.py            # serve on http://localhost:8000

Live mode needs a reachable Qdrant (QDRANT_HOST/QDRANT_PORT) and an OpenAI-compatible
LLM endpoint configured in .env (LLM_BASE_URL, GWA_MODEL, GWA_EMBED_MODEL, and the API
key named by LLM_API_KEY_ENV). For an offline smoke run with no key and no Qdrant server:

    GWA_MOCK=1 QDRANT_LOCATION=:memory: python run.py

The full stack (Qdrant + app) is one command: `docker compose up --build`.
"""
import os

import uvicorn

if __name__ == "__main__":
    # loopback by default (single-user PoC, no auth); override with BRAIN_HOST=0.0.0.0
    host = os.getenv("BRAIN_HOST", "127.0.0.1")
    uvicorn.run("gwa.ui.app:app", host=host, port=int(os.getenv("PORT", "8000")), reload=False)
