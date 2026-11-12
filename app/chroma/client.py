import os
from chromadb import HttpClient as ChromaClient
from typing import Dict, List

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
    for start in range(0, len(ids), batch_size):
        collection.delete(where={"dataset_id": {"$in": ids[start:start + batch_size]}})


def get_indexed_hashes(collection, page_size: int = 5000) -> Dict[str, str]:
    """dataset_id -> content_hash of everything currently in the collection.
    Entities indexed before content hashing get "" (always re-indexed once).
    Returns {} if the collection cannot be read (e.g. mocked in tests)."""
    out: Dict[str, str] = {}
    offset = 0
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
            return out
        offset += page_size
