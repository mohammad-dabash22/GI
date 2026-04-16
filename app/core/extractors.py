"""Text extraction from PDF, DOCX, and plain text files."""

import os
import fitz  # PyMuPDF
from docx import Document


MAX_SINGLE_CHUNK_CHARS = 12000


def extract_text_from_pdf(filepath: str) -> list[dict]:
    """Extract text from PDF. Small PDFs returned as single chunk."""
    doc = fitz.open(filepath)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            pages.append({"page": i + 1, "text": text.strip()})
    doc.close()

    total_chars = sum(len(p["text"]) for p in pages)
    if total_chars <= MAX_SINGLE_CHUNK_CHARS:
        combined = "\n\n".join(f"[Page {p['page']}]\n{p['text']}" for p in pages)
        if combined.strip():
            return [{"page": 1, "text": combined.strip()}]
        return []
    return pages


def extract_text_from_docx(filepath: str) -> list[dict]:
    """Extract text from DOCX. Small docs returned as single chunk."""
    doc = Document(filepath)
    paragraphs = [(i + 1, p.text.strip()) for i, p in enumerate(doc.paragraphs) if p.text.strip()]
    total_chars = sum(len(t) for _, t in paragraphs)
    if total_chars <= MAX_SINGLE_CHUNK_CHARS:
        combined = "\n\n".join(t for _, t in paragraphs)
        if combined:
            return [{"paragraph": 1, "text": combined}]
        return []
    return [{"paragraph": num, "text": text} for num, text in paragraphs]


MAX_SINGLE_CHUNK_LINES = 300
HEADER_CONTEXT_LINES = 25
CHUNK_SIZE = 80
CHUNK_OVERLAP = 15


def extract_text_from_txt(filepath: str) -> list[dict]:
    """Extract text from plain text file. Small files sent as single chunk
    to preserve context. Larger files use overlapping chunks with header prefix."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    total = len(lines)
    if total <= MAX_SINGLE_CHUNK_LINES:
        text = "".join(lines).strip()
        if text:
            return [{"line_start": 1, "line_end": total, "text": text}]
        return []

    header = "".join(lines[:HEADER_CONTEXT_LINES]).strip()
    header_prefix = f"[DOCUMENT HEADER FOR CONTEXT]\n{header}\n[END HEADER]\n\n"
    results = []
    start = 0
    while start < total:
        end = min(start + CHUNK_SIZE, total)
        chunk = "".join(lines[start:end]).strip()
        if chunk:
            text = chunk if start == 0 else header_prefix + chunk
            results.append({
                "line_start": start + 1,
                "line_end": end,
                "text": text
            })
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return results


def extract_text(filepath: str) -> tuple[str, list[dict]]:
    """Route to the right extractor based on file extension.
    Returns (filename, list_of_chunks)."""
    ext = os.path.splitext(filepath)[1].lower()
    filename = os.path.basename(filepath)
    if ext == ".pdf":
        return filename, extract_text_from_pdf(filepath)
    elif ext in (".docx", ".doc"):
        return filename, extract_text_from_docx(filepath)
    elif ext in (".txt", ".md"):
        return filename, extract_text_from_txt(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
