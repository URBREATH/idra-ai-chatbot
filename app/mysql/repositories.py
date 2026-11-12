"""
repositories.py — Reads the federated catalogue straight from the Idra MySQL DB.

Idra stores the harvested DCAT-AP metadata in relational tables:
  odms                  -> federated catalogues (nodeID = odms.id)
  dcat_dataset          -> datasets, PK (dataset_id, nodeID)
  dcat_distribution     -> distributions, FK (dataset_id, nodeID)
  dcat_keyword          -> keywords per dataset
  dcat_concept(+_preflabel) -> themes (type 1 = DCAT theme, type 2 = INSPIRE topic)
  dcat_agent_name       -> publisher names
  dcat_licensedocument  -> distribution licenses

Rows are reshaped into the same NGSI-like structure the Orion/Mongo source
produces ({"_id": {"id", "type"}, "attrs": {key: {"value": ...}}}), so the rest
of the pipeline (payload_builder, chunker, distribution linking, metadata)
works unchanged. Attribute keys are the ones mapped by config.FIELD_LABELS.

Only columns present in every Idra 4.x schema are selected, so the code works
with or without the newer migrations (resourceUri, metadataEnvelope, ...).
"""
import html
import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

from dotenv import load_dotenv

from .client import fetch_many

load_dotenv()

logger = logging.getLogger(__name__)

DATASET_TYPE = "Dataset"
DISTRIBUTION_TYPE = "DistributionDCAT-AP"
SOURCE_NAME = "idra-mysql"

# Skip datasets whose catalogue no longer exists in `odms` (left behind when a
# catalogue is removed from Idra without cleanup).
ONLY_REGISTERED = os.getenv("MYSQL_ONLY_REGISTERED_CATALOGUES", "true").strip().lower() in ("1", "true", "yes", "on")
# Optional comma separated whitelist of odms ids / nodeIDs, e.g. "96,110".
_NODE_FILTER = {n.strip() for n in os.getenv("MYSQL_NODE_IDS", "").split(",") if n.strip()}
# Preferred language for multilingual labels (themes, publisher names).
PREFERRED_LANG = os.getenv("MYSQL_PREFERRED_LANGUAGE", "en").strip().lower()

_JUNK_LICENSE_URIS = {"http://purl.org/dc/terms/license", "http://purl.org/dc/terms/rights"}

_BLOCK_TAGS = re.compile(r"<\s*(br|/p|/li|/h[1-6]|/div|/tr)\s*/?\s*>", re.IGNORECASE)
_LI_TAG = re.compile(r"<\s*li[^>]*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\u00a0]+")
_MANY_NEWLINES = re.compile(r"\n\s*\n\s*\n+")


