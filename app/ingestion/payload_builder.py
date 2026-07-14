from typing import Dict, Any
from .semantic_enricher import enrich
from .technical_crawler import crawl

MAX_TOKENS = 400
CHARS_PER_TOKEN = 3
MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN

SEP = "[SEP]"

FIELD_LABELS = {
    "title": "Title",
    "description": "Description",
    "format": "Format",
    "license": "License",
    "downloadURL": "URL",
    "accessUrl": "AccessURL",
    "modifiedDate": "Updated",
    "releaseDate": "Published",
    "rights": "Rights",
}

JUNK = {"", '\\"\\"', '""', "N/A"}

# se True, arricchisce il blocco semantico con l'LLM (lento in ingestione)
ENABLE_ENRICHMENT = False #da mettere nelle variabili d'ambiente


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def _clean_value(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("@value", "")).strip()
    return str(raw).strip()


def extract_attrs(entity: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw_key, attr in entity.get("attrs", {}).items():
        field = raw_key.rstrip("/").split("/")[-1]
        value = _clean_value(attr.get("value"))
        if value and value not in JUNK:
            out[FIELD_LABELS.get(field, field)] = value
    return out


async def build_payload(dataset: Dict[str, Any]) -> str:
    """
    Build the payload:
    [SEMANTIC BLOCK][SEP][TECHNICAL BLOCK][SEP][DESCRIPTION BLOCK]
    All content in English, extracted from the real Orion 'attrs' values.
    """
    dataset_id = dataset.get("_id", {}).get("id", "")
    attrs = extract_attrs(dataset)

    title = attrs.get("Title", "")
    description = attrs.get("Description", "")

    # SEMANTIC BLOCK: title + description (optional LLM enrichment)
    semantic_text = f"{title} {description}".strip()
    if ENABLE_ENRICHMENT and semantic_text:
        semantic_terms = await enrich(semantic_text)
        semantic_content = " ".join(semantic_terms) if semantic_terms else (title or "N/A")
    else:
        semantic_content = semantic_text or "N/A"

    # TECHNICAL BLOCK: real attribute values, NOT schema URIs
    tech_parts = [f"{k}: {v}" for k, v in attrs.items()]
    technical_content = " | ".join(tech_parts) if tech_parts else "N/A"

    # DESCRIPTION BLOCK
    desc_parts = []
    if title:
        desc_parts.append(f"Title: {title}")
    if description:
        desc_parts.append(f"Description: {description}")
    if dataset_id:
        desc_parts.append(f"DatasetID: {dataset_id}")
    description_content = " | ".join(desc_parts) if desc_parts else "N/A"

    payload = (f"[SEMANTIC BLOCK] {semantic_content} {SEP} "
               f"[TECHNICAL BLOCK] {technical_content} {SEP} "
               f"[DESCRIPTION BLOCK] {description_content}")

    return _truncate(payload, MAX_CHARS)