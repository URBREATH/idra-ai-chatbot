from typing import Any, Dict, List


def _is_geometry(value: Any) -> bool:
    return isinstance(value, dict) and "type" in value and "coordinates" in value


def _collect_terms(value: Any, terms: List[str], seen: set) -> None:
    """Recursively walk the dataset structure collecting all string/number values."""
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
    """Recursive scan of dataset structure extracting dimension names, SDMX codes,
    labels, and nested descriptions (ARCHITECTURE.md - Technical Crawler).

    Output: a deduplicated, space-joined string of technical terms.
    """
    terms: List[str] = []
    seen: set = set()
    _collect_terms(dataset, terms, seen)
    return " ".join(terms)
