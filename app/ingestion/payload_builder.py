import os
import logging
from typing import Dict, Any

from dotenv import load_dotenv

from .semantic_enricher import enrich
from .technical_crawler import crawl   # crawl SEMPRE attivo

load_dotenv()

logger = logging.getLogger(__name__)

MAX_TOKENS = int(os.getenv("MAX_TOKENS_PAYLOAD_BUILDER", 400))
CHARS_PER_TOKEN = int(os.getenv("CHARS_PER_TOKEN_PAYLOAD_BUILDER", 3))
MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN

SEP = "[SEP]"

FIELD_LABELS = {
    "title": "Title",
    "description": "Description",
    "keyword": "Keywords",        # <-- NUOVO (Dataset): lista di parole chiave
    "theme": "Theme",             # <-- NUOVO (Dataset): es. 'ENVI'
    "publisher": "Publisher",     # <-- NUOVO (Dataset)
    "landingPage": "LandingPage", # <-- NUOVO (Dataset): pagina del dataset
    "format": "Format",
    "license": "License",
    "downloadURL": "URL",
    "accessUrl": "AccessURL",
    "modifiedDate": "Updated",
    "releaseDate": "Published",
    "rights": "Rights",
}

JUNK = {"", '\\"\\"', '""', "N/A"}

# Title/Description nel blocco semantico, non ripetuti nel tecnico.
TECH_EXCLUDE = {"Title", "Description"}

ENABLE_ENRICHMENT = os.getenv("ENABLE_ENRICHMENT", "true").strip().lower() in ("1", "true", "yes", "on")


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def _clean_value(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("@value", "")).strip()
    if isinstance(raw, list):
        # NUOVO: keyword/theme in NGSI-LD sono spesso LISTE -> uniscile con virgola
        return ", ".join(_clean_value(x) for x in raw if x not in (None, "")).strip()
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
    dataset_id = dataset.get("_id", {}).get("id", "")
    attrs = extract_attrs(dataset)
    logger.debug(f"[payload] {dataset_id}: attributi -> {list(attrs.keys())}")

    title = attrs.get("Title") or str(dataset.get("title", "")).strip()
    description = attrs.get("Description") or str(dataset.get("description", "")).strip()
    theme = attrs.get("Theme", "")
    keywords = attrs.get("Keywords", "")

    # SEMANTIC BLOCK: titolo + descrizione + tema + keyword (+ arricchimento)
    semantic_text = " ".join(p for p in [title, description, theme, keywords] if p).strip()
    if ENABLE_ENRICHMENT and semantic_text:
        semantic_terms = await enrich(semantic_text)
        if semantic_terms:
            semantic_content = f"{semantic_text} {' '.join(semantic_terms)}".strip()
        else:
            semantic_content = semantic_text
    else:
        semantic_content = semantic_text or "N/A"
        if not semantic_text:
            logger.debug(f"[payload] {dataset_id}: blocco semantico VUOTO -> 'N/A'")

    # TECHNICAL BLOCK: scalari (senza Title/Description) + crawl()
    tech_parts = [f"{k}: {v}" for k, v in attrs.items() if k not in TECH_EXCLUDE]
    crawled = await crawl(dataset)
    if crawled:
        tech_parts.append(crawled)
    technical_content = " | ".join(tech_parts) if tech_parts else "N/A"

    # DESCRIPTION BLOCK: solo DatasetID
    desc_parts = []
    if dataset_id:
        desc_parts.append(f"DatasetID: {dataset_id}")
    description_content = " | ".join(desc_parts) if desc_parts else "N/A"

    payload = (f"[SEMANTIC BLOCK] {semantic_content} {SEP} "
               f"[TECHNICAL BLOCK] {technical_content} {SEP} "
               f"[DESCRIPTION BLOCK] {description_content}")

    logger.debug(f"[payload] {dataset_id}: {len(payload)} char (semantic={len(semantic_content)})")
    if len(payload) > MAX_CHARS:
        logger.debug(f"[payload] {dataset_id}: payload {len(payload)} > MAX_CHARS {MAX_CHARS}: verra' troncato")

    return _truncate(payload, MAX_CHARS)