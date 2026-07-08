import json
import os
from typing import List

from ..ollama.client import generate_completion

MODEL = os.getenv("OLLAMA_LLM_MODEL", "qwen2.5:7b")
TEMPERATURE = 0.1
MAX_TERMS = 20


def _build_prompt(text: str) -> str:
    return f"""Analizza il seguente testo ed estrai una lista di concetti, sinonimi e termini correlati in italiano.
Restituisci SOLO un array JSON di stringhe, senza testo aggiuntivo.

Testo: {text}

Array JSON:"""


async def enrich(text: str) -> List[str]:
    if not text or not text.strip():
        return []

    prompt = _build_prompt(text.strip())

    try:
        response = await generate_completion(prompt, model=MODEL, temperature=TEMPERATURE)
    except Exception:
        return []

    try:
        terms = json.loads(response.strip())
        if not isinstance(terms, list):
            return []
    except json.JSONDecodeError:
        return []

    unique_terms = []
    seen = set()
    for term in terms:
        if isinstance(term, str):
            normalized = term.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_terms.append(term.strip())

    return unique_terms[:MAX_TERMS]