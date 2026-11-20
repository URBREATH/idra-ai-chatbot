import os
import json
import time
import uuid
import hashlib
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field
from dotenv import load_dotenv


from .payload_builder import extract_attrs, build_payload
from .chunker import chunk_payload
from ..config.config import FORMAT_CANON
from ..instructions.nbs_instructions import is_nbs_resource, extract_problems_section
from .sources import (
    INGEST_SOURCES,
    get_datasets_since,
    get_deleted_dataset_ids,
    get_all_dataset_ids
)
from ..ollama.client import generate_batch_embeddings
from ..observability import otel, tracing
from ..chroma.client import get_tenant_collection, reset_tenant_collection, delete_documents_from_collection, get_indexed_hashes

load_dotenv()

# LOGGING: abilita DEBUG per tutti i moduli app.* (senza attivare il debug delle
# librerie di terze parti) e garantisci un handler. NON usiamo basicConfig, che
# sotto Uvicorn verrebbe ignorato.
logging.getLogger("app").setLevel(logging.DEBUG)  # <-- adatta 'app' al package radice
if not logging.getLogger().handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(_h)
logger = logging.getLogger(__name__)

BATCH_SIZE = int(os.getenv("INGESTION_BATCH_SIZE", 500))

INGEST_ENTITY_TYPES = os.getenv("INGEST_ENTITY_TYPES", "Dataset,Distribution")
_ALLOWED_TYPES = {t.strip().lower() for t in INGEST_ENTITY_TYPES.split(",") if t.strip()}

_INDEX_CONFIG = {
    "embedding_model": os.getenv("OLLAMA_EMBEDDING_MODEL", ""),
    "enrichment": os.getenv("ENABLE_ENRICHMENT", "true").strip().lower(),
    "enrichment_model": os.getenv("OLLAMA_ENRICHMENT_MODEL", "mistral:7b"),
    "technical": os.getenv("INCLUDE_TECHNICAL_IN_EMBEDDING", "false").strip().lower(),
}


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
    sources: List[str] = field(default_factory=lambda: list(INGEST_SOURCES))
    last_result: Optional[Dict[str, int]] = None
    last_error: Optional[str] = None


_status: IngestionStatus = IngestionStatus()


def get_ingestion_status() -> IngestionStatus:
    return _status


def content_hash(entity: Dict[str, Any], dinfo: Optional[Dict[str, Any]] = None) -> str:
    """Fingerprint of what gets indexed for an entity. Unchanged hash = skip
    (no LLM enrichment, no embedding) on incremental runs. Includes the
    enrichment/embedding settings, so changing a model re-indexes everything."""
    payload = {"type": get_entity_type(entity), "attrs": extract_attrs(entity), "dist": dinfo or {},
               "cfg": _INDEX_CONFIG}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


async def _process_dataset(ds: Dict[str, Any], tenant_id: str,
                           distribution_info: Dict[str, Dict[str, Any]],
                           chash: str = "") -> List[Dict[str, Any]]:

    dataset_id = ds.get("_id", {}).get("id") or str(uuid.uuid4())
    attrs = extract_attrs(ds)
    is_nbs = is_nbs_resource(ds)  # NEW
    nbs_problems = extract_problems_section(attrs.get("Description", "")) if is_nbs else ""
    title = attrs.get("Title") or str(ds.get("title", ""))
    with tracing.observe_step("ingestion.build_payload", as_type="span") as pobs:
        payload = await build_payload(ds)
        tracing.safe_update(pobs, output=tracing.io(payload), metadata={"payload_chars": len(payload or "")})
    with tracing.observe_step("ingestion.chunk", as_type="span",
                              metadata={"payload_chars": len(payload or "")}) as cobs:
        chunks = await chunk_payload(payload, dataset_id, title=title)
        tracing.safe_update(cobs, output={"chunks": len(chunks)})
    tracing.fact(payload_chars=len(payload or ""), chunks=len(chunks))

    entity_type = get_entity_type(ds)

    dinfo = distribution_info.get(dataset_id, {})
    formats = dinfo.get("formats") or clean_format(attrs.get("Format", ""))
    url = attrs.get("URL") or attrs.get("AccessURL") or attrs.get("LandingPage") or dinfo.get("url", "")
    license_str = attrs.get("License") or dinfo.get("license", "")

    results = []
    for chunk in chunks:
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
            "parent_dataset_id": attrs.get("BelongsToDataset"),
            "catalogue": attrs.get("Catalogue"),
            "source": ds.get("source") or "orion-mongo",
            "content_hash": chash,
            "is_nbs": is_nbs,  # NEW
            "nbs_problems": nbs_problems,  # NEW
        }
        metadata = {k: v for k, v in candidate_metadata.items() if v not in (None, "", [])}
        results.append({
            "id": chunk["chunk_id"],
            "metadata": metadata,
            "document": chunk["text"],
        })
    return results


