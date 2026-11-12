import json
import logging
import os
from typing import List

from dotenv import load_dotenv

from ..ollama.client import generate_completion
from ..observability import tracing
load_dotenv()

logger = logging.getLogger(__name__)

MODEL = os.getenv("OLLAMA_ENRICHMENT_MODEL", "mistral:7b")
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.1))
MAX_TERMS = int(os.getenv("MAX_TERMS", 20))


def _build_prompt(text: str) -> str:
    return f"""Analyze the following text and extract a list of concepts, synonyms and related terms in English.
Return ONLY a JSON array of strings, with no additional text.

Text: {text}

JSON Array:"""


def _extract_json_array(response: str) -> str:
    raw = response.strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


async def enrich(text: str) -> List[str]:
    if not text or not text.strip():
        return []
    with tracing.observe_step("ingestion.semantic_enrichment", as_type="span",
                              metadata={"model": MODEL, "max_terms": MAX_TERMS}) as obs:
        result = await _enrich(text)
        tracing.safe_update(obs, output=result, metadata={
            "terms": len(result), "status": tracing.get_facts().get("enrichment_status")})
        return result


async def _enrich(text: str) -> List[str]:
    prompt = _build_prompt(text.strip())
    try:
        response = await generate_completion(prompt, model=MODEL, temperature=TEMPERATURE)
    except Exception:
        logger.debug(f"[enrich] chiamata a {MODEL} FALLITA: 0 termini", exc_info=True)
        tracing.fact(enrichment_status="llm_error", enrichment_terms=0)
        return []
    try:
        terms = json.loads(_extract_json_array(response))
        if not isinstance(terms, list):
            logger.debug("[enrich] risposta non e' una lista JSON: 0 termini")
            tracing.fact(enrichment_status="not_a_list", enrichment_terms=0)
            return []
    except json.JSONDecodeError:
        logger.debug(f"[enrich] JSON non parsabile ({len(response)} char): 0 termini")
        tracing.fact(enrichment_status="invalid_json", enrichment_terms=0)
        return []
    unique_terms, seen = [], set()
    for term in terms:
        if isinstance(term, str):
            n = term.strip().lower()
            if n and n not in seen:
                seen.add(n)
                unique_terms.append(term.strip())
    result = unique_terms[:MAX_TERMS]
    logger.debug(f"[enrich] {len(result)} termini estratti")
    tracing.fact(enrichment_status="ok" if result else "empty", enrichment_terms=len(result))
    return result

