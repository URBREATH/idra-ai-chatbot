import asyncio
import os
import logging
import httpx
from dotenv import load_dotenv

from app.observability import tracing

load_dotenv()

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
OLLAMA_KEEP_ALIVE: str | int = int(_keep_alive) if _keep_alive.lstrip("-").isdigit() else _keep_alive
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "4096"))
RETRY_ATTEMPTS = int(os.getenv("OLLAMA_MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("OLLAMA_RETRY_BACKOFF", "2.0"))
BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=1200.0, write=30.0, pool=30.0)

async def list_models() -> list[str]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/api/tags", timeout=100.0)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]


def _ollama_error(resp: httpx.Response) -> str:
    try:
        detail = str(resp.json().get("error", ""))
    except Exception:
        detail = resp.text[:300] if resp.text else ""
    return detail.strip() or resp.reason_phrase


async def _post_with_retry(client: httpx.AsyncClient, url: str, payload: dict) -> tuple[dict, int]:
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = await client.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json(), attempt
        except httpx.HTTPStatusError as exc:
            detail = _ollama_error(exc.response)
            if exc.response.status_code < 500 or attempt == RETRY_ATTEMPTS:
                logger.error("Ollama %s failed: %s", url, detail)
                raise
            logger.warning("Ollama %s transient %d (%s), retry %d/%d",
                           url, exc.response.status_code, detail, attempt, RETRY_ATTEMPTS - 1)
        except httpx.TransportError as exc:
            if attempt == RETRY_ATTEMPTS:
                logger.error("Ollama %s unreachable: %s", url, exc)
                raise
            logger.warning("Ollama %s transport error (%s), retry %d/%d",
                           url, exc, attempt, RETRY_ATTEMPTS - 1)
        await asyncio.sleep(RETRY_BACKOFF * attempt)
    raise RuntimeError("unreachable")


async def generate_embedding(text: str, model: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large"),
                             name: str = "ollama.embedding") -> list[float]:
    with tracing.observe_step(name, as_type="embedding", model=model,
                              input=tracing.io(text),
                              metadata={"chars": len(text or "")}) as obs:
        async with httpx.AsyncClient() as client:
            data, attempt = await _post_with_retry(
                client,
                f"{BASE_URL}/api/embed",
                {"model": model, "input": text, "truncate": True, "keep_alive": OLLAMA_KEEP_ALIVE},
            )
            embeddings = data.get("embeddings") or []
            embedding = embeddings[0] if embeddings else []
            prompt_tokens = data.get("prompt_eval_count")
        meta = {"chars": len(text or "")}
        if isinstance(prompt_tokens, int):
            meta["prompt_tokens"] = prompt_tokens
        if attempt > 1:
            meta["attempts"] = attempt
        tracing.safe_update(obs, output={"dimensions": len(embedding)},
                            metadata=meta,
                            level=None if embedding else "WARNING",
                            status_message=None if embedding else "empty embedding")
        return embedding


def _ns_to_ms(value) -> float | None:
    return round(value / 1e6, 1) if isinstance(value, (int, float)) else None


def _generation_stats(data: dict) -> tuple[dict, dict]:
    """usage_details + timing metadata from an Ollama /api/chat response."""
    prompt_tokens = data.get("prompt_eval_count")
    output_tokens = data.get("eval_count")
    usage = {}
    if isinstance(prompt_tokens, int):
        usage["input"] = prompt_tokens
    if isinstance(output_tokens, int):
        usage["output"] = output_tokens
    if usage:
        usage["total"] = sum(usage.values())
    eval_ms = _ns_to_ms(data.get("eval_duration"))
    meta = {
        "done_reason": data.get("done_reason"),
        "total_ms": _ns_to_ms(data.get("total_duration")),
        "load_ms": _ns_to_ms(data.get("load_duration")),
        "prompt_eval_ms": _ns_to_ms(data.get("prompt_eval_duration")),
        "eval_ms": eval_ms,
        "tokens_per_second": round(output_tokens / (eval_ms / 1000), 2)
        if isinstance(output_tokens, int) and eval_ms else None,
    }
    return usage, {k: v for k, v in meta.items() if v is not None}


async def generate_completion(prompt: str, model: str = os.getenv("OLLAMA_LLM_MODEL", "mistral-nemo"), temperature: float = 0.0, system: str | None = None,
                              name: str = "ollama.chat") -> str:
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    options = {
        "temperature": temperature,
        "num_ctx": OLLAMA_NUM_CTX,
        "num_predict": OLLAMA_NUM_PREDICT,
    }
    with tracing.observe_step(name, as_type="generation", model=model,
                              model_parameters=options,
                              input=tracing.io(messages)) as gen:
        async with httpx.AsyncClient() as client:
            data, attempt = await _post_with_retry(client, f"{BASE_URL}/api/chat", {
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": options,
            })
        content = data.get("message", {}).get("content", "")
        if isinstance(data, dict):
            usage, meta = _generation_stats(data)
            if attempt > 1:
                meta = {**meta, "attempts": attempt}
            truncated = data.get("done_reason") == "length"
            tracing.safe_update(gen, output=tracing.io(content), usage_details=usage or None,
                                metadata=meta or None,
                                level="WARNING" if truncated else None,
                                status_message="num_predict limit reached" if truncated else None)
        if data.get("done_reason") == "length":
            logger.warning(
                "Ollama response reached the configured token limit (num_predict=%d)",
                OLLAMA_NUM_PREDICT,
            )
        return content


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
