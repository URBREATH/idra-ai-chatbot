import uuid
from typing import List, Dict, Any

from ..mongodb.repositories import get_datasets
from ..ollama.client import generate_embedding
from ..chroma.client import get_tenant_collection

async def ingest_tenant(tenant_id: str) -> None:
    # 1️⃣ Retrieve datasets for tenant (placeholder: all datasets)
    datasets: List[Dict[str, Any]] = await get_datasets()
    collection = get_tenant_collection(tenant_id)

    ids: List[str] = []
    embeddings: List[List[float]] = []
    metadatas: List[Dict[str, Any]] = []

    for ds in datasets:
        # Simple payload: use dataset title or description for embedding
        text = ds.get("title") or ds.get("description") or ""
        if not text:
            continue
        embed = await generate_embedding(text)
        doc_id = ds.get("_id", {}).get("id") or str(uuid.uuid4())
        ids.append(doc_id)
        embeddings.append(embed)
        metadatas.append({
            "tenant_id": tenant_id,
            "dataset_id": doc_id,
            "title": ds.get("title"),
            "publisher": ds.get("publisher"),
        })

    # Upsert vectors into Chroma collection
    await collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas)
