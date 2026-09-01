import os
import logging
from typing import Dict, Any

from dotenv import load_dotenv

from .semantic_enricher import enrich
from .technical_crawler import crawl

load_dotenv()

logger = logging.getLogger(__name__)

MAX_TOKENS = int(os.getenv("MAX_TOKENS_PAYLOAD_BUILDER", 512))
CHARS_PER_TOKEN = int(os.getenv("CHARS_PER_TOKEN_PAYLOAD_BUILDER", 3))
MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN

FIELD_LABELS = {
    "title": "Title",
    "description": "Description",
    "keyword": "Keywords",
    "theme": "Theme",
    "publisher": "Publisher",
    "landingPage": "LandingPage",
    "format": "Format",
    "license": "License",
    "downloadURL": "URL",
    "accessUrl": "AccessURL",
    "modifiedDate": "Updated",
    "releaseDate": "Published",
    "rights": "Rights",
    "name": "Name",              # utile per POI ed entita' senza title
    "address": "Address",
}

JUNK = {"", '\\"\\"', '""', "N/A"}

ENABLE_ENRICHMENT = os.getenv("ENABLE_ENRICHMENT", "true").strip().lower() in ("1", "true", "yes", "on")

# Se true, include blocco tecnico + crawl nel vettore anche per le entita' CON
# semantica (sconsigliato per la qualita'). Il fallback per le entita' SENZA
# semantica usa comunque gli attributi, a prescindere da questo flag.
INCLUDE_TECHNICAL = os.getenv("INCLUDE_TECHNICAL_IN_EMBEDDING", "false").strip().lower() in ("1", "true", "yes", "on")


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def _clean_value(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("@value", "")).strip()
    if isinstance(raw, list):
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


def _attrs_to_text(attrs: Dict[str, str]) -> str:
    return " | ".join(f"{k}: {v}" for k, v in attrs.items())


async def build_payload(dataset: Dict[str, Any]) -> str:
    """
    Testo da vettorizzare.
    - Entita' CON semantica (es. Dataset): solo testo semantico (miglior retrieval).
    - Entita' SENZA semantica (POI, TrafficFlowObserved, Distribution spoglie):
      fallback sugli attributi, cosi' il chunk NON e' vuoto ed e' cercabile.
    """
    dataset_id = dataset.get("_id", {}).get("id", "")
    attrs = extract_attrs(dataset)

    title = attrs.get("Title") or str(dataset.get("title", "")).strip()
    description = attrs.get("Description") or str(dataset.get("description", "")).strip()
    theme = attrs.get("Theme", "")
    keywords = attrs.get("Keywords", "")

    semantic_text = " ".join(p for p in [title, description, theme, keywords] if p).strip()
    if ENABLE_ENRICHMENT and semantic_text:
        terms = await enrich(semantic_text)
        if terms:
            semantic_text = f"{semantic_text} {' '.join(terms)}".strip()

    if semantic_text:
        # --- percorso normale: solo semantico (+ tecnico se richiesto dal flag) ---
        document = semantic_text
        if INCLUDE_TECHNICAL:
            tech_parts = [f"{k}: {v}" for k, v in attrs.items() if k not in ("Title", "Description")]
            crawled = await crawl(dataset)
            if crawled:
                tech_parts.append(crawled)
            technical = " | ".join(tech_parts)
            room = MAX_CHARS - len(document) - 1
            if room > 0 and technical:
                document = f"{document} {_truncate(technical, room)}".strip()
    else:
        # --- FALLBACK: entita' senza titolo/descrizione -> usa gli attributi ---
        tech_parts = [f"{k}: {v}" for k, v in attrs.items()]
        crawled = await crawl(dataset)
        if crawled:
            tech_parts.append(crawled)
        document = " | ".join(tech_parts).strip() or "N/A"
        logger.debug(f"[payload] {dataset_id}: nessuna semantica -> fallback sugli attributi")

    document = _truncate(document, MAX_CHARS)
    logger.debug(f"[payload] {dataset_id}: document {len(document)} char")
    return document