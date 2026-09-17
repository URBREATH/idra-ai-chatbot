import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _is_geometry(value: Any) -> bool:
    return isinstance(value, dict) and "type" in value and "coordinates" in value


def _collect_terms(value: Any, terms: List[str], seen: set) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, dict):
        if _is_geometry(value):
            return
        for v in value.values():
            _collect_terms(v, terms, seen)
    elif isinstance(value, list):
        for item in value:
            _collect_terms(item, terms, seen)
    elif isinstance(value, (str, int, float)):
        s = str(value).strip()
        if s and s not in seen:
            seen.add(s)
            terms.append(s)


async def crawl(dataset: Dict[str, Any]) -> str:
    terms: List[str] = []
    seen: set = set()
    _collect_terms(dataset, terms, seen)
    result = " ".join(terms)
    dataset_id = dataset.get("_id", {}).get("id", "?")
    logger.debug(f"[crawl] {dataset_id}: {len(terms)} termini, {len(result)} char")
    return result
