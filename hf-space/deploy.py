#!/usr/bin/env python3
"""One-command deploy of this project as a Hugging Face Space (Docker SDK, Variant 2).

Run it YOURSELF so the token never leaves your machine (never printed, never committed):

    pip install huggingface_hub
    HF_TOKEN=hf_xxx HF_SPACE=gwa-brain python hf-space/deploy.py

    HF_TOKEN     = a Hugging Face token with WRITE + "Make calls to Inference Providers"
                   (used to create/push the Space AND stored as the Space's runtime secret)
    HF_SPACE     = space name (default: gwa-brain)
    HF_PRIVATE=1 = create a PRIVATE space (default: public)

The chat model runs on the Hugging Face Inference router by default; any OpenAI-compatible
provider works (e.g. Groq) — override LLM_BASE_URL / GWA_MODEL / LLM_API_KEY_ENV + key as
Space variables (see SETUP.md).
"""
import os
import pathlib
import shutil
import tempfile

from huggingface_hub import HfApi

token = os.environ.get("HF_TOKEN")
if not token:
    raise SystemExit("set HF_TOKEN (a Hugging Face access token with write access)")
name = os.environ.get("HF_SPACE", "gwa-brain")
private = os.environ.get("HF_PRIVATE", "0") == "1"

api = HfApi(token=token)
user = api.whoami()["name"]
repo_id = f"{user}/{name}"
print(f"Deploying to Space: {repo_id}  ({'private' if private else 'public'})")

api.create_repo(repo_id, repo_type="space", space_sdk="docker",
                private=private, exist_ok=True)
# the running Space calls the HF Inference router with this token at runtime
api.add_space_secret(repo_id=repo_id, key="HF_TOKEN", value=token)

root = pathlib.Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory() as td:
    stage = pathlib.Path(td)
    for item in ("gwa", "demo", "run.py", "requirements.txt"):          # the app + pre-built demo brain
        src = root / item
        (shutil.copytree if src.is_dir() else shutil.copy)(src, stage / item)
    for item in ("Dockerfile", "README.md", "demo.gif"):                # HF files at the Space root
        shutil.copy(root / "hf-space" / item, stage / item)
    api.upload_folder(repo_id=repo_id, repo_type="space",
                      folder_path=str(stage), commit_message="Deploy GWA Brain demo")

print(f"Done. Build/logs:  https://huggingface.co/spaces/{repo_id}")
print(f"Live (after build): https://{user.lower()}-{name.lower()}.hf.space")
