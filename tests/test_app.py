"""M4: the FastAPI app — REST + SSE end to end, mock backend (no key, no network)."""
import json

import pytest
from fastapi.testclient import TestClient


def _events(resp_text):
    out = []
    for line in resp_text.splitlines():
        if line.startswith("data:"):
            out.append(json.loads(line[5:].strip()))
    return out


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("GWA_MOCK", "1")
    monkeypatch.setenv("QDRANT_LOCATION", ":memory:")
    monkeypatch.setenv("BRAIN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("QDRANT_COLLECTION", "app_test")
    from gwa.ui.app import app
    with TestClient(app) as c:
        yield c


def test_healthz_and_empty_status(client):
    assert client.get("/healthz").json() == {"ok": True}
    st = client.get("/brain/status").json()
    assert st == {"facts": 0, "documents": 0, "docs": [], "readonly": False}


def test_readonly_blocks_uploads_and_reset(monkeypatch, tmp_path):
    """GWA_READONLY serves a fixed brain: uploads + reset are refused, asking still works."""
    monkeypatch.setenv("GWA_MOCK", "1")
    monkeypatch.setenv("QDRANT_LOCATION", ":memory:")
    monkeypatch.setenv("BRAIN_DATA_DIR", str(tmp_path / "ro"))
    monkeypatch.setenv("QDRANT_COLLECTION", "ro_test")
    monkeypatch.setenv("GWA_READONLY", "1")
    from gwa.ui.app import app
    with TestClient(app) as c:
        assert c.get("/brain/status").json()["readonly"] is True
        up = c.post("/upload/stream", files={"file": ("t.txt", b"hi", "text/plain")})
        assert up.status_code == 403
        assert c.post("/brain/reset").status_code == 403
        assert c.post("/ask/stream", json={"question": "anything?"}).status_code == 200


def test_upload_then_ask_stream(client):
    doc = ("Der Wasserstand sinkt nach 500 Stunden auf 160 Zentimeter.\n\n"
           "Der Wasserstand betraegt nach 100 Stunden noch 180 Zentimeter.\n\n"
           "Der Zulauf besteht aus einem Stahlrohr.\n").encode("utf-8")
    up = client.post("/upload/stream", files={"file": ("Bericht.txt", doc, "text/plain")})
    assert up.status_code == 200
    ev = _events(up.text)
    assert ev[0]["type"] == "start"
    done = ev[-1]
    assert done["type"] == "done" and done["new_facts"] >= 3

    st = client.get("/brain/status").json()
    assert st["facts"] >= 3 and st["documents"] == 1

    ask = client.post("/ask/stream", json={"question": "Wie hoch ist der Wasserstand nach 500 Stunden?"})
    assert ask.status_code == 200
    aev = _events(ask.text)
    types = [e["type"] for e in aev]
    assert types[0] == "decompose"
    assert types[-1] == "answer"
    answer_ev = aev[-1]
    result = answer_ev["result"]
    assert any("500" in f["text"] and "160" in f["text"] for f in result["used_facts"])
    assert any("100 Stunden" in f["text"] for f in result["struck_facts"])  # near neighbour surfaced
    assert "[Bericht.txt" in answer_ev["text"]
    # graph endpoint reflects accumulation
    g = client.get("/graph").json()
    assert g["facts"] >= 3


def test_dotted_filename_does_not_500(client):
    # filename "." / ".." must resolve to a safe basename, not write the dir (raw 500)
    up = client.post("/upload/stream", files={"file": (".", b"Das Gehaeuse ist robust.\n", "text/plain")})
    assert up.status_code == 200
    assert _events(up.text)[-1]["type"] == "done"


def test_upload_too_large_returns_413(monkeypatch, tmp_path):
    monkeypatch.setenv("GWA_MOCK", "1")
    monkeypatch.setenv("QDRANT_LOCATION", ":memory:")
    monkeypatch.setenv("BRAIN_DATA_DIR", str(tmp_path / "data2"))
    monkeypatch.setenv("QDRANT_COLLECTION", "big_test")
    monkeypatch.setenv("BRAIN_MAX_UPLOAD_BYTES", "64")
    from gwa.ui.app import app
    with TestClient(app) as c:
        big = b"x" * 5000
        r = c.post("/upload/stream", files={"file": ("big.txt", big, "text/plain")})
        assert r.status_code == 413
        assert c.get("/brain/status").json()["facts"] == 0


def test_reset(client):
    doc = b"Das Gehaeuse ist robust und langlebig.\n"
    client.post("/upload/stream", files={"file": ("a.txt", doc, "text/plain")})
    assert client.get("/brain/status").json()["facts"] >= 1
    assert client.post("/brain/reset").json() == {"ok": True}
    assert client.get("/brain/status").json()["facts"] == 0
