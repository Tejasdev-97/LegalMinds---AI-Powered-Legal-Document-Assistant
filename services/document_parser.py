"""
document_parser.py — Extract text from PDF, DOCX, and TXT files.
Preserves page boundaries for document-grounded AI answers.
"""

import os
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from docx import Document
except ImportError:
    Document = None


def extract_text_from_file(file_path: str, file_type: str) -> dict:
    """
    Extract text and metadata from a document.
    Returns dict with 'text', 'pages', 'metadata'.
    """
    ext = file_type.lower()
    if ext == "pdf":
        return _extract_pdf(file_path)
    elif ext == "docx":
        return _extract_docx(file_path)
    elif ext == "txt":
        return _extract_txt(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _extract_pdf(file_path: str) -> dict:
    """Extract text from a PDF file, preserving page boundaries."""
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed. Please run: pip install PyMuPDF")
    doc = fitz.open(file_path)
    pages = []
    full_text_parts = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        pages.append({"page": page_num + 1, "text": text.strip()})
        if text.strip():
            full_text_parts.append(f"[Page {page_num + 1}]\n{text.strip()}")

    doc.close()

    full_text = "\n\n".join(full_text_parts)
    total_pages = len(pages)

    return {
        "text": full_text,
        "pages": pages,
        "metadata": {
            "total_pages": total_pages,
            "file_type": "PDF",
        },
    }


def _extract_docx(file_path: str) -> dict:
    """Extract text from a DOCX file. DOCX has no real pages; we simulate sections."""
    if Document is None:
        raise RuntimeError("python-docx is not installed. Please run: pip install python-docx")
    document = Document(file_path)
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    full_text = "\n".join(paragraphs)

    # Estimate pages roughly at ~400 words per page
    words = full_text.split()
    words_per_page = 400
    estimated_pages = max(1, len(words) // words_per_page + (1 if len(words) % words_per_page else 0))

    pages = []
    chunk_size = words_per_page
    for i in range(estimated_pages):
        chunk_words = words[i * chunk_size : (i + 1) * chunk_size]
        pages.append({"page": i + 1, "text": " ".join(chunk_words)})

    return {
        "text": full_text,
        "pages": pages,
        "metadata": {
            "total_pages": estimated_pages,
            "file_type": "DOCX",
        },
    }


def _extract_txt(file_path: str) -> dict:
    """Extract text from a plain text file."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        full_text = f.read()

    words = full_text.split()
    words_per_page = 400
    estimated_pages = max(1, len(words) // words_per_page + (1 if len(words) % words_per_page else 0))

    pages = []
    chunk_size = words_per_page
    for i in range(estimated_pages):
        chunk_words = words[i * chunk_size : (i + 1) * chunk_size]
        pages.append({"page": i + 1, "text": " ".join(chunk_words)})

    return {
        "text": full_text,
        "pages": pages,
        "metadata": {
            "total_pages": estimated_pages,
            "file_type": "TXT",
        },
    }


def search_in_text(text: str, query: str) -> list:
    """
    Simple keyword search in document text.
    Returns list of snippets with page context.
    """
    query_lower = query.lower()
    results = []

    # Split on page markers if available
    import re
    page_blocks = re.split(r"\[Page (\d+)\]", text)

    if len(page_blocks) > 1:
        # PDF format with page markers
        i = 1
        while i < len(page_blocks) - 1:
            page_num = page_blocks[i]
            page_text = page_blocks[i + 1]
            lines = page_text.split("\n")
            for line in lines:
                if query_lower in line.lower() and line.strip():
                    results.append({
                        "page": int(page_num),
                        "snippet": line.strip()[:300],
                    })
            i += 2
    else:
        # Plain text without page markers
        lines = text.split("\n")
        for line in lines:
            if query_lower in line.lower() and line.strip():
                results.append({
                    "page": None,
                    "snippet": line.strip()[:300],
                })

    return results[:20]  # Limit results
