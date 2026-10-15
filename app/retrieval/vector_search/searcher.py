import os
from typing import Any
from dotenv import load_dotenv
from app.chroma import client as chroma_client

load_dotenv()

DEFAULT_N_RESULTS = int(os.getenv("DEFAULT_N_RESULTS", 10))
DATASET_TYPE = "Dataset"
DISTRIBUTION_TYPE = "DistributionDCAT-AP"

# Words that signal a request for a specific FILE/format (Distribution level).
# Add other languages here if your users write in them.
_FILE_WORDS = ("download", "file", "csv", "geojson", "json", "xlsx",
               "excel", "shapefile", "shp", "parquet", "pdf", "xml")


def wants_file(message: str) -> bool:
    """# <<< CHANGE 1b: True if the question asks for a file/format -> search Distributions."""
    m = str(message or "").lower()
    return any(w in m for w in _FILE_WORDS)


def vector_search(
        tenant_id: str,
        query_embedding: list[float],
        n_results: int = DEFAULT_N_RESULTS,
        where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Similarity search against the tenant's collection.

    # <<< CHANGE 1: by default search ONLY Datasets (entity_type=Dataset).
    Tenant and extra conditions are combined with $and (Chroma allows only one
    key at the top level of `where`). If the caller already sets entity_type
    (e.g. to search Distributions), the default is not applied.
    """
    collection = chroma_client.get_tenant_collection(tenant_id)

    where = dict(where or {})
    where.setdefault("entity_type", DATASET_TYPE)  # <<< CHANGE 1

    clauses = [{"tenant_id": tenant_id}] + [{k: v} for k, v in where.items()]  # <<< CHANGE 1
    metadata_filter = clauses[0] if len(clauses) == 1 else {"$and": clauses}

    return collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=metadata_filter,
        include=["documents", "metadatas", "distances"],  # <<< CHANGE 1
    )


def search_for_message(tenant_id: str, message: str, query_embedding: list[float],
                       n_results: int = DEFAULT_N_RESULTS,
                       wanted_format: str = "") -> dict[str, Any]:
    """# <<< CHANGE 1b: pick the right level based on the question.
    - file/format question -> Distributions (with optional format filter)
    - otherwise            -> Datasets (vector_search default)."""
    where: dict[str, Any] = {}
    if wants_file(message):
        where["entity_type"] = DISTRIBUTION_TYPE
    if wanted_format:
        where["format"] = {"$contains": wanted_format}
    return vector_search(tenant_id, query_embedding, n_results=n_results, where=where or None)

