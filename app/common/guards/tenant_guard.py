import os
from fastapi import Header, HTTPException

DEFAULT_TENANT_ID: str = os.getenv("DEFAULT_TENANT_ID", "default-tenant")
_COLLECTION_PREFIX = "rag_tenant_"


def resolve_tenant(x_tenant_id: str | None = Header(default=None)) -> str:
    """FastAPI dependency: extract and validate the tenant from the request header.

    Falls back to DEFAULT_TENANT_ID when the header is absent.
    Raises 400 if the tenant value contains characters that would break the
    ChromaDB collection naming convention (alphanumeric and underscore only).
    """
    tenant = x_tenant_id or DEFAULT_TENANT_ID
    if not tenant.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail=f"Invalid tenant identifier: '{tenant}'")
    return tenant


def tenant_collection_name(tenant_id: str) -> str:
    """Return the canonical ChromaDB collection name for a given tenant."""
    return f"{_COLLECTION_PREFIX}{tenant_id}"
