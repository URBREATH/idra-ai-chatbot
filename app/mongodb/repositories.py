import os
import logging
from dotenv import load_dotenv
from .client import get_database
from typing import List, Dict, Any
from datetime import datetime

load_dotenv()

logger = logging.getLogger(__name__)

db = get_database()
COLLECTION = os.getenv("COLLECTION")

_raw_cursor = os.getenv("CURSOR_LENGTH", "").strip()
CURSOR_LENGTH = int(_raw_cursor) if _raw_cursor.isdigit() else None

# ============================================================================
# QUALE TIPO DI ENTITA' INDICIZZARE
# ----------------------------------------------------------------------------
# DEFAULT ORA: VUOTO -> indicizza TUTTI i tipi (Dataset, Distribution,
# PointOfInterest, TrafficFlowObserved, ...).
# Per restringere a un solo tipo, valorizza INGEST_ENTITY_TYPE nel .env con la
# URI del tipo, es.:
#   INGEST_ENTITY_TYPE=https://uri.etsi.org/ngsi-ld/default-context/Dataset
# ============================================================================
INGEST_ENTITY_TYPE = os.getenv("INGEST_ENTITY_TYPE", "").strip()

logger.debug(f"[mongo] COLLECTION={COLLECTION!r}, "
             f"CURSOR_LENGTH={'tutti' if CURSOR_LENGTH is None else CURSOR_LENGTH}, "
             f"INGEST_ENTITY_TYPE={INGEST_ENTITY_TYPE or 'TUTTI I TIPI'}")


def _base_filter() -> Dict[str, Any]:
    f = {"_id.servicePath": "/"}
    if INGEST_ENTITY_TYPE:                 # se vuoto -> nessun filtro di tipo (tutti)
        f["_id.type"] = INGEST_ENTITY_TYPE
    return f


async def get_datasets(filter_query: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    collection = db[COLLECTION]
    cursor = collection.find(filter_query or {})
    docs = await cursor.to_list(length=CURSOR_LENGTH)
    logger.debug(f"[mongo] get_datasets -> {len(docs)} documenti")
    return docs


async def get_datasets_since(tenant_id: str, last_ingestion: datetime) -> List[Dict[str, Any]]:
    collection = db[COLLECTION]
    since_epoch = last_ingestion.timestamp() if last_ingestion != datetime.min else 0
    filter_query = _base_filter()
    filter_query["modDate"] = {"$gte": since_epoch}
    logger.debug(f"[mongo] get_datasets_since: since_epoch={since_epoch} "
                 f"({'TUTTI' if since_epoch == 0 else 'incrementale'}); filtro={filter_query}")
    cursor = collection.find(filter_query)
    docs = await cursor.to_list(length=CURSOR_LENGTH)
    logger.debug(f"[mongo] get_datasets_since -> {len(docs)} entita' da processare")
    if CURSOR_LENGTH is not None and len(docs) == CURSOR_LENGTH:
        logger.debug(f"[mongo] ATTENZIONE: risultati == CURSOR_LENGTH ({CURSOR_LENGTH}): "
                     f"possibili documenti troncati. Alza CURSOR_LENGTH.")
    return docs


async def get_datasets_by_ids(dataset_ids: List[str]) -> List[Dict[str, Any]]:
    collection = db[COLLECTION]
    cursor = collection.find({"_id.id": {"$in": dataset_ids}})
    docs = await cursor.to_list(length=CURSOR_LENGTH)
    logger.debug(f"[mongo] get_datasets_by_ids -> {len(docs)}/{len(dataset_ids)}")
    return docs


async def get_deleted_dataset_ids(tenant_id: str, last_ingestion: datetime) -> List[str]:
    collection = db["deleted_datasets"]
    since_epoch = last_ingestion.timestamp() if last_ingestion != datetime.min else 0
    # ATTENZIONE: nomi di campo SEGNAPOSTO da verificare con un findOne reale.
    filter_query = {"servicePath": "/", "deletedAt": {"$gte": since_epoch}}
    cursor = collection.find(filter_query)
    records = await cursor.to_list(length=CURSOR_LENGTH)
    ids = [r.get("dataset_id") for r in records]
    logger.debug(f"[mongo] get_deleted_dataset_ids -> {len(ids)}")
    return ids


async def get_all_dataset_ids(tenant_id: str) -> List[str]:
    # Nessun filtro di tipo: restituisce TUTTI gli id, cosi' un full_reindex
    # fa pulizia completa in Chroma prima di reinserire.
    collection = db[COLLECTION]
    cursor = collection.find({"_id.servicePath": "/"}, projection={"_id": 1})
    records = await cursor.to_list(length=CURSOR_LENGTH)
    ids = [r["_id"]["id"] for r in records if r.get("_id", {}).get("id") is not None]
    logger.debug(f"[mongo] get_all_dataset_ids -> {len(ids)} id (tutti i tipi)")
    return ids