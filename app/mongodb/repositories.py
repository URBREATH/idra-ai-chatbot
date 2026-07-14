from .client import get_database
from typing import List, Dict, Any
from datetime import datetime

db = get_database()

async def get_datasets(filter_query: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    collection = db["entities"]
    cursor = collection.find(filter_query or {})
    return await cursor.to_list(length=100)

async def get_datasets_since(tenant_id: str, last_ingestion: datetime) -> List[Dict[str, Any]]:
    collection = db["entities"]
    # modDate in Orion è un epoch float: converti il datetime in timestamp
    since_epoch = last_ingestion.timestamp() if last_ingestion != datetime.min else 0
    filter_query = {
        "_id.servicePath": "/",
        "modDate": {"$gte": since_epoch},
    }
    cursor = collection.find(filter_query)
    return await cursor.to_list(length=100)

async def get_datasets_by_ids(dataset_ids: List[str]) -> List[Dict[str, Any]]:
    collection = db["entities"]
    cursor = collection.find({"_id.id": {"$in": dataset_ids}})
    return await cursor.to_list(length=100)

async def get_deleted_dataset_ids(tenant_id: str, last_ingestion: datetime) -> List[str]:
    collection = db["deleted_datasets"]
    since_epoch = last_ingestion.timestamp() if last_ingestion != datetime.min else 0
    filter_query = {
        # sostituisci con i nomi di campo REALI visti nel findOne:
        "servicePath": "/",
        "deletedAt": {"$gte": since_epoch},
    }
    cursor = collection.find(filter_query)
    records = await cursor.to_list(length=100)
    return [r.get("dataset_id") for r in records]

async def get_all_dataset_ids(tenant_id: str) -> List[str]:
    collection = db["entities"]
    cursor = collection.find({"_id.servicePath": "/"}, projection={"_id": 1})
    records = await cursor.to_list(length=100)
    return [r["_id"]["id"] for r in records if r.get("_id", {}).get("id") is not None]
