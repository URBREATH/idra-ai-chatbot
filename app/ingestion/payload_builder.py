from typing import Dict, Any
from .semantic_enricher import enrich
from .technical_crawler import crawl

MAX_TOKENS = 400
CHARS_PER_TOKEN = 3
MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN

SEP = "[SEP]"


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


async def build_payload(dataset: Dict[str, Any]) -> str:
    """
    Build the final payload structure:
    [SEMANTIC BLOCK][SEP][TECHNICAL BLOCK][SEP][DESCRIPTION BLOCK]
    
    Maximum 512 tokens (~2048 chars)
    """
    dataset_id = dataset.get("_id", {}).get("id", "")
    title = dataset.get("title", "")
    description = dataset.get("description", "")
    
    # Get semantic enrichment
    semantic_text = title or description
    semantic_terms = await enrich(semantic_text)
    semantic_content = " ".join(semantic_terms) if semantic_terms else (title or "N/A")
    
    # Get technical crawl
    technical_content = await crawl(dataset)
    if not technical_content:
        technical_content = "N/A"
    
    # Build description block
    desc_parts = []
    if title:
        desc_parts.append(f"Title: {title}")
    if description:
        desc_parts.append(f"Description: {description}")
    if dataset_id:
        desc_parts.append(f"DatasetID: {dataset_id}")
    
    publisher = dataset.get("publisher")
    if publisher:
        desc_parts.append(f"Publisher: {publisher}")
    
    description_content = " | ".join(desc_parts) if desc_parts else "N/A"
    
    # Assemble with block markers and separators
    payload = f"[SEMANTIC BLOCK] {semantic_content} {SEP} [TECHNICAL BLOCK] {technical_content} {SEP} [DESCRIPTION BLOCK] {description_content}"
    
    # Truncate if exceeds token limit
    return _truncate(payload, MAX_CHARS)