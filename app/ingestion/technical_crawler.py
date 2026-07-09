from typing import Any, Set, Dict


def _clean_key(uri_key: str) -> str:
    # Tiene solo l'ultimo segmento della chiave URI: prende dopo l'ultimo '/'
    # (le chiavi Orion usano '=' al posto di '.', ma a noi serve solo il nome finale)
    return uri_key.rstrip("/").split("/")[-1]

def _is_geometry(value: Any) -> bool:
    # Un valore è una geometria GeoJSON se è un dict con 'type' e 'coordinates'
    return isinstance(value, dict) and "type" in value and "coordinates" in value

def _format_value(value: Any) -> str:
    if isinstance(value, dict):
        # Valori strutturati semplici (es. address): concateno i sotto-valori scalari
        parts = [str(v) for v in value.values() if isinstance(v, (str, int, float))]
        return ", ".join(parts)
    if isinstance(value, (str, int, float)):
        return str(value)
    return ""

async def crawl(dataset: Dict[str, Any]) -> str:
    entity_type = _clean_key(dataset.get("_id", {}).get("type", ""))
    parts = []
    if entity_type:
        parts.append(entity_type)

    attrs = dataset.get("attrs", {})
    for raw_key, attr in attrs.items():
        if not isinstance(attr, dict):
            continue
        value = attr.get("value")
        if _is_geometry(value):        # salta le geometrie: coordinate inutili e ingombranti
            continue
        text_value = _format_value(value)
        if text_value:
            parts.append(f"{_clean_key(raw_key)}: {text_value}")

    return " | ".join(parts)