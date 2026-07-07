from typing import Any, Set


async def crawl(dataset: dict) -> str:
    """
    Recursively crawl dataset structure to extract technical terms:
    - SDMX dimension names
    - SDMX codes
    - Labels
    - Nested descriptions
    
    Returns space-separated string of unique terms.
    """
    terms: Set[str] = set()
    
    def add_term(value: Any) -> None:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                terms.add(cleaned)
        elif isinstance(value, (int, float)):
            terms.add(str(value))
    
    def is_technical_key(key: str) -> bool:
        return key in (
            "id", "name", "label", "title", "code", "dimension", "attribute",
            "format", "mediaType", "downloadURL", "type", "description"
        )
    
    def is_container_key(key: str) -> bool:
        return key in (
            "dimensions", "attributes", "measures", "categories", "dimension",
            "datasets", "distributions", "codes", "structure", "attrs",
            "catalog", "value", "properties", "items"
        )
    
    def extract(obj: Any, path: str = "") -> None:
        if obj is None:
            return
            
        # Handle primitive values directly
        if isinstance(obj, (str, int, float)):
            add_term(obj)
            return
            
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key
                
                # Handle technical keys - if value is a dict with "value" key, extract that
                if is_technical_key(key):
                    if isinstance(value, dict) and "value" in value:
                        add_term(value["value"])
                    else:
                        add_term(value)
                
                # Recursively process containers
                if is_container_key(key):
                    extract(value, current_path)
                elif isinstance(value, dict):
                    extract(value, current_path)
                elif isinstance(value, list):
                    for item in value:
                        extract(item, current_path)
        
        elif isinstance(obj, list):
            for item in obj:
                extract(item, path)
    
    extract(dataset)
    
    return " ".join(sorted(terms))