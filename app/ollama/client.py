import asyncio
import os
import logging
import time
import httpx
from dotenv import load_dotenv

from app.observability import otel, tracing

load_dotenv()

logger = logging.getLogger(__name__)

# External API settings (e.g. TensorX, OpenAI, etc.)
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.tensorx.ai/v1").strip().rstrip("/")

# Ollama local settings
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
OLLAMA_KEEP_ALIVE: str | int = int(_keep_alive) if _keep_alive.lstrip("-").isdigit() else _keep_alive
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "4096"))
RETRY_ATTEMPTS = int(os.getenv("OLLAMA_MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("OLLAMA_RETRY_BACKOFF", "2.0"))

OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
BASE_URL = OLLAMA_BASE_URL  # backward-compatible alias
REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=1200.0, write=30.0, pool=30.0)


def is_external_api_enabled() -> bool:
    """True when an external API key (e.g. TensorX) is configured."""
    return bool(os.getenv("LLM_API_KEY", "").strip())


def get_api_base() -> str:
    """Returns the effective base URL (External API or local Ollama)."""
    return os.getenv("LLM_BASE_URL", "https://api.tensorx.ai/v1").strip().rstrip("/") if is_external_api_enabled() else OLLAMA_BASE_URL


def _auth_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = os.getenv("LLM_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


async def list_models() -> list[str]:
    """Returns available models from external API (TensorX) or local Ollama."""
    headers = _auth_headers()
    async with httpx.AsyncClient() as client:
        if is_external_api_enabled():
            base = get_api_base()
            resp = await client.get(f"{base}/models", headers=headers, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]
        else:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=100.0)
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if "error" in body:
            err = body["error"]
            return err.get("message", str(err)) if isinstance(err, dict) else str(err)
    except Exception:
        pass
    return resp.text[:300] if resp.text else resp.reason_phrase


async def _post_with_retry(client: httpx.AsyncClient, url: str, payload: dict, headers: dict | None = None) -> tuple[dict, int]:
    req_headers = headers or _auth_headers()
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = await client.post(url, json=payload, headers=req_headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json(), attempt
        except httpx.HTTPStatusError as exc:
            detail = _error_detail(exc.response)
            if exc.response.status_code < 500 or attempt == RETRY_ATTEMPTS:
                logger.error("LLM %s failed: %s", url, detail)
                otel.add_event("error", "http.status_code", exc.response.status_code, "error.type",
                               type(exc).__name__, "error.message", detail)
                raise
            logger.warning("LLM %s transient %d (%s), retry %d/%d",
                           url, exc.response.status_code, detail, attempt, RETRY_ATTEMPTS - 1)
            otel.add_event("retry", attempt=attempt, max_attempts=RETRY_ATTEMPTS,
                           reason=f"http_{exc.response.status_code}")
            otel.annotate_current_span(**{"http.request.resend_count": attempt})
        except httpx.TransportError as exc:
            if attempt == RETRY_ATTEMPTS:
                logger.error("LLM %s unreachable: %s", url, exc)
                otel.add_event("error", "error.type", type(exc).__name__,
                               "error.message", str(exc)[:300])
                raise
            logger.warning("LLM %s transport error (%s), retry %d/%d",
                           url, exc, attempt, RETRY_ATTEMPTS - 1)
            otel.add_event("retry", attempt=attempt, max_attempts=RETRY_ATTEMPTS,
                           reason=type(exc).__name__)
            otel.annotate_current_span(**{"http.request.resend_count": attempt})
        await asyncio.sleep(RETRY_BACKOFF * attempt)
    raise RuntimeError("unreachable")


async def generate_embedding(
    text: str,
    model: str | None = None,
    name: str = "llm.embedding"
) -> list[float]:
    effective_model = model or os.getenv("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large")
    provider = "openai" if is_external_api_enabled() else "ollama"
    started = time.perf_counter()
    prompt_tokens = None
    cost_details = None
    success = False
    error_type = None
    request_payload: dict | None = None
    try:
        with tracing.observe_step(name, as_type="embedding", model=effective_model,
                                  input=tracing.io(text),
                                  metadata={"chars": len(text or ""), "provider": provider}) as obs:
            async with httpx.AsyncClient() as client:
                if is_external_api_enabled():
                    base = get_api_base()
                    target_url = f"{base}/embeddings"
                    request_payload = {"model": effective_model, "input": text}
                    data, attempt = await _post_with_retry(
                        client,
                        target_url,
                        request_payload,
                    )
                    items = data.get("data") or []
                    embedding = items[0].get("embedding", []) if items else []
                    usage = data.get("usage") or {}
                    prompt_tokens = usage.get("prompt_tokens")
                else:
                    target_url = f"{OLLAMA_BASE_URL}/api/embed"
                    request_payload = {"model": effective_model, "input": text,
                                       "truncate": True, "keep_alive": OLLAMA_KEEP_ALIVE}
                    data, attempt = await _post_with_retry(
                        client,
                        target_url,
                        request_payload,
                    )
                    embeddings = data.get("embeddings") or []
                    embedding = embeddings[0] if embeddings else []
                    prompt_tokens = data.get("prompt_eval_count")

            meta = {"chars": len(text or ""), "provider": provider, "endpoint": target_url,
                    "request": tracing.io(request_payload)}
            usage_details = None
            if isinstance(prompt_tokens, int):
                meta["prompt_tokens"] = prompt_tokens
                usage_details = {"input": prompt_tokens, "total": prompt_tokens}
                cost_details = tracing.token_cost("embedding", prompt_tokens, None,
                                                  model=effective_model)
            tracing.record_usage(effective_model, "embedding", input_tokens=prompt_tokens)
            if attempt > 1:
                meta["attempts"] = attempt
            parsed = httpx.URL(target_url)
            otel.set_gen_ai_attributes(
                system=provider, operation="embeddings", request_model=effective_model,
                input_tokens=prompt_tokens,
                **{"server.address": parsed.host, "server.port": parsed.port,
                   "http.request.method": "POST"},
            )
            tracing.safe_update(obs, output={"dimensions": len(embedding)},
                                metadata=meta,
                                usage_details=usage_details,
                                cost_details=cost_details,
                                level=None if embedding else "WARNING",
                                status_message=None if embedding else "empty embedding")
            success = True
            return embedding
    except Exception as exc:
        error_type = type(exc).__name__
        raise
    finally:
        otel.record_llm_call(
            system=provider, operation="embeddings", model=effective_model,
            duration_s=time.perf_counter() - started,
            input_tokens=prompt_tokens or 0,
            cost_total=(cost_details or {}).get("total", 0.0),
            success=success, error_type=error_type,
        )


def _ns_to_ms(value) -> float | None:
    return round(value / 1e6, 1) if isinstance(value, (int, float)) else None


def _generation_stats(data: dict) -> tuple[dict, dict]:
    """usage_details + timing metadata from a response."""
    # OpenAI / TensorX format
    if "usage" in data and isinstance(data["usage"], dict):
        u = data["usage"]
        usage = {
            "input": u.get("prompt_tokens"),
            "output": u.get("completion_tokens"),
            "total": u.get("total_tokens")
        }
        usage = {k: v for k, v in usage.items() if isinstance(v, int)}
        choices = data.get("choices") or [{}]
        finish_reason = choices[0].get("finish_reason") if choices else None
        meta = {"done_reason": finish_reason}
        return usage, {k: v for k, v in meta.items() if v is not None}

    # Ollama format
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


async def generate_completion(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.0,
    system: str | None = None,
    name: str = "llm.chat",
    metadata: dict | None = None,
) -> str:
    effective_model = model or os.getenv("OLLAMA_LLM_MODEL", "mistral-nemo")
    provider = "openai" if is_external_api_enabled() else "ollama"
    started = time.perf_counter()
    input_tokens = output_tokens = None
    cost_details = None
    finish_reason = None
    success = False
    error_type = None
    request_payload: dict | None = None
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    options = {
        "temperature": temperature,
        "num_ctx": OLLAMA_NUM_CTX,
        "num_predict": OLLAMA_NUM_PREDICT,
    }

    try:
        with tracing.observe_step(name, as_type="generation", model=effective_model,
                                  model_parameters=options,
                                  input=tracing.io(messages),
                                  metadata=metadata or None) as gen:
            async with httpx.AsyncClient() as client:
                if is_external_api_enabled():
                    base = get_api_base()
                    target_url = f"{base}/chat/completions"
                    payload = {
                        "model": effective_model,
                        "messages": messages,
                        "temperature": temperature,
                        "stream": False,
                    }
                    request_payload = payload
                    data, attempt = await _post_with_retry(client, target_url, payload)
                    choices = data.get("choices") or [{}]
                    msg = choices[0].get("message") or {}
                    content = msg.get("content") or ""
                    if not content and msg.get("reasoning_content"):
                        content = msg["reasoning_content"]
                    finish_reason = choices[0].get("finish_reason")
                    truncated = finish_reason == "length"
                else:
                    target_url = f"{OLLAMA_BASE_URL}/api/chat"
                    payload = {
                        "model": effective_model,
                        "messages": messages,
                        "stream": False,
                        "keep_alive": OLLAMA_KEEP_ALIVE,
                        "options": options,
                    }
                    request_payload = payload
                    data, attempt = await _post_with_retry(client, target_url, payload)
                    content = data.get("message", {}).get("content", "")
                    finish_reason = data.get("done_reason")
                    truncated = finish_reason == "length"

            if isinstance(data, dict):
                usage, meta = _generation_stats(data)
                input_tokens = usage.get("input")
                output_tokens = usage.get("output")
                if truncated:
                    logger.warning("Response reached the configured token limit (num_predict=%s)",
                                   OLLAMA_NUM_PREDICT)
                meta = {**meta, "provider": provider, "endpoint": target_url,
                        "request": tracing.io(request_payload)}
                if attempt > 1:
                    meta = {**meta, "attempts": attempt}
                tracing.record_usage(effective_model, "generation",
                                     input_tokens=input_tokens,
                                     output_tokens=output_tokens)
                cost_details = tracing.token_cost("generation", input_tokens, output_tokens,
                                                  model=effective_model)
                parsed = httpx.URL(target_url)
                otel.set_gen_ai_attributes(
                    system=provider, operation="chat", request_model=effective_model,
                    response_model=data.get("model") or effective_model,
                    input_tokens=input_tokens, output_tokens=output_tokens,
                    finish_reason=finish_reason,
                    **{"server.address": parsed.host, "server.port": parsed.port,
                       "http.request.method": "POST"},
                )
                tracing.safe_update(gen, output=tracing.io(content), usage_details=usage or None,
                                    cost_details=cost_details,
                                    metadata={**(metadata or {}), **meta} or None,
                                    level="WARNING" if truncated else None,
                                    status_message="max tokens reached" if truncated else None)
            success = True
            return content
    except Exception as exc:
        error_type = type(exc).__name__
        raise
    finally:
        otel.record_llm_call(
            system=provider, operation="chat", model=effective_model,
            duration_s=time.perf_counter() - started,
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
            cost_total=(cost_details or {}).get("total", 0.0),
            success=success, error_type=error_type,
        )


async def generate_batch_embeddings(
    texts: list[str],
    model: str | None = None,
) -> list[list[float]]:
    """Generate embeddings for a list of texts (batch or sequential)."""
    effective_model = model or os.getenv("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large")
    if not texts:
        return []

    # If external API, we can do batching (e.g. in batches of 32)
    if is_external_api_enabled():
        base = get_api_base()
        results: list[list[float]] = []
        total_tokens = 0
        batch_size = 32
        started = time.perf_counter()
        success = False
        error_type = None
        try:
            with tracing.observe_step("llm.embedding_batch", as_type="embedding",
                                      model=effective_model,
                                      input=tracing.io({"texts": texts, "batch_size": batch_size}),
                                      metadata={"provider": "openai", "endpoint": f"{base}/embeddings",
                                                "characters": sum(len(t or "") for t in texts)}) as obs:
                async with httpx.AsyncClient() as client:
                    batches = []
                    for i in range(0, len(texts), batch_size):
                        batch = texts[i:i + batch_size]
                        batches.append(batch)
                        try:
                            data, _ = await _post_with_retry(
                                client,
                                f"{base}/embeddings",
                                {"model": effective_model, "input": batch},
                            )
                            items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
                            for item in items:
                                results.append(item.get("embedding", []))
                            usage = data.get("usage") or {}
                            if isinstance(usage.get("prompt_tokens"), int):
                                total_tokens += usage["prompt_tokens"]
                        except Exception as exc:
                            logger.warning("Batch embedding failed (%s), falling back to one-by-one", exc)
                            for t in batch:
                                results.append(await generate_embedding(t, model=effective_model))
                tracing.record_usage(effective_model, "embedding", input_tokens=total_tokens or None)
                cost_details = tracing.token_cost("embedding", total_tokens or None, None,
                                                  model=effective_model)
                otel.set_gen_ai_attributes(
                    system="openai", operation="embeddings", request_model=effective_model,
                    input_tokens=total_tokens,
                )
                tracing.safe_update(obs, output={"vectors": len(results),
                                                 "prompt_tokens": total_tokens or None},
                                    metadata={"provider": "openai", "endpoint": f"{base}/embeddings",
                                              "batches": len(batches), "batch_size": batch_size,
                                              "characters": sum(len(t or "") for t in texts)},
                                    cost_details=cost_details)
                success = True
            return results
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            otel.record_llm_call(
                system="openai", operation="embeddings", model=effective_model,
                duration_s=time.perf_counter() - started,
                input_tokens=total_tokens, success=success, error_type=error_type,
            )

    # Fallback Ollama sequential
    results = []
    for text in texts:
        results.append(await generate_embedding(text, model=effective_model))
    return results
