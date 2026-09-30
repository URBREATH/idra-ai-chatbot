import os
import logging
import re

from dotenv import load_dotenv
from .client import get_database
from typing import List, Dict, Any, Optional
from datetime import datetime

load_dotenv()

logger = logging.getLogger(__name__)

db = get_database()
COLLECTION = os.getenv("COLLECTION")

_raw_cursor = os.getenv("CURSOR_LENGTH", "").strip()
CURSOR_LENGTH = int(_raw_cursor) if _raw_cursor.isdigit() else None

# Tipi di entita' da leggere. Accetta un ELENCO separato da virgola, es.
# "Dataset,DistributionDCAT-AP". Vuoto = tutti i tipi.
INGEST_ENTITY_TYPE = os.getenv("INGEST_ENTITY_TYPE", "").strip()
_ENTITY_TYPES = [t.strip() for t in INGEST_ENTITY_TYPE.split(",") if t.strip()]

logger.debug(f"[mongo] COLLECTION={COLLECTION!r}, "
             f"CURSOR_LENGTH={'tutti' if CURSOR_LENGTH is None else CURSOR_LENGTH}, "
             f"INGEST_ENTITY_TYPE={_ENTITY_TYPES or 'TUTTI I TIPI'}")


def _type_filter() -> Optional[Dict[str, Any]]:
    """
    Filtro su _id.type che matcha l'ULTIMO segmento del tipo, cosi' funziona sia
    se in Mongo il tipo e' una stringa secca ('Dataset') sia se e' un URL
    ('https://uri.etsi.org/ngsi-ld/default-context/Dataset'). Case-insensitive.
    Con piu' tipi usa $in (basta che ne matchi uno). Vuoto -> nessun filtro di tipo.
    """
    if not _ENTITY_TYPES:
        return None
    regexes = [re.compile(rf"(^|[/#]){re.escape(t)}$", re.IGNORECASE) for t in _ENTITY_TYPES]
    return {"$in": regexes}


def _base_filter() -> Dict[str, Any]:
    f: Dict[str, Any] = {"_id.servicePath": "/"}
    type_filter = _type_filter()
    if type_filter is not None:
        f["_id.type"] = type_filter  # es. {"$in": [/(^|[/#])Dataset$/i, /(^|[/#])DistributionDCAT-AP$/i]}
    return f


async def get_datasets(filter_query: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    collection = db[COLLECTION]
    docs = await collection.find(filter_query or {}).to_list(length=CURSOR_LENGTH)
    logger.debug(f"[mongo] get_datasets -> {len(docs)} documenti")
    return docs


async def get_datasets_since(tenant_id: str, last_ingestion: datetime) -> List[Dict[str, Any]]:
    collection = db[COLLECTION]
    since_epoch = last_ingestion.timestamp() if last_ingestion != datetime.min else 0
    filter_query = _base_filter()
    filter_query["modDate"] = {"$gte": since_epoch}
    logger.debug(f"[mongo] get_datasets_since: since_epoch={since_epoch} "
                 f"({'TUTTI' if since_epoch == 0 else 'incrementale'}); filtro={filter_query}")
    docs = await collection.find(filter_query).to_list(length=CURSOR_LENGTH)
    logger.debug(f"[mongo] get_datasets_since -> {len(docs)} entita' da processare")
    if CURSOR_LENGTH is not None and len(docs) == CURSOR_LENGTH:
        logger.debug(f"[mongo] ATTENZIONE: risultati == CURSOR_LENGTH ({CURSOR_LENGTH}): possibili troncati.")
    return docs


async def get_datasets_by_ids(dataset_ids: List[str]) -> List[Dict[str, Any]]:
    collection = db[COLLECTION]
    docs = await collection.find({"_id.id": {"$in": dataset_ids}}).to_list(length=CURSOR_LENGTH)
    logger.debug(f"[mongo] get_datasets_by_ids -> {len(docs)}/{len(dataset_ids)}")
    return docs


async def get_deleted_dataset_ids(tenant_id: str, last_ingestion: datetime) -> List[str]:
    collection = db["deleted_datasets"]
    since_epoch = last_ingestion.timestamp() if last_ingestion != datetime.min else 0
    # ATTENZIONE: nomi di campo SEGNAPOSTO da verificare con un findOne reale.
    filter_query = {"servicePath": "/", "deletedAt": {"$gte": since_epoch}}
    records = await collection.find(filter_query).to_list(length=CURSOR_LENGTH)
    ids = [r.get("dataset_id") for r in records]
    logger.debug(f"[mongo] get_deleted_dataset_ids -> {len(ids)}")
    return ids


async def get_all_dataset_ids(tenant_id: str) -> List[str]:
    # Nessun filtro di tipo: pulizia completa in Chroma prima del reinserimento.
    collection = db[COLLECTION]
    records = await collection.find({"_id.servicePath": "/"}, projection={"_id": 1}).to_list(length=CURSOR_LENGTH)
    ids = [r["_id"]["id"] for r in records if r.get("_id", {}).get("id") is not None]
    logger.debug(f"[mongo] get_all_dataset_ids -> {len(ids)} id (tutti i tipi)")
    return ids