def _delete_from_collection(collection, dataset_ids: List[str]) -> None:
    delete_documents_from_collection(collection, dataset_ids)


async def _flush_to_chroma(collection, buffer: List[Dict[str, Any]], batch_num: int) -> int:
    if not buffer:
        logger.debug(f"[upsert] batch #{batch_num}: empty buffer")
        return 0

    texts = [c["document"] for c in buffer]
    with tracing.observe_step("ingestion.embeddings", as_type="span",
                              input=tracing.io({"texts": texts}),
                              metadata={"chunks": len(texts),
                                        "model": os.getenv("OLLAMA_EMBEDDING_MODEL", "")}) as emb_obs:
        embeddings = await generate_batch_embeddings(texts)
        if len(embeddings) != len(texts):
            raise ValueError(f"expected {len(texts)} embeddings, got {len(embeddings)}")
        tracing.safe_update(emb_obs, output={"embeddings": len(embeddings)},
                            metadata={"chunks": len(texts),
                                      "model": os.getenv("OLLAMA_EMBEDDING_MODEL", "")})

    ids = [c["id"] for c in buffer]
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


# Per-entity Langfuse traces (one trace per indexed entity, grouped in the
# session "ingestion-<run id>"). Off = only the run-level trace is sent.
TRACE_ENTITIES = os.getenv("LANGFUSE_TRACE_INGESTION_ENTITIES", "true").strip().lower() in ("1", "true", "yes", "on")


def _percentile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return round(s[k], 3)


