import os
import logging
from typing import List, Dict, Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Allineato al budget del payload_builder e al limite del modello di embedding.
MAX_TOKENS = int(os.getenv("MAX_TOKENS_CHUNKER", 512))
CHARS_PER_TOKEN = int(os.getenv("CHARS_PER_TOKEN_CHUNKER", 3))
MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN


def _hard_truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    logger.debug(f"[chunk] troncamento: {len(text)} -> {MAX_CHARS} char")
    return text[:MAX_CHARS].rsplit(" ", 1)[0]


async def chunk_payload(payload: str, dataset_id: str) -> List[Dict[str, Any]]:
    """
    UN dataset -> UN chunk. Il testo arriva gia' pulito da build_payload.
    Nessun marcatore da ricostruire, nessun annidamento, nessuno split SDMX.
    """
    if not payload or not payload.strip():
        logger.debug(f"[chunk] {dataset_id}: payload vuoto -> 0 chunk")
        return []

    text = _hard_truncate(payload.strip())
    logger.debug(f"[chunk] {dataset_id}: 1 chunk, {len(text)} char")
    return [{
        "dataset_id": dataset_id,
        "chunk_id": f"{dataset_id}_chunk_1",
        "text": text,
    }]