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
    return client.get_or_create_collection(name=collection_name)

def delete_documents_from_collection(collection, dataset_ids: List[str]) -> None:
    """Delete all chunks belonging to the given dataset IDs from the collection.

    Uses a metadata `where` filter so that every chunk of a dataset is removed
    regardless of how many chunks were produced during ingestion.
    """
    for did in dataset_ids:
        if did is not None:
            collection.delete(where={"dataset_id": did})