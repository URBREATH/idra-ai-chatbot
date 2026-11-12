"""
sources.py — Chooses where the ingestion reads the catalogue from.

INGEST_SOURCES is a comma separated list (order = indexing order):
  mysql      -> Idra MySQL DB (datasets + distributions)          [app/mysql]
  mongo      -> every entity in the Orion-LD MongoDB (legacy)      [app/mongodb]
  mongo_nbs  -> only the NBS case studies stored in Orion-LD Mongo [app/mongodb]

Default "mongo" keeps the previous behaviour. Recommended with Idra:
  INGEST_SOURCES=mysql,mongo_nbs

The three functions keep the signatures the ingestion service always used, so
the service does not need to know which backend is behind them.
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_VALID = ("mysql", "mongo", "mongo_nbs")


def _parse_sources(raw: str) -> List[str]:
    out: List[str] = []
    for s in (raw or "").split(","):
        s = s.strip().lower()
        if not s:
            continue
        if s not in _VALID:
            raise ValueError(f"INGEST_SOURCES: unknown source {s!r} (valid: {', '.join(_VALID)})")
        if s not in out:
            out.append(s)
    if "mongo" in out and "mongo_nbs" in out:
        out.remove("mongo_nbs")  # 'mongo' already includes the NBS entities
    return out or ["mongo"]


INGEST_SOURCES: List[str] = _parse_sources(os.getenv("INGEST_SOURCES", "mongo"))
logger.info(f"[sources] INGEST_SOURCES={INGEST_SOURCES}")


def uses_mysql() -> bool:
    return "mysql" in INGEST_SOURCES


def _dedupe(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for e in entities:
        eid = e.get("_id", {}).get("id")
        if eid in seen:
            continue
        seen.add(eid)
        out.append(e)
    return out


async def get_datasets_since(tenant_id: str, since: datetime) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    for src in INGEST_SOURCES:
        if src == "mysql":
            from ..mysql import repositories as mysql_repo
            batch = await mysql_repo.get_datasets_since(tenant_id, since)
        elif src == "mongo":
            from ..mongodb import repositories as mongo_repo
            batch = await mongo_repo.get_datasets_since(tenant_id, since)
        else:  # mongo_nbs: few entities, always read them all (the hash skips unchanged ones)
            from ..mongodb import repositories as mongo_repo
            batch = await mongo_repo.get_nbs_entities()
        logger.info(f"[sources] {src}: {len(batch)} entities")
        entities.extend(batch)
    return _dedupe(entities)


async def get_all_dataset_ids(tenant_id: str) -> List[str]:
    ids: List[str] = []
    for src in INGEST_SOURCES:
        if src == "mysql":
            from ..mysql import repositories as mysql_repo
            ids.extend(await mysql_repo.get_all_dataset_ids(tenant_id))
        elif src == "mongo":
            from ..mongodb import repositories as mongo_repo
            ids.extend(await mongo_repo.get_all_dataset_ids(tenant_id))
        else:
            from ..mongodb import repositories as mongo_repo
            ids.extend(await mongo_repo.get_nbs_entity_ids())
    return list(dict.fromkeys(ids))


async def get_deleted_dataset_ids(tenant_id: str, since: datetime) -> List[str]:
    ids: List[str] = []
    if "mongo" in INGEST_SOURCES:
        from ..mongodb import repositories as mongo_repo
        ids.extend(i for i in await mongo_repo.get_deleted_dataset_ids(tenant_id, since) if i)
    # mysql / mongo_nbs: removals are detected by reconciling with Chroma (see service)
    return ids
