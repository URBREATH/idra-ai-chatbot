import os
import httpx

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

async def list_models() -> list[str]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/api/tags", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]


async def generate_embedding(text: str, model: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large")) -> list[float]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE_URL}/api/embeddings", json={"model": model, "prompt": text})
        resp.raise_for_status()
        data = resp.json()
        return data.get("embedding", [])

async def generate_completion(prompt: str, model: str = os.getenv("OLLAMA_LLM_MODEL", "enggpt-2-16b-a3b"), temperature: float = 0.0) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": temperature}
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")


async def generate_batch_embeddings(
    texts: list[str],
    model: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large"),
) -> list[list[float]]:
    """Generate embeddings for a list of texts sequentially.

    Ollama does not expose a native batch endpoint; requests are issued one by
    one and the results are collected in order.
    """
    results: list[list[float]] = []
    for text in texts:
        embedding = await generate_embedding(text, model=model)
        results.append(embedding)
    return results
