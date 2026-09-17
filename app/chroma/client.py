import os
from chromadb import HttpClient as ChromaClient
from typing import List

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

def delete_documents_from_collection(collection, dataset_ids) -> None:
    """Cancella da Chroma tutti i chunk delle entita' indicate, filtrando per
    dataset_id (non per chunk_id), cosi' non restano chunk orfani."""
    ids = [d for d in (dataset_ids or []) if d]
    if not ids:
        return
    # Chroma accetta un filtro where con $in: elimina ogni chunk il cui metadato
    # dataset_id sia in questa lista, indipendentemente dal numero di chunk.
    collection.delete(where={"dataset_id": {"$in": ids}})
