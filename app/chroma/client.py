import os
from chromadb import HttpClient as ChromaClient
from typing import Dict, List

from app.observability import otel

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_URL = f"http://{CHROMA_HOST}:{CHROMA_PORT}"

_client = None

def get_client() -> ChromaClient:
    global _client
    if _client is None:
        _client = ChromaClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return _client

def get_tenant_collection(tenant_id: str):
    collection_name = f"rag_tenant_{tenant_id}"
    client = get_client()
    with otel.db_operation("get_or_create_collection", "chroma", namespace=tenant_id,
                           collection=collection_name):
        return client.get_or_create_collection(name=collection_name, configuration={"hnsw": {"space": "cosine"}})

def reset_tenant_collection(tenant_id: str):
    collection_name = f"rag_tenant_{tenant_id}"
    client = get_client()
    with otel.db_operation("reset_collection", "chroma", namespace=tenant_id,
                           collection=collection_name):
        try:
            client.delete_collection(name=collection_name)
        except Exception:
            pass
        return client.get_or_create_collection(name=collection_name, configuration={"hnsw": {"space": "cosine"}})

def delete_documents_from_collection(collection, dataset_ids, batch_size: int = 500) -> None:
    """Cancella da Chroma tutti i chunk delle entita' indicate, filtrando per
    dataset_id (non per chunk_id), cosi' non restano chunk orfani."""
    ids = [d for d in (dataset_ids or []) if d]
    if not ids:
        return
    # Chroma accetta un filtro where con $in: elimina ogni chunk il cui metadato
    # dataset_id sia in questa lista, indipendentemente dal numero di chunk.
    # A blocchi, per non inviare filtri enormi (migliaia di id con Idra/MySQL).
    with otel.db_operation("delete", "chroma") as span:
        for start in range(0, len(ids), batch_size):
            batch = ids[start:start + batch_size]
            collection.delete(where={"dataset_id": {"$in": batch}})
            otel.add_event("chroma.delete_batch", size=len(batch))
        if span is not None:
            otel.set_attributes(span, {"idra.chroma.deleted_dataset_ids": len(ids),
                                       "idra.chroma.batch_size": batch_size})


def get_indexed_hashes(collection, page_size: int = 5000) -> Dict[str, str]:
    """dataset_id -> content_hash of everything currently in the collection.
    Entities indexed before content hashing get "" (always re-indexed once).
    Returns {} if the collection cannot be read (e.g. mocked in tests)."""
    out: Dict[str, str] = {}
    offset = 0
    with otel.db_operation("get", "chroma") as span:
        while True:
            try:
                res = collection.get(include=["metadatas"], limit=page_size, offset=offset)
            except Exception:
                return out
            if not isinstance(res, dict):
                return out
            metas = res.get("metadatas") or []
            for m in metas:
                if isinstance(m, dict) and m.get("dataset_id"):
                    out.setdefault(str(m["dataset_id"]), str(m.get("content_hash") or ""))
            if len(metas) < page_size:
                break
            offset += page_size
        if span is not None:
            otel.set_attributes(span, {"idra.chroma.indexed_entities": len(out),
                                       "idra.chroma.pages": offset // page_size + 1})
    return out
