import os
import logging
import re
from typing import List, Dict, Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = int(os.getenv("MAX_CHUNK_CHARS", 1200))  # target size of a chunk
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 150))  # overlap between hard-split pieces


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    text = (text or "").replace("\\n", "\n").strip()  # handle literal \n too
    if not text:
        return []
    if len(text) <= size:
        return [text]

    # split on blank lines (paragraphs / sections) and pack them into chunks
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for p in paragraphs:
        if len(p) > size:
            # a single paragraph is too long: flush, then hard-split it with overlap
            if current:
                chunks.append(current)
                current = ""
            start = 0
            step = max(size - overlap, 1)
            while start < len(p):
                chunks.append(p[start:start + size].strip())
                start += step
        elif len(current) + len(p) + 1 <= size:
            current = (current + "\n" + p).strip()
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)
    return chunks


async def chunk_payload(payload: str, dataset_id: str, title: str = "") -> list[dict]:
    pieces = _split_text(payload, MAX_CHUNK_CHARS, CHUNK_OVERLAP)
    if not pieces:
        pieces = [(title or "").strip() or "N/A"]

    prefix = (title or "").strip()
    chunks = []
    for i, piece in enumerate(pieces, 1):
        body = piece
        if prefix and prefix.lower() not in piece.lower():
            body = prefix + "\n" + piece  # keep the title in every chunk
        chunks.append({"chunk_id": f"{dataset_id}_chunk_{i}", "text": body})
    return chunks
