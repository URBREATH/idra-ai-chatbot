import os
from typing import Any
from dotenv import load_dotenv
from app.chroma import client as chroma_client

load_dotenv()

DEFAULT_N_RESULTS = int(os.getenv("DEFAULT_N_RESULTS", 10))


def vector_search(
    tenant_id: str,
    query_embedding: list[float],
    n_results: int = DEFAULT_N_RESULTS,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a similarity search against the tenant's ChromaDB collection.

    Tenant isolation is enforced by adding a tenant_id metadata filter on top
    of any additional filters provided by the caller (ARCHITECTURE.md - Multi-Tenant).
    """
    collection = chroma_client.get_tenant_collection(tenant_id)

    metadata_filter: dict[str, Any] = {"tenant_id": tenant_id}
    if where:
        metadata_filter.update(where)

    return collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=metadata_filter,
    )
