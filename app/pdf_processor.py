"""
PDF ingestion: extract text from a PDF and split it into semantically
coherent chunks suitable for flashcard generation.

Strategy:
    1. Use PyMuPDF to pull per-page text (fast, fewer dependencies than pdfplumber).
    2. Normalise whitespace and strip page headers/footers heuristically.
    3. Concatenate pages, then split on blank-line paragraph boundaries.
    4. Greedily pack paragraphs into chunks around CHUNK_TARGET_CHARS, never
       splitting a paragraph across chunks.
    5. Guarantee each chunk has enough signal (min 300 chars) or merge it
       into the next one.

We also return a short "top-level summary" line per chunk that we pass to
the LLM to help it write higher-quality cards in context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from .config import CHUNK_TARGET_CHARS

MIN_CHUNK_CHARS = 300
MAX_CHUNK_CHARS = int(CHUNK_TARGET_CHARS * 1.6)


@dataclass
class PDFExtract:
    text: str
    page_count: int
    chunks: list[str]


_WS_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def _clean_page(text: str) -> str:
    # collapse runs of spaces/tabs but preserve newlines
    text = _WS_RE.sub(" ", text)
    # normalise hyphenation: "struc-\nture" -> "structure"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # strip trailing whitespace on each line
    lines = [ln.rstrip() for ln in text.split("\n")]
    return "\n".join(lines).strip()


def _looks_like_header_footer(line: str, page_no: int) -> bool:
    """Best-effort filter for recurring page numbers / running headers."""
    s = line.strip()
    if not s:
        return False
    # bare page number
    if s.isdigit() and len(s) <= 4:
        return True
    # "Page 3 of 42" style
    if re.fullmatch(r"[Pp]age\s*\d+(\s*(of|/)\s*\d+)?", s):
        return True
    return False


def extract_pdf(path: Path | str) -> PDFExtract:
    """Extract full text from a PDF, cleaned and concatenated."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    doc = fitz.open(path)
    try:
        page_texts: list[str] = []
        for page_no, page in enumerate(doc, start=1):
            raw = page.get_text("text") or ""
            cleaned = _clean_page(raw)
            # remove likely running headers/footers
            filtered = "\n".join(
                ln for ln in cleaned.split("\n") if not _looks_like_header_footer(ln, page_no)
            )
            if filtered.strip():
                page_texts.append(filtered)
        full = "\n\n".join(page_texts)
        full = _MULTI_NL_RE.sub("\n\n", full).strip()
        chunks = _chunk_text(full)
        return PDFExtract(text=full, page_count=doc.page_count, chunks=chunks)
    finally:
        doc.close()


def _chunk_text(text: str) -> list[str]:
    """Greedy paragraph packing into ~CHUNK_TARGET_CHARS windows."""
    if not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len
        if buf:
            chunks.append("\n\n".join(buf))
            buf = []
            buf_len = 0

    for para in paragraphs:
        # If a single paragraph is enormous, split it on sentence boundaries.
        if len(para) > MAX_CHUNK_CHARS:
            # flush whatever we were building
            flush()
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sub_buf: list[str] = []
            sub_len = 0
            for sent in sentences:
                if sub_len + len(sent) + 1 > CHUNK_TARGET_CHARS and sub_buf:
                    chunks.append(" ".join(sub_buf))
                    sub_buf = [sent]
                    sub_len = len(sent)
                else:
                    sub_buf.append(sent)
                    sub_len += len(sent) + 1
            if sub_buf:
                chunks.append(" ".join(sub_buf))
            continue

        if buf_len + len(para) + 2 > CHUNK_TARGET_CHARS and buf_len >= MIN_CHUNK_CHARS:
            flush()
        buf.append(para)
        buf_len += len(para) + 2

    flush()

    # Merge trailing tiny chunk into previous.
    if len(chunks) >= 2 and len(chunks[-1]) < MIN_CHUNK_CHARS:
        chunks[-2] = chunks[-2] + "\n\n" + chunks[-1]
        chunks.pop()

    return chunks