def clean_text(value: Any) -> str:
    """HTML -> plain text. Keeps paragraph breaks (the chunker splits on them)."""
    if value is None:
        return ""
    text = str(value).replace("\\n", "\n").replace("\r\n", "\n")
    if "<" in text and ">" in text:
        text = _BLOCK_TAGS.sub("\n", text)
        text = _LI_TAG.sub("\n- ", text)
        text = _ANY_TAG.sub(" ", text)
    text = html.unescape(text)
    lines = [_SPACES.sub(" ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    return _MANY_NEWLINES.sub("\n\n", text).strip()


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _join_unique(values: Iterable[str], sep: str = ", ") -> str:
    seen: List[str] = []
    low: Set[str] = set()
    for v in values:
        v = _s(v)
        if v and v.lower() not in low:
            low.add(v.lower())
            seen.append(v)
    return sep.join(seen)


def _pick_label(rows: List[Dict[str, Any]], key: str = "value") -> str:
    """Choose one label among multilingual rows: preferred language, then
    language-neutral, then the first non-empty one."""
    if not rows:
        return ""
    by_lang = {(_s(r.get("language")).lower()): _s(r.get(key)) for r in rows if _s(r.get(key))}
    return by_lang.get(PREFERRED_LANG) or by_lang.get("") or next(iter(by_lang.values()), "")


def _attrs(**fields: Any) -> Dict[str, Dict[str, Any]]:
    """NGSI-like attrs, dropping empty values (extract_attrs would turn None into 'None')."""
    return {k: {"value": v} for k, v in fields.items() if _s(v)}


# --------------------------------------------------------------------------- SQL

_Q_CATALOGUES = "SELECT id, name, publisher_name, country, type, host FROM odms"
_Q_DATASETS = (
    "SELECT dataset_id, nodeID, title, description, landingPage, releaseDate, updateDate, "
    "accessRights, frequency, version, publisher_id FROM dcat_dataset"
)
_Q_DISTRIBUTIONS = (
    "SELECT id, dataset_id, nodeID, title, description, format, mediaType, accessURL, "
    "downloadURL, licenseDocument_id, releaseDate, updateDate, byteSize FROM dcat_distribution"
)
_Q_KEYWORDS = "SELECT dataset_id, nodeID, keywords FROM dcat_keyword"
_Q_THEMES = (
    "SELECT c.concept_id, c.dataset_id, c.nodeID, c.type, p.value, p.language "
    "FROM dcat_concept c JOIN dcat_concept_preflabel p ON p.concept_id = c.concept_id "
    "WHERE c.dataset_id IS NOT NULL"
)
_Q_AGENT_NAMES = "SELECT agent_id, name AS value, language FROM dcat_agent_name"
_Q_LICENSES = "SELECT licenseDocument_id, name, uri FROM dcat_licensedocument"

_Q_DATASET_IDS = "SELECT dataset_id, nodeID FROM dcat_dataset"
_Q_DISTRIBUTION_IDS = "SELECT id, dataset_id, nodeID FROM dcat_distribution"
_Q_CATALOGUE_IDS = "SELECT id FROM odms"


def _allowed_nodes(catalogue_rows: List[Dict[str, Any]]) -> Optional[Set[str]]:
    """Set of allowed nodeIDs, or None = no restriction."""
    allowed: Optional[Set[str]] = None
    if ONLY_REGISTERED:
        allowed = {_s(r.get("id")) for r in catalogue_rows}
    if _NODE_FILTER:
        allowed = _NODE_FILTER if allowed is None else (allowed & _NODE_FILTER)
    return allowed


def _key(dataset_id: Any, node_id: Any) -> tuple:
    return (_s(dataset_id), _s(node_id))


# ---------------------------------------------------------------- entity build

def build_entities(rows: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Pure function (no I/O): turn the raw MySQL rows into NGSI-like entities."""
    catalogues = {_s(r.get("id")): r for r in rows.get("catalogues", [])}
    allowed = _allowed_nodes(rows.get("catalogues", []))

    keywords: Dict[tuple, List[str]] = defaultdict(list)
    for r in rows.get("keywords", []):
        keywords[_key(r.get("dataset_id"), r.get("nodeID"))].append(_s(r.get("keywords")))

    # concept_id -> label rows, then dataset -> [label per concept]
    concept_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    concept_owner: Dict[str, tuple] = {}
    concept_type: Dict[str, str] = {}
    for r in rows.get("themes", []):
        cid = _s(r.get("concept_id"))
        concept_rows[cid].append(r)
        concept_owner[cid] = _key(r.get("dataset_id"), r.get("nodeID"))
        concept_type[cid] = _s(r.get("type"))
    themes: Dict[tuple, List[str]] = defaultdict(list)
    # DCAT themes (type 1) first, then INSPIRE topic categories (type 2)
    for cid in sorted(concept_rows, key=lambda c: concept_type.get(c, "")):
        label = _pick_label(concept_rows[cid])
        if label:
            themes[concept_owner[cid]].append(label)

    agent_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows.get("agent_names", []):
        agent_rows[_s(r.get("agent_id"))].append(r)

    licenses: Dict[str, str] = {}
    for r in rows.get("licenses", []):
        name, uri = _s(r.get("name")), _s(r.get("uri"))
        if uri in _JUNK_LICENSE_URIS:
            uri = ""
        label = name or uri
        if label:
            licenses[_s(r.get("licenseDocument_id"))] = label

    # ---- datasets
    datasets: Dict[tuple, Dict[str, Any]] = {}
    for r in rows.get("datasets", []):
        node = _s(r.get("nodeID"))
        if allowed is not None and node not in allowed:
            continue
        datasets[_key(r.get("dataset_id"), node)] = r

    # ---- distributions grouped by dataset
    dists_by_ds: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows.get("distributions", []):
        k = _key(r.get("dataset_id"), r.get("nodeID"))
        if k in datasets and _s(r.get("id")):
            dists_by_ds[k].append(r)

    entities: List[Dict[str, Any]] = []
    for k, d in datasets.items():
        dataset_id, node = k
        cat = catalogues.get(node, {})
        cat_name = _s(cat.get("name"))
        title = clean_text(d.get("title"))
        kw = _join_unique(keywords.get(k, []))
        th = _join_unique(themes.get(k, []))
        publisher = _pick_label(agent_rows.get(_s(d.get("publisher_id")), [])) or _s(cat.get("publisher_name"))
        dists = dists_by_ds.get(k, [])

        entities.append({
            "_id": {"id": dataset_id, "type": DATASET_TYPE, "servicePath": "/"},
            "source": SOURCE_NAME,
            "nodeID": node,
            "attrs": _attrs(
                title=title,
                description=clean_text(d.get("description")),
                keyword=kw,
                theme=th,
                publisher=publisher,
                landingPage=_s(d.get("landingPage")),
                releaseDate=_s(d.get("releaseDate")),
                modified=_s(d.get("updateDate")),
                accessRights=clean_text(d.get("accessRights")),
                frequency=_s(d.get("frequency")),
                version=_s(d.get("version")),
                catalogue=cat_name,
                country=_s(cat.get("country")),
                datasetDistribution=",".join(_s(x.get("id")) for x in dists),
            ),
        })

        for x in dists:
            fmt = _join_unique([_s(x.get("format")), _s(x.get("mediaType"))])
            dist_title = clean_text(x.get("title"))
            desc = clean_text(x.get("description"))
            # Give each distribution the semantic context of its dataset, so a
            # "CSV about air quality" query can match the file-level document.
            if title and title.lower() not in (dist_title + " " + desc).lower():
                desc = f"{desc}\nDataset: {title}".strip()
            entities.append({
                "_id": {"id": _s(x.get("id")), "type": DISTRIBUTION_TYPE, "servicePath": "/"},
                "source": SOURCE_NAME,
                "nodeID": node,
                "attrs": _attrs(
                    title=dist_title or (f"{title} ({fmt})" if fmt else title),
                    description=desc,
                    keyword=kw,
                    theme=th,
                    publisher=publisher,
                    format=fmt,
                    downloadURL=_s(x.get("downloadURL")),
                    accessUrl=_s(x.get("accessURL")),
                    license=licenses.get(_s(x.get("licenseDocument_id")), ""),
                    releaseDate=_s(x.get("releaseDate")),
                    modified=_s(x.get("updateDate")),
                    byteSize=_s(x.get("byteSize")),
                    catalogue=cat_name,
                    belongsToDataset=dataset_id,
                ),
            })
    return entities


# ------------------------------------------------------------- public (async)

async def load_entities() -> List[Dict[str, Any]]:
    rows = await fetch_many({
        "catalogues": _Q_CATALOGUES,
        "datasets": _Q_DATASETS,
        "distributions": _Q_DISTRIBUTIONS,
        "keywords": _Q_KEYWORDS,
        "themes": _Q_THEMES,
        "agent_names": _Q_AGENT_NAMES,
        "licenses": _Q_LICENSES,
    })
    entities = build_entities(rows)
    n_ds = sum(1 for e in entities if e["_id"]["type"] == DATASET_TYPE)
    logger.info(f"[mysql] loaded {n_ds} datasets and {len(entities) - n_ds} distributions "
                f"(rows: datasets={len(rows['datasets'])}, distributions={len(rows['distributions'])}, "
                f"only_registered={ONLY_REGISTERED}, node_filter={sorted(_NODE_FILTER) or 'none'})")
    return entities


async def get_datasets_since(tenant_id: str, last_ingestion: datetime) -> List[Dict[str, Any]]:
    """Returns ALL current entities. Idra's updateDate is the *source* modification
    date (often empty) and harvesting rewrites rows, so a time filter would be
    unreliable: incremental runs are handled by the content hash in the service."""
    return await load_entities()


async def get_all_dataset_ids(tenant_id: str) -> List[str]:
    """Ids of every entity (datasets + distributions) the MySQL source would index."""
    rows = await fetch_many({
        "catalogues": _Q_CATALOGUE_IDS,
        "datasets": _Q_DATASET_IDS,
        "distributions": _Q_DISTRIBUTION_IDS,
    })
    allowed = _allowed_nodes(rows["catalogues"])
    ds_keys = {_key(r.get("dataset_id"), r.get("nodeID")) for r in rows["datasets"]
               if allowed is None or _s(r.get("nodeID")) in allowed}
    ids = [k[0] for k in ds_keys]
    ids += [_s(r.get("id")) for r in rows["distributions"]
            if _key(r.get("dataset_id"), r.get("nodeID")) in ds_keys and _s(r.get("id"))]
    return ids


async def get_deleted_dataset_ids(tenant_id: str, last_ingestion: datetime) -> List[str]:
    """Idra deletes rows physically: removals are detected by the service by
    comparing the ids in Chroma with get_all_dataset_ids()."""
    return []
