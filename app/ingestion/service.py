import os
import uuid
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass
from dotenv import load_dotenv

from .payload_builder import extract_attrs
from ..config.config import FORMAT_CANON
from ..instructions.nbs_instructions import is_nbs_resource, extract_problems_section
from ..mongodb.repositories import (
    get_datasets_since,
    get_deleted_dataset_ids,
    get_all_dataset_ids
)
from ..ollama.client import generate_embedding
from ..chroma.client import get_tenant_collection, delete_documents_from_collection

load_dotenv()

logging.getLogger("app").setLevel(logging.DEBUG)
_h = logging.StreamHandler()
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.getLogger().addHandler(_h)
logger = logging.getLogger(__name__)

BATCH_SIZE = int(os.getenv("INGESTION_BATCH_SIZE", 500))

INGEST_ENTITY_TYPES = os.getenv("INGEST_ENTITY_TYPES", "Dataset,Distribution")
_ALLOWED_TYPES = {t.strip().lower() for t in INGEST_ENTITY_TYPES.split(",") if t.strip()}


def clean_format(raw: str) -> List[str]:
    """'text/csv, CSV' -> ['CSV']. Normalizes and returns a list, for the $contains filter."""
    out: List[str] = []
    for part in str(raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        key = token.rstrip("/").split("/")[-1].lower()
        label = FORMAT_CANON.get(token.lower()) or FORMAT_CANON.get(key) or key.upper()
        if label not in out:
            out.append(label)
    return sorted(out)


def get_entity_type(entity: Dict[str, Any]) -> str:
    """'Dataset', 'DistributionDCAT-AP', ... from the NGSI type (often a URL)."""
    t = entity.get("_id", {}).get("type") or entity.get("type") or ""
    return str(t).rstrip("/#").split("/")[-1].split("#")[-1]


def should_index(entity: Dict[str, Any]) -> bool:
    etype = get_entity_type(entity).lower()
    if "distribution" in etype:
        return "distribution" in _ALLOWED_TYPES
    return etype in _ALLOWED_TYPES


def split_ids(raw: str) -> List[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]

def _suffix(entity_id: str) -> str:
    """Last part of a urn id (after the last ':'). This is what a Dataset and its
    Distribution share, even when their prefixes differ."""
    return str(entity_id or "").split(":")[-1]


def build_distribution_info(entities: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """dataset_id -> {'formats': [...], 'url': '...', 'license': '...'}.
    Handles both directions of the DCAT link (datasetDistribution / belongsToDataset)."""
    dist_by_suffix: Dict[str, Dict[str, Any]] = {}
    ds_id_by_suffix: Dict[str, str] = {}
    for e in entities:
        eid = e.get("_id", {}).get("id")
        if not eid:
            continue
        etype = get_entity_type(e)
        if "Distribution" in etype:
            dist_by_suffix[_suffix(eid)] = e
        elif etype == "Dataset":
            ds_id_by_suffix[_suffix(eid)] = eid

    info: Dict[str, Dict[str, Any]] = {}

    def ensure(dsid: str):
        return info.setdefault(dsid, {"formats": set(), "url": "", "license": set()})

    def carry_over(dsid: str, dist: Dict[str, Any]):
        a = extract_attrs(dist)
        rec = ensure(dsid)
        for f in clean_format(a.get("Format", "")):
            rec["formats"].add(f)
        if not rec["url"]:
            rec["url"] = a.get("URL") or a.get("AccessURL") or ""
        if a.get("License"):
            rec["license"].add(a["License"])

    for e in entities:
        etype = get_entity_type(e)
        eid = e.get("_id", {}).get("id")
        a = extract_attrs(e)
        if etype == "Dataset":
            for ref in split_ids(a.get("DistributionIds", "")):
                dist = dist_by_suffix.get(_suffix(ref))
                if dist:
                    carry_over(eid, dist)
        elif "Distribution" in etype:
            for ref in split_ids(a.get("BelongsToDataset", "")):
                dsid = ds_id_by_suffix.get(_suffix(ref)) or ref
                carry_over(dsid, e)

    return {dsid: {"formats": sorted(v["formats"]), "url": v["url"],
                   "license": ", ".join(sorted(v["license"]))}
            for dsid, v in info.items()}

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


async def _process_dataset(ds: Dict[str, Any], tenant_id: str,
                           distribution_info: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:  # <<< CHANGE 2
    from .payload_builder import build_payload
    from .chunker import chunk_payload

    dataset_id = ds.get("_id", {}).get("id") or str(uuid.uuid4())
    attrs = extract_attrs(ds)
    is_nbs = is_nbs_resource(ds)  # NEW
    nbs_problems = extract_problems_section(attrs.get("Description", "")) if is_nbs else ""
    title = attrs.get("Title") or str(ds.get("title", ""))
    payload = await build_payload(ds)
    chunks = await chunk_payload(payload, dataset_id, title=title)

    entity_type = get_entity_type(ds)

    dinfo = distribution_info.get(dataset_id, {})
    formats = dinfo.get("formats") or clean_format(attrs.get("Format", ""))
    url = attrs.get("URL") or attrs.get("AccessURL") or attrs.get("LandingPage") or dinfo.get("url", "")
    license_str = attrs.get("License") or dinfo.get("license", "")

    results = []
    for chunk in chunks:
        embed = await generate_embedding(chunk["text"])
        candidate_metadata = {
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "chunk_id": chunk["chunk_id"],
            "entity_type": entity_type,
            "title": attrs.get("Title") or ds.get("title"),
            "description": attrs.get("Description"),
            "theme": attrs.get("Theme"),
            "keywords": attrs.get("Keywords"),
            "publisher": attrs.get("Publisher") or ds.get("publisher"),
            "url": url,
            "format": formats,
            "license": license_str,
            "released": attrs.get("Published"),
            "distribution_ids": attrs.get("DistributionIds"),
            "is_nbs": is_nbs,  # NEW
            "nbs_problems": nbs_problems,  # NEW
        }
        metadata = {k: v for k, v in candidate_metadata.items() if v not in (None, "", [])}
        results.append({
            "id": chunk["chunk_id"], "embedding": embed,
            "metadata": metadata, "document": chunk["text"],
        })
    return results


async def _delete_from_collection(collection, dataset_ids: List[str]) -> None:
    delete_documents_from_collection(collection, dataset_ids)


def _flush_to_chroma(collection, buffer: List[Dict[str, Any]], batch_num: int) -> int:
    if not buffer:
        logger.debug(f"[upsert] batch #{batch_num}: empty buffer")
        return 0
    ids = [c["id"] for c in buffer]
    embeddings = [c["embedding"] for c in buffer]
    metadatas = [c["metadata"] for c in buffer]
    documents = [c["document"] for c in buffer]
    empty_docs = sum(1 for d in documents if not d)
    count_pre = collection.count()
    logger.debug(f"[upsert] batch #{batch_num}: ABOUT TO upsert {len(ids)} chunks "
                 f"(empty documents: {empty_docs}); records NOW: {count_pre}")
    collection.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
    count_post = collection.count()
    added = count_post - count_pre
    logger.debug(f"[upsert] batch #{batch_num}: DONE. before={count_pre}, after={count_post} "
                 f"(added={added}, overwritten={len(ids) - added})")
    return len(ids)


async def _run_incremental(tenant_id: str, full_reindex: bool = False) -> Dict[str, int]:
    collection = get_tenant_collection(tenant_id)
    count_start = collection.count()
    logger.debug(f"[ingest] START tenant={tenant_id} full_reindex={full_reindex} | records: {count_start}")

    if full_reindex:
        dataset_ids = await get_all_dataset_ids(tenant_id)
        logger.debug(f"[full_reindex] deleting {len(dataset_ids)} entities")
        await _delete_from_collection(collection, dataset_ids)
        logger.debug(f"[full_reindex] records after deletion: {collection.count()}")

    effective_since = datetime.min if full_reindex else (_status.last_ingestion or datetime.min)

    new_datasets = await get_datasets_since(tenant_id, effective_since)
    deleted_ids = [] if full_reindex else await get_deleted_dataset_ids(tenant_id, effective_since)
    if deleted_ids:
        await _delete_from_collection(collection, deleted_ids)
        logger.debug(f"[ingest] deleted {len(deleted_ids)} removed at source")

    distribution_info = build_distribution_info(new_datasets)
    logger.debug(f"[ingest] distribution info for {len(distribution_info)} datasets")

    entities_to_index = [e for e in new_datasets if should_index(e)]
    skipped = len(new_datasets) - len(entities_to_index)
    logger.debug(f"[ingest] indexing {len(entities_to_index)} entities of types "
                 f"{sorted(_ALLOWED_TYPES)}; skipped {skipped} of other types "
                 f"(full_reindex={full_reindex}, since={effective_since})")

    buffer: List[Dict[str, Any]] = []
    processed_total = 0
    batch_num = 0
    for i, ds in enumerate(entities_to_index, 1):
        try:
            chunks = await _process_dataset(ds, tenant_id, distribution_info)  # <<< CHANGE 2
            buffer.extend(chunks)
            has_text = all(bool(c.get("document")) for c in chunks)
            logger.debug(f"[{i}/{len(entities_to_index)}] {ds.get('_id', {}).get('id')}: "
                         f"+{len(chunks)} chunks (text={has_text}); buffer {len(buffer)}/{BATCH_SIZE}")
        except Exception:
            logger.warning(f"[{i}/{len(entities_to_index)}] error on entity", exc_info=True)

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
        logger.debug("[ingest] no chunks generated: NO upsert")
    else:
        logger.debug(f"[ingest] END: {processed_total} chunks in {batch_num} batches. "
                     f"records start={count_start}, end={count_end}")

    return {"processed": processed_total, "deleted": len(deleted_ids), "total_datasets": len(entities_to_index)}


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