async def _index_entity(ds: Dict[str, Any], h: str, tenant_id: str, run_id: str,
                        distribution_info: Dict[str, Dict[str, Any]],
                        changed: bool) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Process one entity inside its own Langfuse trace. Returns (chunks, facts)."""
    eid = ds.get("_id", {}).get("id")
    etype = get_entity_type(ds)
    source = ds.get("source") or "orion-mongo"
    attrs = extract_attrs(ds)
    with tracing.suppressed(not TRACE_ENTITIES), \
            tracing.trace_attributes(session_id=f"ingestion-{run_id}", trace_name="ingestion.entity",
                                     tags=["ingestion", etype, source],
                                     metadata={"run_id": run_id, "tenant_id": tenant_id}), \
            tracing.collect_facts() as facts:
        with tracing.observe_step("ingestion.entity", as_type="chain",
                                  input=tracing.io({"id": eid, "type": etype, "source": source,
                                                    "title": attrs.get("Title"),
                                                    "catalogue": attrs.get("Catalogue")}),
                                  metadata={"content_hash": h, "changed": changed}) as eobs, \
                tracing.collect_metrics() as emetrics:
            chunks = await _process_dataset(ds, tenant_id, distribution_info, h)
            summary = tracing.metrics_summary(emetrics)
            tracing.safe_update(eobs, output={"chunks": len(chunks)},
                                metadata={**facts, **summary,
                                          "content_hash": h, "changed": changed})
            if isinstance(facts.get("enrichment_terms"), int):
                tracing.score_trace(eobs, "enrichment_terms", float(facts["enrichment_terms"]),
                                    data_type="NUMERIC")
            if facts.get("enrichment_status"):
                tracing.score_trace(eobs, "enrichment_status", facts["enrichment_status"],
                                    data_type="CATEGORICAL")
            tracing.score_trace(eobs, "chunks", float(len(chunks)), data_type="NUMERIC")
            if summary["usage"]["total"]:
                tracing.score_trace(eobs, "tokens_total", float(summary["usage"]["total"]),
                                    data_type="NUMERIC")
            if summary["cost"]["total"]:
                tracing.score_trace(eobs, "cost_total", float(summary["cost"]["total"]),
                                    data_type="NUMERIC")
        entity_facts = dict(facts)
    return chunks, entity_facts


async def _run_incremental(tenant_id: str, full_reindex: bool = False,
                           run: Any = tracing.NOOP, run_id: str = "") -> Dict[str, int]:
    run_id = run_id or uuid.uuid4().hex[:12]
    collection = get_tenant_collection(tenant_id)
    count_start = collection.count()
    logger.debug(f"[ingest] START tenant={tenant_id} full_reindex={full_reindex} "
                 f"sources={INGEST_SOURCES} | records: {count_start}")

    with tracing.observe_step("ingestion.read_index", as_type="tool", parent=run) as obs:
        # dataset_id -> content_hash of what is already in Chroma
        indexed = get_indexed_hashes(collection)
        logger.debug(f"[ingest] {len(indexed)} entities already in the collection")
        tracing.safe_update(obs, output={"chunks": count_start, "entities": len(indexed)})

    if full_reindex:
        with tracing.observe_step("ingestion.full_reindex_delete", as_type="tool", parent=run) as obs:
            # Source ids + everything already indexed (also cleans ids coming from a
            # previous source, e.g. the old Orion ids after switching to MySQL).
            dataset_ids = list(dict.fromkeys(list(await get_all_dataset_ids(tenant_id)) + list(indexed)))
            logger.debug(f"[full_reindex] deleting {len(dataset_ids)} entities")
            _delete_from_collection(collection, dataset_ids)
            collection = reset_tenant_collection(tenant_id)
            logger.debug(f"[full_reindex] records after deletion/reset: {collection.count()}")
            tracing.safe_update(obs, output={"deleted_entities": len(dataset_ids)})
        indexed = {}

    effective_since = datetime.min if full_reindex else (_status.last_ingestion or datetime.min)

    with tracing.observe_step("ingestion.load_sources", as_type="retriever", parent=run,
                              input={"sources": INGEST_SOURCES, "since": str(effective_since)}) as obs:
        new_datasets = await get_datasets_since(tenant_id, effective_since)
        deleted_ids = [] if full_reindex else list(await get_deleted_dataset_ids(tenant_id, effective_since))
        by_type: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        for e in new_datasets:
            by_type[get_entity_type(e)] = by_type.get(get_entity_type(e), 0) + 1
            src = e.get("source") or "orion-mongo"
            by_source[src] = by_source.get(src, 0) + 1
        tracing.safe_update(obs, output={"entities": len(new_datasets), "by_type": by_type,
                                         "by_source": by_source, "deleted_at_source": len(deleted_ids)})

    with tracing.observe_step("ingestion.plan", as_type="span", parent=run) as plan_obs:
        # Reconciliation: whatever is in Chroma but no longer at the source is stale.
        # Removed at the END of the run, so the chatbot keeps answering with the old
        # index while the new one is being built (e.g. right after switching source).
        stale: List[str] = []
        if not full_reindex and indexed:
            source_ids = set(await get_all_dataset_ids(tenant_id))
            if source_ids:
                already = set(deleted_ids)
                stale = [i for i in indexed if i not in source_ids and i not in already]
                if stale:
                    logger.info(f"[ingest] {len(stale)} entities no longer at the source: "
                                f"will be removed at the end of the run")
            else:
                logger.warning("[ingest] sources returned no ids: skipping stale cleanup for safety")
                tracing.safe_update(plan_obs, level="WARNING", status_message="sources returned no ids")

        if deleted_ids:
            _delete_from_collection(collection, deleted_ids)
            logger.debug(f"[ingest] deleted {len(deleted_ids)} removed at source")
            for i in deleted_ids:
                indexed.pop(i, None)

        distribution_info = build_distribution_info(new_datasets)
        logger.debug(f"[ingest] distribution info for {len(distribution_info)} datasets")

        candidates = [e for e in new_datasets if should_index(e)]
        skipped = len(new_datasets) - len(candidates)

        # Content hash: skip entities whose indexed content did not change.
        entities_to_index: List[tuple] = []
        unchanged = 0
        for e in candidates:
            eid = e.get("_id", {}).get("id")
            h = content_hash(e, distribution_info.get(eid))
            if eid and indexed.get(eid) == h:
                unchanged += 1
                continue
            entities_to_index.append((e, h))

        # Changed entities may now produce fewer chunks: drop their old ones first.
        changed_ids = [e.get("_id", {}).get("id") for e, _ in entities_to_index
                       if e.get("_id", {}).get("id") in indexed]
        if changed_ids:
            _delete_from_collection(collection, changed_ids)
            logger.debug(f"[ingest] removed old chunks of {len(changed_ids)} changed entities")
        tracing.safe_update(plan_obs, output={
            "candidates": len(candidates), "to_index": len(entities_to_index), "unchanged": unchanged,
            "changed": len(changed_ids), "new": len(entities_to_index) - len(changed_ids),
            "skipped_types": skipped, "stale_to_remove": len(stale), "deleted_at_source": len(deleted_ids),
        })

    logger.info(f"[ingest] to index: {len(entities_to_index)} entities of types "
                f"{sorted(_ALLOWED_TYPES)}; unchanged {unchanged}; skipped {skipped} of other types "
                f"(full_reindex={full_reindex}, since={effective_since})")

    total = len(entities_to_index)
    _status.processed = 0
    _status.remaining = total

    buffer: List[Dict[str, Any]] = []
    processed_total = 0
    batch_num = 0
    errors = 0
    seconds: List[float] = []
    enrich_status: Dict[str, int] = {}
    enrich_terms: List[int] = []

    async def _flush() -> int:
        nonlocal batch_num
        batch_num += 1
        with tracing.observe_step("ingestion.chroma_upsert", as_type="tool", parent=run,
                                  input={"batch": batch_num, "chunks": len(buffer)}) as obs:
            n = await _flush_to_chroma(collection, buffer, batch_num)
            tracing.safe_update(obs, output={"upserted": n})
        return n

    changed_set = set(changed_ids)
    for i, (ds, h) in enumerate(entities_to_index, 1):
        t0 = time.perf_counter()
        try:
            chunks, efacts = await _index_entity(ds, h, tenant_id, run_id, distribution_info,
                                                 changed=ds.get("_id", {}).get("id") in changed_set)
            buffer.extend(chunks)
            has_text = all(bool(c.get("document")) for c in chunks)
            logger.debug(f"[{i}/{total}] {ds.get('_id', {}).get('id')}: "
                         f"+{len(chunks)} chunks (text={has_text}); buffer {len(buffer)}/{BATCH_SIZE}")
            seconds.append(time.perf_counter() - t0)
            if efacts.get("enrichment_status"):
                enrich_status[efacts["enrichment_status"]] = enrich_status.get(efacts["enrichment_status"], 0) + 1
            if isinstance(efacts.get("enrichment_terms"), int):
                enrich_terms.append(efacts["enrichment_terms"])
        except Exception:
            errors += 1
            logger.warning(f"[{i}/{total}] error on entity", exc_info=True)
        _status.remaining = total - i

        if len(buffer) >= BATCH_SIZE:
            processed_total += await _flush()
            _status.processed = processed_total
            buffer = []

    if buffer:
        processed_total += await _flush()
        _status.processed = processed_total
        buffer = []

    if stale:
        with tracing.observe_step("ingestion.remove_stale", as_type="tool", parent=run) as obs:
            _delete_from_collection(collection, stale)
            deleted_ids.extend(stale)
            logger.info(f"[ingest] removed {len(stale)} stale entities")
            tracing.safe_update(obs, output={"removed": len(stale)})

    count_end = collection.count()
    if processed_total == 0:
        logger.debug("[ingest] no chunks generated: NO upsert")
    else:
        logger.debug(f"[ingest] END: {processed_total} chunks in {batch_num} batches. "
                     f"records start={count_start}, end={count_end}")

    stats = {
        "seconds_per_entity_avg": round(sum(seconds) / len(seconds), 3) if seconds else None,
        "seconds_per_entity_p50": _percentile(seconds, 0.5),
        "seconds_per_entity_p95": _percentile(seconds, 0.95),
        "enrichment_status": enrich_status,
        "enrichment_terms_avg": round(sum(enrich_terms) / len(enrich_terms), 2) if enrich_terms else None,
        "chunks_start": count_start, "chunks_end": count_end, "batches": batch_num,
    }
    tracing.safe_update(run, metadata={"index_config": _INDEX_CONFIG, **stats,
                                       "metrics": tracing.metrics_summary()})
    return {"processed": processed_total, "deleted": len(deleted_ids), "total_datasets": total,
            "unchanged": unchanged, "errors": errors}


async def ingest_tenant(tenant_id: str, full_reindex: bool = False) -> Dict[str, int]:
    _status.running = True
    _status.start_time = datetime.now()
    _status.last_error = None
    run_id = uuid.uuid4().hex[:12]
    run_started = time.perf_counter()
    logger.debug(f"Starting ingestion for tenant {tenant_id}, full_reindex={full_reindex} (run {run_id})")
    with tracing.trace_attributes(session_id=f"ingestion-{run_id}", trace_name="ingestion.run",
                                  tags=["ingestion", "run", f"tenant:{tenant_id}"],
                                  metadata={"run_id": run_id, "tenant_id": tenant_id}):
        run = tracing.start_root("ingestion.run", as_type="chain",
                                 input={"tenant_id": tenant_id, "full_reindex": full_reindex,
                                        "sources": INGEST_SOURCES, "run_id": run_id},
                                 metadata={"index_config": _INDEX_CONFIG})
        try:
            with tracing.collect_metrics() as run_metrics:
                result = await _run_incremental(tenant_id, full_reindex, run=run, run_id=run_id)
        except Exception as exc:
            _status.last_error = f"{type(exc).__name__}: {exc}"
            tracing.safe_update(run, level="ERROR", status_message=_status.last_error[:500])
            otel.record_ingestion(time.perf_counter() - run_started, errors=1)
            run.end()
            tracing.flush()
            raise
        finally:
            _status.running = False
        _status.last_ingestion = datetime.now()
        _status.processed = result["processed"]
        _status.remaining = 0
        _status.last_result = result
        otel.record_ingestion(time.perf_counter() - run_started,
                              processed=result.get("processed", 0),
                              total=result.get("total_datasets", 0),
                              unchanged=result.get("unchanged", 0),
                              deleted=result.get("deleted", 0),
                              errors=result.get("errors", 0))
        summary = tracing.metrics_summary(run_metrics)
        # output must be set before end(): an ended OTel span ignores new attributes
        tracing.safe_update(run, output=result)
        run.end()
        for name, key in (("entities_indexed", "total_datasets"), ("entities_unchanged", "unchanged"),
                          ("entities_errors", "errors"), ("chunks_upserted", "processed"),
                          ("entities_deleted", "deleted")):
            tracing.score_trace(run, name, float(result.get(key, 0)), data_type="NUMERIC")
        for name, key in (("tokens_input", "input"), ("tokens_output", "output"),
                          ("tokens_total", "total")):
            tracing.score_trace(run, name, float(summary["usage"][key]), data_type="NUMERIC")
        if summary["cost"]["total"]:
            tracing.score_trace(run, "cost_total", float(summary["cost"]["total"]),
                                data_type="NUMERIC")
        tracing.flush()
    logger.debug(f"Ingestion completed for tenant {tenant_id}: {result}")
    return result


