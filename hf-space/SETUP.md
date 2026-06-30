# Deploy the demo on a Hugging Face Space

**Variant 2**: a real chat LLM via an OpenAI-compatible provider (the **Hugging Face
Inference router** by default) + the lexical embedder + in-memory Qdrant, with the demo
brain pre-loaded (instant start, no extraction).

## Quickest — one command

Run this **yourself** (the token stays on your machine — never printed, never committed):

    pip install huggingface_hub
    HF_TOKEN=hf_xxx HF_SPACE=gwa-brain python hf-space/deploy.py     # add HF_PRIVATE=1 for private

`HF_TOKEN` must have **write** access **and** the **"Make calls to Inference Providers"**
permission — it creates/pushes the Space *and* is stored as the runtime chat key. HF then
builds it at `https://<you>-gwa-brain.hf.space`.

---

## Manual setup
1. **Create the Space** — huggingface.co → New → Space, **SDK: Docker** (blank), name `gwa-brain`.
2. **Put the files in the Space repo** (it is its own git repo):

       git clone https://huggingface.co/spaces/<you>/gwa-brain space && cd space
       cp -r ../gwa ../demo ../run.py ../requirements.txt .                       # app + pre-loaded demo brain
       cp ../hf-space/Dockerfile ../hf-space/README.md ../hf-space/demo.gif .     # HF Dockerfile + README + GIF
       git add -A && git commit -m "GWA Brain demo" && git push

3. **Add the token** — Space → Settings → Variables and secrets → New secret:
   `HF_TOKEN` = a token with write + "Make calls to Inference Providers".

## Use a different (free) provider instead — e.g. Groq
Any OpenAI-compatible endpoint works. To run on Groq's free tier, set these in
**Space → Settings → Variables and secrets** (Space variables override the Dockerfile defaults,
no redeploy needed):

| Key | Type | Value |
|---|---|---|
| `LLM_BASE_URL` | variable | `https://api.groq.com/openai/v1` |
| `GWA_MODEL` | variable | `llama-3.1-8b-instant` |
| `LLM_API_KEY_ENV` | variable | `GROQ_API_KEY` |
| `GROQ_API_KEY` | **secret** | a free key from console.groq.com |

## Notes
- **Going public? Lock it down:** set `GWA_READONLY=1` as a Space variable to disable uploads
  *and* brain-reset, so the single shared brain can't be polluted or wiped by anonymous
  visitors. The pre-loaded demo stays and questions still work; the UI hides those controls.
- A Cloudflare-fronted provider (e.g. Together via the HF router) blocks the default Python
  HTTP user-agent; the app sends a proper `User-Agent` so calls aren't rejected (override
  with `GWA_USER_AGENT` if a provider needs something specific).
- Each question makes a few chat calls (decompose · guard · formulate); a free tier is
  rate/credit-limited, so heavy traffic may hit the limit (a natural cap — no surprise bill).
- Without `GWA_READONLY`, **uploads** are enabled and call the LLM (extraction); the
  pre-loaded sample needs none. No auth — don't point heavy/untrusted traffic at it.
- **Better retrieval** (Variant 3): a local `bge-m3` embedder (sentence-transformers, ~2 GB,
  CPU) for dense search quality — more setup; ask if wanted.
