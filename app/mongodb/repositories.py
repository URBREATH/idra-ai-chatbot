from .client import get_database
from typing import List, Dict, Any
from datetime import datetime

db = get_database()

async def get_datasets(filter_query: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    collection = db["entities"]
    cursor = collection.find(filter_query or {})
    return await cursor.to_list(length=1000)

async def get_datasets_since(tenant_id: str, last_ingestion: datetime) -> List[Dict[str, Any]]:
    collection = db["entities"]
    filter_query = {
        "tenant_id": tenant_id,
        "updatedAt": {"$gte": last_ingestion}
    }
    cursor = collection.find(filter_query)
    return await cursor.to_list(length=1000)

async def get_datasets_by_ids(dataset_ids: List[str]) -> List[Dict[str, Any]]:
    collection = db["entities"]
    cursor = collection.find({"_id.id": {"$in": dataset_ids}})
    return await cursor.to_list(length=1000)

async def get_deleted_dataset_ids(tenant_id: str, last_ingestion: datetime) -> List[str]:
    collection = db["deleted_datasets"]
    filter_query = {
        "tenant_id": tenant_id,
        "deletedAt": {"$gte": last_ingestion}
    }
    cursor = collection.find(filter_query)
    records = await cursor.to_list(length=1000)
    return [r.get("dataset_id") for r in records]

async def get_all_dataset_ids(tenant_id: str) -> List[str]:
    collection = db["entities"]
    cursor = collection.find({"tenant_id": tenant_id}, projection={"_id": 1})
    records = await cursor.to_list(length=1000)
    return [r["_id"]["id"] for r in records if r.get("_id", {}).get("id") is not None]
