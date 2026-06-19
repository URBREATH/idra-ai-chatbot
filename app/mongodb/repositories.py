from .client import get_database
from typing import List, Dict, Any

db = get_database()

async def get_datasets(filter_query: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    collection = db["datasets"]
    cursor = collection.find(filter_query or {})
    return await cursor.to_list(length=1000)

# Additional repository functions (incremental, deleted) would be added similarly.
