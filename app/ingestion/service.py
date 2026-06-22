import uuid
import asyncio
from typing import List, Dict, Any

from ..mongodb.repositories import get_datasets
from ..ollama.client import generate_embedding
from ..chroma.client import get_tenant_collection


def ingest_tenant(tenant_id: str) -> None:
    """Synchronously ingest datasets for a tenant.

    The function executes the asynchronous ingestion logic in a way that works
    both when no event loop is running and when called from inside an existing
    ``asyncio`` event loop (e.g., within ``pytest‑asyncio`` tests). It blocks until
    the ingestion completes, ensuring that side‑effects (such as calls to the
    collection's ``add`` method) are visible immediately after the call.
    """

    import threading

    async def _run() -> None:
        # Retrieve all datasets for the tenant (placeholder implementation).
        datasets: List[Dict[str, Any]] = await get_datasets()
        collection = get_tenant_collection(tenant_id)

        ids: List[str] = []
        embeddings: List[List[float]] = []
        metadatas: List[Dict[str, Any]] = []

        for ds in datasets:
            # Prefer title, fall back to description; skip if neither is present.
            text = ds.get("title") or ds.get("description") or ""
            if not text:
                continue
            embed = await generate_embedding(text)
            doc_id = ds.get("_id", {}).get("id") or str(uuid.uuid4())
            ids.append(doc_id)
            embeddings.append(embed)
            metadatas.append({
                "tenant_id": tenant_id,
                "dataset_id": doc_id,
                "title": ds.get("title"),
                "publisher": ds.get("publisher"),
            })

        # Insert the accumulated records into the tenant‑specific collection.
        collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas)

    # Helper that runs ``_run`` in a fresh event loop.
    def _run_sync() -> None:
        asyncio.run(_run())

    try:
        # If no loop is running in the current thread, ``asyncio.run`` works.
        asyncio.get_running_loop()
    except RuntimeError:
        # No active loop – safe to run directly.
        _run_sync()
    else:
        # An event loop is already active (e.g., pytest‑asyncio). Run the
        # coroutine in a separate thread to avoid ``asyncio.run`` conflicts.
        thread = threading.Thread(target=_run_sync, daemon=True)
        thread.start()
        thread.join()
