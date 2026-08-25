import os
import re
from typing import List, Dict, Any

from dotenv import load_dotenv

load_dotenv()

MAX_TOKENS = int(os.getenv("MAX_TOKENS_CHUNKER", 300))
CHARS_PER_TOKEN = int(os.getenv("CHARS_PER_TOKEN_CHUNKER", 2))
MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN

SEP = "[SEP]"

DIMENSION_PATTERN = re.compile(r'\b([A-Z_]{2,}(?:\d+)?)\b')


def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN

def _hard_truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS].rsplit(" ", 1)[0]

def _split_technical_block(technical: str) -> List[str]:
    """
    Split technical block by SDMX dimension names.
    Returns list of dimension groups (e.g., ["FREQ A M Q", "GEO IT FR DE", ...])
    """
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
    """
    Split payload into chunks by SDMX dimension when exceeding 512 tokens.
    Each chunk keeps the same datasetId.
    """
    if not payload or not payload.strip():
        return []
    
    # Parse the three blocks
    parts = payload.split(SEP)
    if len(parts) != 3:
        return [_build_chunk("", payload, "", dataset_id, 1)]
    
    semantic_block = parts[0].replace("[SEMANTIC BLOCK]", "").strip()
    technical_block = parts[1].replace("[TECHNICAL BLOCK]", "").strip()
    description_block = parts[2].replace("[DESCRIPTION BLOCK]", "").strip()
    
    # Check if fits in single chunk
    if _estimate_tokens(payload) <= MAX_TOKENS:
        return [_build_chunk(semantic_block, technical_block, description_block, dataset_id, 1)]
    
    # Split technical block by dimensions
    dimension_groups = _split_technical_block(technical_block)
    
    if not dimension_groups:
        return [_build_chunk(semantic_block, technical_block, description_block, dataset_id, 1)]
    
    chunks = []
    current_technical = []
    current_tokens = _estimate_tokens(f"[SEMANTIC BLOCK] {semantic_block} {SEP} [TECHNICAL BLOCK] {' '.join(dimension_groups)} {SEP} [DESCRIPTION BLOCK] {description_block}")
    
    # If even one dimension group is too large, we need to split further
    for dim_group in dimension_groups:
        test_chunk = f"[SEMANTIC BLOCK] {semantic_block} {SEP} [TECHNICAL BLOCK] {' '.join(current_technical + [dim_group])} {SEP} [DESCRIPTION BLOCK] {description_block}"
        
        if _estimate_tokens(test_chunk) > MAX_TOKENS and current_technical:
            chunks.append(_build_chunk(semantic_block, " ".join(current_technical), description_block, dataset_id, len(chunks) + 1))
            current_technical = [dim_group]
        else:
            current_technical.append(dim_group)
    
    if current_technical:
        chunks.append(_build_chunk(semantic_block, " ".join(current_technical), description_block, dataset_id, len(chunks) + 1))
    
    return chunks