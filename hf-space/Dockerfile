# Hugging Face Space (Docker SDK) — GWA Brain demo.
#
# Variant 2: a REAL chat LLM via an OpenAI-compatible provider (default: the Hugging Face
# Inference router), with the zero-dependency LEXICAL embedder and an in-memory Qdrant. The
# demo brain (demo/brain.json) is pre-loaded, so there is NO extraction or embedding-API
# call on startup — only a one-off, instant lexical re-index.
#
# Set HF_TOKEN as a Space secret (a token with "Make calls to Inference Providers"). Any
# OpenAI-compatible endpoint works — e.g. Groq's free tier: override LLM_BASE_URL,
# GWA_MODEL and LLM_API_KEY_ENV as Space variables (see SETUP.md). Nothing secret here.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY gwa ./gwa
COPY run.py .
COPY demo ./demo

ENV PORT=7860 \
    BRAIN_HOST=0.0.0.0 \
    QDRANT_LOCATION=":memory:" \
    BRAIN_DATA_DIR=/app/data \
    GWA_MOCK=0 \
    GWA_EMBED=lexical \
    GWA_MAX_TOKENS=8192 \
    LLM_BASE_URL=https://router.huggingface.co/v1 \
    LLM_API_KEY_ENV=HF_TOKEN \
    GWA_MODEL=Qwen/Qwen2.5-7B-Instruct

# pre-load the demo brain so the Space starts instantly (facts already extracted)
RUN useradd -m -u 1000 user \
 && mkdir -p /app/data \
 && cp demo/brain.json /app/data/brain.json \
 && chown -R user:user /app
USER user

EXPOSE 7860
CMD ["python", "run.py"]
