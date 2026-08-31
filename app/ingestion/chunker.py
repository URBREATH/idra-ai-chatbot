import logging
import os
import re
from typing import List, Dict, Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MAX_TOKENS = int(os.getenv("MAX_TOKENS_CHUNKER", 300))
CHARS_PER_TOKEN = int(os.getenv("CHARS_PER_TOKEN_CHUNKER", 2))
MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN  # = 600 con i default

SEP = "[SEP]"

DIMENSION_PATTERN = re.compile(r'\b([A-Z_]{2,}(?:\d+)?)\b')


# FIX — stima coerente con MAX_CHARS (prima era // 4)
def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def _hard_truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    logger.debug(f"[chunk] hard truncate: {len(text)} char -> {MAX_CHARS} (possibile perdita di contenuto)")
    return text[:MAX_CHARS].rsplit(" ", 1)[0]


def _split_technical_block(technical: str) -> List[str]:
    tokens = technical.split()
    if not tokens:
        return []
    dimensions = []
    current_dim = None
    current_codes = []
    for token in tokens:
        if DIMENSION_PATTERN.fullmatch(token) and token not in ("AND", "OR", "THE", "FOR", "WITH"):
            if current_dim is not None:
                dimensions.append(f"{current_dim} {' '.join(current_codes)}")
            current_dim = token
            current_codes = []
        else:
            current_codes.append(token)
    if current_dim is not None:
        dimensions.append(f"{current_dim} {' '.join(current_codes)}")
    return dimensions


def _build_chunk(semantic, technical_part, description, dataset_id, chunk_num):
    text = f"[SEMANTIC BLOCK] {semantic} {SEP} [TECHNICAL BLOCK] {technical_part} {SEP} [DESCRIPTION BLOCK] {description}"
    return {
        "dataset_id": dataset_id,
        "chunk_id": f"{dataset_id}_chunk_{chunk_num}",
        "text": _hard_truncate(text)
    }


async def chunk_payload(payload: str, dataset_id: str) -> List[Dict[str, Any]]:
    if not payload or not payload.strip():
        logger.debug(f"[chunk] {dataset_id}: payload vuoto -> 0 chunk")
        return []

    parts = payload.split(SEP)
    if len(parts) != 3:
        logger.debug(f"[chunk] {dataset_id}: attesi 3 blocchi ma trovati {len(parts)} "
                     f"(struttura [SEP] rotta) -> fallback a chunk unico")
        return [_build_chunk("", payload, "", dataset_id, 1)]

    semantic_block = parts[0].replace("[SEMANTIC BLOCK]", "").strip()
    technical_block = parts[1].replace("[TECHNICAL BLOCK]", "").strip()
    description_block = parts[2].replace("[DESCRIPTION BLOCK]", "").strip()

    if _estimate_tokens(payload) <= MAX_TOKENS:
        logger.debug(f"[chunk] {dataset_id}: entra in 1 chunk ({len(payload)} char)")
        return [_build_chunk(semantic_block, technical_block, description_block, dataset_id, 1)]

    dimension_groups = _split_technical_block(technical_block)
    if not dimension_groups:
        logger.debug(f"[chunk] {dataset_id}: nessuna dimensione SDMX -> 1 chunk (con troncamento)")
        return [_build_chunk(semantic_block, technical_block, description_block, dataset_id, 1)]

    chunks = []
    current_technical = []
    for dim_group in dimension_groups:
        test_chunk = f"[SEMANTIC BLOCK] {semantic_block} {SEP} [TECHNICAL BLOCK] {' '.join(current_technical + [dim_group])} {SEP} [DESCRIPTION BLOCK] {description_block}"
        if _estimate_tokens(test_chunk) > MAX_TOKENS and current_technical:
            chunks.append(_build_chunk(semantic_block, " ".join(current_technical), description_block, dataset_id,
                                       len(chunks) + 1))
            current_technical = [dim_group]
        else:
            current_technical.append(dim_group)
    if current_technical:
        chunks.append(
            _build_chunk(semantic_block, " ".join(current_technical), description_block, dataset_id, len(chunks) + 1))

    logger.debug(f"[chunk] {dataset_id}: payload lungo -> spezzato in {len(chunks)} chunk")
    return chunks