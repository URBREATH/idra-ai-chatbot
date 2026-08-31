import json
import logging
import os
from typing import List

from dotenv import load_dotenv

from ..ollama.client import generate_completion
load_dotenv()

logger = logging.getLogger(__name__)

MODEL = os.getenv("OLLAMA_LLM_MODEL", "qwen2.5:7b")
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
        logger.debug("[enrich] testo vuoto: 0 termini")
        return []

    prompt = _build_prompt(text.strip())

    try:
        response = await generate_completion(prompt, model=MODEL, temperature=TEMPERATURE)
    except Exception:
        logger.debug(f"[enrich] chiamata a {MODEL} FALLITA: ritorno 0 termini", exc_info=True)
        return []

    try:
        terms = json.loads(_extract_json_array(response))
        if not isinstance(terms, list):
            logger.debug("[enrich] risposta non e' una lista JSON: ritorno 0 termini")
            return []
    except json.JSONDecodeError:
        logger.debug(f"[enrich] JSON non parsabile (risposta di {len(response)} char): ritorno 0 termini")
        return []

    unique_terms = []
    seen = set()
    for term in terms:
        if isinstance(term, str):
            normalized = term.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_terms.append(term.strip())

    result = unique_terms[:MAX_TERMS]
    logger.debug(f"[enrich] {len(result)} termini estratti (grezzi: {len(terms)})")
    return result
