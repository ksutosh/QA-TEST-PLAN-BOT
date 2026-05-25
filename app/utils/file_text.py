"""Extract plain text from uploaded file bytes for LLM context."""

from __future__ import annotations

import io
from typing import Optional

from app.utils.html_text import html_storage_to_plain_text

# Per-file cap after extraction (keeps prompts bounded).
DEFAULT_MAX_EXTRACT_CHARS = 80_000

_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
    ".rst",
    ".ini",
    ".cfg",
    ".properties",
    ".toml",
    ".tsv",
}

_TEXT_MIMES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/xml",
    "application/json",
    "application/xml",
    "application/x-yaml",
    "text/yaml",
    "text/x-markdown",
}


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _looks_like_text(data: bytes, sample_size: int = 4096) -> bool:
    if not data:
        return False
    sample = data[:sample_size]
    if b"\x00" in sample:
        return False
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    printable = sum(1 for c in text if c.isprintable() or c in "\n\r\t")
    return printable / max(len(text), 1) > 0.85


def _is_text_type(filename: str, mimetype: Optional[str]) -> bool:
    name = (filename or "").lower()
    mime = (mimetype or "").lower()
    if any(name.endswith(ext) for ext in _TEXT_EXTENSIONS):
        return True
    if mime in _TEXT_MIMES or mime.startswith("text/"):
        return True
    return False


def _extract_pdf(data: bytes) -> Optional[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
        return "\n\n".join(pages).strip() or None
    except Exception:
        return None


def _extract_docx(data: bytes) -> Optional[str]:
    try:
        from docx import Document
    except ImportError:
        return None
    try:
        doc = Document(io.BytesIO(data))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs).strip() or None
    except Exception:
        return None


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 40] + "\n\n... (truncated for length)"


def extract_text_from_bytes(
    data: bytes,
    filename: str = "",
    mimetype: Optional[str] = None,
    max_chars: int = DEFAULT_MAX_EXTRACT_CHARS,
) -> Optional[str]:
    """
    Best-effort text extraction from common document types.
    Returns None if the format is unsupported or extraction fails.
    """
    if not data:
        return None

    name = (filename or "").lower()
    mime = (mimetype or "").lower()
    result: Optional[str] = None

    if _is_text_type(name, mime):
        result = _decode_text(data)
    elif name.endswith(".pdf") or mime == "application/pdf":
        result = _extract_pdf(data)
    elif name.endswith(".docx") or "wordprocessingml.document" in mime:
        result = _extract_docx(data)
    elif name.endswith((".html", ".htm")) or "html" in mime:
        result = html_storage_to_plain_text(_decode_text(data))
    elif _looks_like_text(data):
        result = _decode_text(data)

    if not result or not result.strip():
        return None
    return _truncate(result.strip(), max_chars)
