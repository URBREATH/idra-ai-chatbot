import os
import uuid
import asyncio
import logging
import threading
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field

from dotenv import load_dotenv

from .payload_builder import extract_attrs
from ..mongodb.repositories import (
    get_datasets_since,
    get_deleted_dataset_ids,
    get_all_dataset_ids
)
from ..ollama.client import generate_embedding
from ..chroma.client import get_tenant_collection, delete_documents_from_collection

load_dotenv()

# LOGGING: abilita DEBUG per tutti i moduli app.* (senza attivare il debug delle
# librerie di terze parti) e garantisci un handler. NON usiamo basicConfig, che
# sotto Uvicorn verrebbe ignorato.
logging.getLogger("app").setLevel(logging.DEBUG)   # <-- adatta 'app' al nome del tuo package radice
if not logging.getLogger().handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(_h)
logger = logging.getLogger(__name__)

BATCH_SIZE = int(os.getenv("INGESTION_BATCH_SIZE", 500))

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

    dataset_id = ds.get("_id", {}).get("id") or str(uuid.uuid4())

    payload = await build_payload(ds)
    chunks = await chunk_payload(payload, dataset_id)

    attrs = extract_attrs(ds)

    results = []
    for chunk in chunks:
        embed = await generate_embedding(chunk["text"])

        # METADATI: identificativi + filtrabili + DESCRITTIVI (dal Dataset).
        # description/theme/keywords servono al caso "consiglia dai metadati".
        candidate_metadata = {
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "chunk_id": chunk["chunk_id"],
            "title": attrs.get("Title") or ds.get("title"),
            "description": attrs.get("Description"),   # <-- NUOVO
            "theme": attrs.get("Theme"),               # <-- NUOVO (es. 'ENVI')
            "keywords": attrs.get("Keywords"),         # <-- NUOVO (stringa unita)
            "publisher": attrs.get("Publisher") or ds.get("publisher"),
            "url": attrs.get("URL") or attrs.get("LandingPage"),
            "format": attrs.get("Format"),
            "license": attrs.get("License"),
            "released": attrs.get("Published"),
        }
        metadata = {k: v for k, v in candidate_metadata.items() if v is not None}

        results.append({
            "id": chunk["chunk_id"],
            "embedding": embed,
            "metadata": metadata,
            "document": chunk["text"],
        })

    return results

async def _delete_from_collection(collection, dataset_ids: List[str]) -> None:
    delete_documents_from_collection(collection, dataset_ids)

def _flush_to_chroma(collection, buffer: List[Dict[str, Any]], batch_num: int) -> int:
    if not buffer:
        logger.debug(f"[upsert] lotto #{batch_num}: buffer vuoto")
        return 0
    ids = [c["id"] for c in buffer]
    embeddings = [c["embedding"] for c in buffer]
    metadatas = [c["metadata"] for c in buffer]
    documents = [c["document"] for c in buffer]
    empty_docs = sum(1 for d in documents if not d)
    count_pre = collection.count()
    logger.debug(f"[upsert] lotto #{batch_num}: STO PER fare upsert di {len(ids)} chunk "
                 f"(documenti vuoti: {empty_docs}); record ORA: {count_pre}")
    collection.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
    count_post = collection.count()
    nuovi = count_post - count_pre
    logger.debug(f"[upsert] lotto #{batch_num}: ESEGUITO. prima={count_pre}, dopo={count_post} "
                 f"(nuovi={nuovi}, sovrascritti={len(ids) - nuovi})")
    return len(ids)

async def _run_incremental(tenant_id: str, full_reindex: bool = False) -> Dict[str, int]:
    collection = get_tenant_collection(tenant_id)
    count_start = collection.count()
    logger.debug(f"[ingest] START tenant={tenant_id} full_reindex={full_reindex} | record: {count_start}")

    if full_reindex:
        dataset_ids = await get_all_dataset_ids(tenant_id)
        logger.debug(f"[full_reindex] cancellazione di {len(dataset_ids)} dataset")
        await _delete_from_collection(collection, dataset_ids)
        logger.debug(f"[full_reindex] record dopo cancellazione: {collection.count()}")

    if full_reindex:
        effective_since = datetime.min
    else:
        effective_since = _status.last_ingestion or datetime.min

    new_datasets = await get_datasets_since(tenant_id, effective_since)
    deleted_ids = [] if full_reindex else await get_deleted_dataset_ids(tenant_id, effective_since)
    if deleted_ids:
        await _delete_from_collection(collection, deleted_ids)
        logger.debug(f"[ingest] cancellati {len(deleted_ids)} dataset rimossi alla fonte")

    logger.debug(f"[ingest] Trovati {len(new_datasets)} dataset da processare "
                 f"(full_reindex={full_reindex}, since={effective_since})")

    buffer: List[Dict[str, Any]] = []
    processed_total = 0
    batch_num = 0
    for i, ds in enumerate(new_datasets, 1):
        try:
            chunks = await _process_dataset(ds, tenant_id)
            buffer.extend(chunks)
            has_text = all(bool(c.get("document")) for c in chunks)
            logger.debug(f"[{i}/{len(new_datasets)}] {ds.get('_id', {}).get('id')}: "
                         f"+{len(chunks)} chunk (testo={has_text}); buffer {len(buffer)}/{BATCH_SIZE}")
        except Exception:
            logger.debug(f"[{i}/{len(new_datasets)}] errore sul dataset", exc_info=True)

        if len(buffer) >= BATCH_SIZE:
            batch_num += 1
            processed_total += _flush_to_chroma(collection, buffer, batch_num)
            buffer = []

    if buffer:
        batch_num += 1
        processed_total += _flush_to_chroma(collection, buffer, batch_num)
        buffer = []

    count_end = collection.count()
    if processed_total == 0:
        logger.debug("[ingest] nessun chunk generato: NESSUN upsert")
    else:
        logger.debug(f"[ingest] FINE: {processed_total} chunk in {batch_num} lotti. "
                     f"record inizio={count_start}, fine={count_end}")

    return {"processed": processed_total, "deleted": len(deleted_ids), "total_datasets": len(new_datasets)}

async def ingest_tenant(tenant_id: str, full_reindex: bool = False) -> Dict[str, int]:
    _status.running = True
    _status.start_time = datetime.now()
    logger.debug(f"Starting ingestion for tenant {tenant_id}, full_reindex={full_reindex}")
    try:
        result = await _run_incremental(tenant_id, full_reindex)
    finally:
        _status.running = False
    _status.last_ingestion = datetime.now()
    _status.processed = result["processed"]
    logger.debug(f"Ingestion completed for tenant {tenant_id}: {result}")
    return result