import uuid
import asyncio
import logging
import threading
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field

from ..mongodb.repositories import (
    get_datasets_since,
    get_deleted_dataset_ids,
    get_all_dataset_ids
)
from ..ollama.client import generate_embedding
from ..chroma.client import get_tenant_collection, delete_documents_from_collection

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

@dataclass
class IngestionStatus:
    running: bool = False
    processed: int = 0
    remaining: int = 0
    last_ingestion: Optional[datetime] = None
    start_time: Optional[datetime] = None

_status: IngestionStatus = IngestionStatus()

def get_ingestion_status() -> IngestionStatus:
    return _status

async def _process_dataset(ds: Dict[str, Any], tenant_id: str) -> List[Dict[str, Any]]:
    from .payload_builder import build_payload
    from .chunker import chunk_payload
    
    dataset_id = ds.get("_id", {}).get("id")
    if not dataset_id:
        dataset_id = str(uuid.uuid4())
    
    payload = await build_payload(ds)
    chunks = await chunk_payload(payload, dataset_id)
    
    results = []
    for chunk in chunks:
        embed = await generate_embedding(chunk["text"])

        candidate_metadata = {
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "chunk_id": chunk["chunk_id"],
            "title": ds.get("title"),
            "publisher": ds.get("publisher"),
        }
        metadata = {k: v for k, v in candidate_metadata.items() if v is not None}

        results.append({
            "id": chunk["chunk_id"],
            "embedding": embed,
            "metadata": metadata,
            "document": chunk["text"]
        })

    return results

async def _delete_from_collection(collection, dataset_ids: List[str]) -> None:
    delete_documents_from_collection(collection, dataset_ids)

async def _run_incremental(tenant_id: str, full_reindex: bool = False) -> Dict[str, int]:
    collection = get_tenant_collection(tenant_id)

    if full_reindex:
        dataset_ids = await get_all_dataset_ids(tenant_id)
        logger.info(f"[full_reindex] cancellazione di {len(dataset_ids)} dataset dalla collection")
        await _delete_from_collection(collection, dataset_ids)

    last_ingestion = _status.last_ingestion or datetime.min
    new_datasets = await get_datasets_since(tenant_id, last_ingestion)
    deleted_ids = await get_deleted_dataset_ids(tenant_id, last_ingestion)

    if deleted_ids:
        await _delete_from_collection(collection, deleted_ids)
        logger.info(f"Deleted {len(deleted_ids)} datasets from ChromaDB for tenant {tenant_id}")

    # LOG 1 — il più importante: quanti dataset ho preso da MongoDB?
    logger.info(f"Trovati {len(new_datasets)} dataset da processare "
                f"(tenant={tenant_id}, since={last_ingestion})")

    all_chunks = []
    for i, ds in enumerate(new_datasets, 1):
        try:
            chunks = await _process_dataset(ds, tenant_id)
            all_chunks.extend(chunks)
            # LOG 2 — progresso per dataset + verifica che i chunk abbiano il testo
            has_text = all(bool(c.get("document")) for c in chunks)
            logger.info(f"[{i}/{len(new_datasets)}] {ds.get('_id', {}).get('id')}: "
                        f"+{len(chunks)} chunk, testo_presente={has_text}")
        except Exception:
            # LOG 3 — errore sul singolo dataset, con stack trace, senza fermare il resto
            logger.exception(f"[{i}/{len(new_datasets)}] errore processando il dataset")

    if all_chunks:
        ids = [c["id"] for c in all_chunks]
        embeddings = [c["embedding"] for c in all_chunks]
        metadatas = [c["metadata"] for c in all_chunks]
        documents = [c["document"] for c in all_chunks]
        # LOG 4 — sto per scrivere, e confermo che i documenti non sono vuoti
        empty_docs = sum(1 for d in documents if not d)
        logger.info(f"Scrittura (upsert) di {len(ids)} chunk su Chroma "
                    f"(documenti vuoti: {empty_docs})")
        collection.upsert(ids=ids, embeddings=embeddings,
                          metadatas=metadatas, documents=documents)
        logger.info("Upsert su Chroma completato")
    else:
        logger.warning("Nessun chunk generato: niente da scrivere su Chroma")

    return {
        "processed": len(all_chunks),
        "deleted": len(deleted_ids),
        "total_datasets": len(new_datasets),
    }

async def ingest_tenant(tenant_id: str, full_reindex: bool = False) -> Dict[str, int]:
    _status.running = True
    _status.start_time = datetime.now()
    logger.info(f"Starting ingestion for tenant {tenant_id}, full_reindex={full_reindex}")
    try:
        result = await _run_incremental(tenant_id, full_reindex)
    finally:
        _status.running = False
    _status.last_ingestion = datetime.now()
    _status.processed = result["processed"]
    logger.info(f"Ingestion completed for tenant {tenant_id}: {result}")
    return result