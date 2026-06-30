"""Document -> chunks. Supports PDF (pdfplumber), Word (python-docx), text/markdown.

Chunking targets ~300 tokens with boundaries at paragraphs/headings, so a chunk is
a coherent unit and its citation (page for PDF, paragraph number otherwise) is stable.
"""
from dataclasses import dataclass
from typing import Optional

TARGET_TOKENS = 300


@dataclass
class Chunk:
    text: str
    index: int
    source_doc: str
    chunk_id: str
    page: Optional[int] = None
    paragraph: Optional[int] = None
    context: Optional[str] = None   # document heading/title, to resolve implicit fact subjects


def _ntok(text: str) -> int:
    return len(text.split())


def _doc_heading(units):
    """The document's title/heading, if the first unit looks like one (short, no terminal
    sentence punctuation). Passed to extraction so an implicit fact subject — 'the pump' under
    a 'Pump Station P-12' heading — can be resolved into a self-contained fact."""
    if not units:
        return None
    head = (units[0][0] or "").strip()
    if 0 < len(head) <= 90 and head[-1] not in ".!?" and any(c.isalpha() for c in head):
        return head
    return None


def _pack(units, source_doc, target=TARGET_TOKENS, context=None):
    """units: list[(paragraph_text, page_or_None)] -> list[Chunk] (~target tokens each)."""
    chunks, buf, buf_page, buf_par, tok = [], [], None, None, 0
    for par_idx, (text, page) in enumerate(units):
        text = text.strip()
        if not text:
            continue
        wt = _ntok(text)
        if buf and tok + wt > target:
            chunks.append((" ".join(buf), buf_page, buf_par))
            buf, tok = [], 0
        if not buf:
            buf_page, buf_par = page, par_idx + 1
        buf.append(text)
        tok += wt
    if buf:
        chunks.append((" ".join(buf), buf_page, buf_par))
    return [
        Chunk(text=t, index=i, source_doc=source_doc,
              chunk_id=f"{source_doc}#c{i}", page=p, paragraph=par, context=context)
        for i, (t, p, par) in enumerate(chunks)
    ]


def _pdf_units(path):
    import pdfplumber
    units, pages = [], 0
    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for para in text.split("\n\n"):
                para = " ".join(para.split())
                if para:
                    units.append((para, pno))
    return units, pages


def _docx_units(path):
    import docx
    doc = docx.Document(path)
    units = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            units.append((t, None))
    return units, None


def _text_units(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    units = [( " ".join(p.split()), None) for p in raw.split("\n\n")]
    return [(t, n) for t, n in units if t], None


_EXT = {
    "pdf": _pdf_units,
    "docx": _docx_units,
    "txt": _text_units,
    "md": _text_units,
    "markdown": _text_units,
    "text": _text_units,
}


def extract(path, filename):
    """-> (chunks: list[Chunk], pages: int|None). Raises ValueError on unsupported type."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    fn = _EXT.get(ext)
    if fn is None:
        raise ValueError(f"unsupported file type: .{ext} (use pdf, docx, txt, md)")
    units, pages = fn(path)
    return _pack(units, filename, context=_doc_heading(units)), pages
