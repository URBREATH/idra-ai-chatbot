import os
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
OLLAMA_KEEP_ALIVE: str | int = int(_keep_alive) if _keep_alive.lstrip("-").isdigit() else _keep_alive
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "4096"))
BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

async def list_models() -> list[str]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/api/tags", timeout=100.0)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]


async def generate_embedding(text: str, model: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large")) -> list[float]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/api/embeddings",
            json={"model": model, "prompt": text, "keep_alive": OLLAMA_KEEP_ALIVE},
            timeout=httpx.Timeout(connect=10.0, read=1200.0, write=30.0, pool=30.0),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("embedding", [])

async def generate_completion(prompt: str, model: str = os.getenv("OLLAMA_LLM_MODEL", "mistral-nemo"), temperature: float = 0.0, system: str | None = None) -> str:
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": {
                    "temperature": temperature,
                    "num_ctx": OLLAMA_NUM_CTX,
                    "num_predict": OLLAMA_NUM_PREDICT,
                }
            },
            timeout=httpx.Timeout(connect=10.0, read=1200.0, write=30.0, pool=30.0),
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("done_reason") == "length":
            logger.warning(
                "Ollama response reached the configured token limit (num_predict=%d)",
                OLLAMA_NUM_PREDICT,
            )
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
