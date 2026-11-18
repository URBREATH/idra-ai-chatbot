"""
tracing.py — Thin wrapper around the Langfuse SDK (v5, OpenTelemetry-native).

Every Langfuse observation is an OpenTelemetry span exported over OTLP/HTTP to
Langfuse (`<LANGFUSE_BASE_URL>/api/public/otel`). The pipeline code only uses
the helpers below, so:
  * with no keys configured (tests, local runs) everything is a cheap no-op;
  * an error inside Langfuse can never break a chat request or an ingestion;
  * the SDK can be swapped for another OTel backend in one place.

Configuration (env):
  LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY   enable tracing when both are set
  LANGFUSE_BASE_URL         e.g. http://langfuse-web:3000
  LANGFUSE_ENABLED          "false" to switch off even with keys
  LANGFUSE_TRACING_ENVIRONMENT  e.g. development / production
  LANGFUSE_RELEASE          app release tag
  LANGFUSE_SAMPLE_RATE      0..1 (default 1)
  LANGFUSE_CAPTURE_IO       "false" to avoid sending prompts/answers/texts
  LANGFUSE_MAX_IO_CHARS     truncate long texts (default 20000)
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import time
from typing import Any, Dict, Iterator, List, Optional

from dotenv import load_dotenv

from app.observability import pricing

load_dotenv()

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


CAPTURE_IO = _env_bool("LANGFUSE_CAPTURE_IO", True)
MAX_IO_CHARS = int(os.getenv("LANGFUSE_MAX_IO_CHARS", "20000"))

# Model pricing lives in model_pricing.yaml (see app/observability/pricing.py):
# the operator edits that file and changes are picked up without a restart.
# The env rates below are only the fallback used when the file does not exist.
LLM_INPUT_COST_PER_1K = float(os.getenv("LLM_INPUT_COST_PER_1K", "0") or 0)
LLM_OUTPUT_COST_PER_1K = float(os.getenv("LLM_OUTPUT_COST_PER_1K", "0") or 0)
EMBEDDING_COST_PER_1K = float(os.getenv("EMBEDDING_COST_PER_1K", "0") or 0)

_client = None
_init_done = False


def get_client():
    """The Langfuse client, or None when tracing is disabled/unavailable."""
    global _client, _init_done
    if _init_done:
        return _client
    _init_done = True
    # Bootstrap the shared OTel Resource/TracerProvider first: when Langfuse is
    # enabled it attaches its processor to this provider, so generic OTLP
    # exporters and Langfuse see the same service.* attributes.
    from app.observability import otel

    otel.setup()
    otel.instrument_libraries()
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    if not (public_key and secret_key) or not _env_bool("LANGFUSE_ENABLED", True):
        logger.info("[tracing] Langfuse disabled (no keys or LANGFUSE_ENABLED=false)")
        return None
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=os.getenv("LANGFUSE_BASE_URL", "http://localhost:3000").strip(),
            environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT", "development").strip() or None,
            release=os.getenv("LANGFUSE_RELEASE", "").strip() or None,
            sample_rate=float(os.getenv("LANGFUSE_SAMPLE_RATE", "1.0")),
        )
        logger.info(f"[tracing] Langfuse enabled -> {os.getenv('LANGFUSE_BASE_URL')}")
    except Exception:  # noqa: BLE001
        logger.warning("[tracing] Langfuse init failed: tracing disabled", exc_info=True)
        _client = None
    return _client


def enabled() -> bool:
    return get_client() is not None


def reset_for_tests() -> None:
    global _client, _init_done
    _client, _init_done = None, False


# --------------------------------------------------------------------- no-op

class _NoopObservation:
    """Stands in for a Langfuse observation when tracing is off."""
    id: Optional[str] = None
    trace_id: Optional[str] = None

    def update(self, **_: Any) -> "_NoopObservation":
        return self

    def end(self, **_: Any) -> "_NoopObservation":
        return self

    def score(self, **_: Any) -> None:
        return None

    def score_trace(self, **_: Any) -> None:
        return None

    def start_as_current_observation(self, **_: Any):
        return contextlib.nullcontext(self)

    def start_observation(self, **_: Any) -> "_NoopObservation":
        return self


NOOP = _NoopObservation()


# ------------------------------------------------------------------- helpers

def clip(value: Any, limit: int | None = None) -> Any:
    """Truncate long strings (recursively in lists/dicts) before sending them."""
    limit = limit or MAX_IO_CHARS
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"... [+{len(value) - limit} chars]"
    if isinstance(value, list):
        return [clip(v, limit) for v in value]
    if isinstance(value, dict):
        return {k: clip(v, limit) for k, v in value.items()}
    return value


def io(value: Any) -> Any:
    """Input/output payload, or None when LANGFUSE_CAPTURE_IO=false."""
    return clip(value) if CAPTURE_IO else None


# ------------------------------------------------------- timings / token usage
# A lightweight per-context accumulator. Nested collectors (e.g. one per entity
# inside the ingestion run) merge into their parent on exit, so the run-level
# trace can show totals even though each entity is exported as its own trace.

def _empty_metrics() -> Dict[str, Any]:
    return {
        "timings_ms": {},
        "usage": {"input": 0, "output": 0, "total": 0},
        "cost": {"input": 0.0, "output": 0.0, "total": 0.0},
        "calls": {},
        "models": {},
    }


_metrics: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("lf_metrics", default=None)


@contextlib.contextmanager
def collect_metrics() -> Iterator[Dict[str, Any]]:
    """Collect timings and token usage; merge into the parent collector on exit."""
    parent = _metrics.get()
    metrics = _empty_metrics()
    token = _metrics.set(metrics)
    try:
        yield metrics
    finally:
        _metrics.reset(token)
        if parent is not None:
            _merge_metrics(parent, metrics)


def _merge_metrics(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    for name, value in src["timings_ms"].items():
        dst["timings_ms"][name] = dst["timings_ms"].get(name, 0.0) + value
    for key in ("input", "output", "total"):
        dst["usage"][key] += src["usage"][key]
        dst["cost"][key] += src["cost"][key]
    for kind, count in src["calls"].items():
        dst["calls"][kind] = dst["calls"].get(kind, 0) + count
    for model, values in src["models"].items():
        target = dst["models"].setdefault(
            model, {"input": 0, "output": 0, "total": 0,
                    "cost": {"input": 0.0, "output": 0.0, "total": 0.0}, "calls": 0},
        )
        for key in ("input", "output", "total"):
            target[key] += values[key]
            target["cost"][key] += values["cost"][key]
        target["calls"] += values["calls"]


def record_timing(name: str, seconds: float) -> None:
    """Add a duration (seconds) to the active collector, if any."""
    metrics = _metrics.get()
    if metrics is None or seconds < 0:
        return
    metrics["timings_ms"][name] = metrics["timings_ms"].get(name, 0.0) + seconds * 1000.0


def token_cost(kind: str, input_tokens: Optional[int], output_tokens: Optional[int],
               model: Optional[str] = None) -> Optional[Dict[str, float]]:
    """Cost details from model_pricing.yaml (per-1K prices), env fallback."""
    prompt_tokens = int(input_tokens or 0)
    completion_tokens = int(output_tokens or 0)

    rates = pricing.get_rates(model, kind)
    if rates is not None:
        if kind == "embedding":
            total = prompt_tokens / 1000.0 * rates.get(
                "embedding_per_1k", rates.get("input_per_1k", 0.0)
            )
            if total <= 0:
                return None
            return {"input": round(total, 6), "total": round(total, 6)}
        input_cost = prompt_tokens / 1000.0 * rates.get("input_per_1k", 0.0)
        output_cost = completion_tokens / 1000.0 * rates.get("output_per_1k", 0.0)
        if input_cost <= 0 and output_cost <= 0:
            return None
        return {"input": round(input_cost, 6), "output": round(output_cost, 6),
                "total": round(input_cost + output_cost, 6)}

    # Legacy env fallback, used only when model_pricing.yaml is absent.
    if kind == "embedding":
        total = prompt_tokens / 1000.0 * EMBEDDING_COST_PER_1K
        if total <= 0:
            return None
        return {"input": round(total, 6), "total": round(total, 6)}
    input_cost = prompt_tokens / 1000.0 * LLM_INPUT_COST_PER_1K
    output_cost = completion_tokens / 1000.0 * LLM_OUTPUT_COST_PER_1K
    if input_cost <= 0 and output_cost <= 0:
        return None
    return {"input": round(input_cost, 6), "output": round(output_cost, 6),
            "total": round(input_cost + output_cost, 6)}


def record_usage(model: Optional[str], kind: str, input_tokens: Optional[int] = None,
                 output_tokens: Optional[int] = None) -> None:
    """Record token usage for the active collector and, when configured, its cost."""
    metrics = _metrics.get()
    if metrics is None:
        return
    prompt_tokens = int(input_tokens or 0)
    completion_tokens = int(output_tokens or 0)
    metrics["calls"][kind] = metrics["calls"].get(kind, 0) + 1
    metrics["usage"]["input"] += prompt_tokens
    metrics["usage"]["output"] += completion_tokens
    metrics["usage"]["total"] += prompt_tokens + completion_tokens

    model_key = model or "unknown"
    entry = metrics["models"].setdefault(
        model_key, {"input": 0, "output": 0, "total": 0,
                    "cost": {"input": 0.0, "output": 0.0, "total": 0.0}, "calls": 0},
    )
    entry["input"] += prompt_tokens
    entry["output"] += completion_tokens
    entry["total"] += prompt_tokens + completion_tokens
    entry["calls"] += 1

    cost = token_cost(kind, prompt_tokens, completion_tokens, model=model_key)
    if cost:
        for key in ("input", "output", "total"):
            metrics["cost"][key] += cost.get(key, 0.0)
            entry["cost"][key] += cost.get(key, 0.0)


def metrics_summary(metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """JSON-friendly snapshot for span metadata and scores."""
    source = metrics if metrics is not None else (_metrics.get() or _empty_metrics())
    models = {
        model: {
            **{k: values[k] for k in ("input", "output", "total", "calls")},
            "cost": {k: round(v, 6) for k, v in values["cost"].items()},
        }
        for model, values in source["models"].items()
    }
    return {
        "timings_ms": {name: round(value, 1) for name, value in source["timings_ms"].items()},
        "usage": dict(source["usage"]),
        "cost": {key: round(value, 6) for key, value in source["cost"].items()},
        "calls": dict(source["calls"]),
        "models": models,
    }


def _clean_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


def safe_update(obs: Any, **kwargs: Any) -> None:
    """obs.update(...) that never raises."""
    if obs is None or obs is NOOP:
        return
    try:
        obs.update(**_clean_kwargs(kwargs))
    except Exception:  # noqa: BLE001
        logger.debug("[tracing] update failed", exc_info=True)


_suppressed: contextvars.ContextVar[bool] = contextvars.ContextVar("lf_suppressed", default=False)


@contextlib.contextmanager
def suppressed(active: bool = True) -> Iterator[None]:
    """Inside this block no observation is created (e.g. per-entity ingestion
    tracing switched off: avoids thousands of orphan LLM/embedding traces)."""
    token = _suppressed.set(bool(active) or _suppressed.get())
    try:
        yield
    finally:
        _suppressed.reset(token)


@contextlib.contextmanager
def observe_step(name: str, as_type: str = "span", parent: Any = None, **kwargs: Any) -> Iterator[Any]:
    """Context manager opening a child observation of the current OTel context
    (or of `parent`). Exceptions are recorded with level=ERROR and re-raised.
    The elapsed time is accumulated in the active metrics collector (if any)."""
    started = time.perf_counter()
    try:
        if _suppressed.get():
            yield NOOP
            return
        client = get_client()
        cm = None
        if client is None:
            from app.observability import otel

            if not otel.tracing_enabled():
                yield NOOP
                return
            try:
                cm = otel.observe_step(name, as_type=as_type, **_clean_kwargs(kwargs))
                obs = cm.__enter__()
            except Exception:  # noqa: BLE001
                logger.debug(f"[tracing] cannot open OTel observation {name}", exc_info=True)
                yield NOOP
                return
        else:
            try:
                factory = parent if (parent is not None and parent is not NOOP) else client
                cm = factory.start_as_current_observation(name=name, as_type=as_type, **_clean_kwargs(kwargs))
                obs = cm.__enter__()
            except Exception:  # noqa: BLE001
                logger.debug(f"[tracing] cannot open observation {name}", exc_info=True)
                yield NOOP
                return
        try:
            yield obs
        except BaseException as exc:
            safe_update(obs, level="ERROR", status_message=f"{type(exc).__name__}: {exc}"[:500])
            try:
                cm.__exit__(type(exc), exc, exc.__traceback__)
            except Exception:  # noqa: BLE001
                pass
            raise
        else:
            try:
                cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                logger.debug("[tracing] cannot close observation", exc_info=True)
    finally:
        record_timing(name, time.perf_counter() - started)


def start_root(name: str, as_type: str = "span", **kwargs: Any) -> Any:
    """Start an observation WITHOUT making it current: code that runs outside a
    `with parent.start_as_current_observation(...)` block creates new traces.
    Close it with `.end()`."""
    client = get_client()
    if client is None:
        from app.observability import otel

        if not otel.tracing_enabled():
            return NOOP
        try:
            return otel.start_root(name, as_type=as_type, **_clean_kwargs(kwargs))
        except Exception:  # noqa: BLE001
            logger.debug(f"[tracing] cannot start OTel root {name}", exc_info=True)
            return NOOP
    try:
        return client.start_observation(name=name, as_type=as_type, **_clean_kwargs(kwargs))
    except Exception:  # noqa: BLE001
        logger.debug(f"[tracing] cannot start root {name}", exc_info=True)
        return NOOP


def _attr_value(v: Any) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=True, default=str)
    return s[:190]


@contextlib.contextmanager
def trace_attributes(*, session_id: str | None = None, user_id: str | None = None,
                     tags: List[str] | None = None, metadata: Dict[str, Any] | None = None,
                     trace_name: str | None = None) -> Iterator[None]:
    """Trace-level attributes propagated to every observation opened inside."""
    client = get_client()
    if client is None:
        from app.observability import otel

        if not otel.tracing_enabled():
            yield
            return
        with otel.bind_trace_attributes(session_id=session_id, user_id=user_id, tags=tags,
                                        metadata=metadata, trace_name=trace_name):
            yield
        return
    try:
        from langfuse import propagate_attributes

        cm = propagate_attributes(
            session_id=session_id[:200] if session_id else None,
            user_id=user_id[:200] if user_id else None,
            tags=tags or None,
            metadata={k: _attr_value(v) for k, v in (metadata or {}).items() if v is not None} or None,
            trace_name=trace_name,
        )
        cm.__enter__()
    except Exception:  # noqa: BLE001
        logger.debug("[tracing] propagate_attributes failed", exc_info=True)
        yield
        return
    try:
        yield
    finally:
        try:
            cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


# -------------------------------------------------------- facts per request
# A flat dict of the key decisions taken while answering (language, nbs,
# thresholds, exit path, ...). Stored as metadata on the root observation and,
# for numeric/boolean ones, also as Langfuse scores (aggregatable in dashboards).

_facts: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("lf_facts", default=None)


@contextlib.contextmanager
def collect_facts() -> Iterator[Dict[str, Any]]:
    facts: Dict[str, Any] = {}
    token = _facts.set(facts)
    try:
        yield facts
    finally:
        _facts.reset(token)


def fact(**kv: Any) -> None:
    facts = _facts.get()
    if facts is not None:
        facts.update({k: v for k, v in kv.items() if v is not None})


def get_facts() -> Dict[str, Any]:
    return dict(_facts.get() or {})


# -------------------------------------------------------------------- scores

def score_trace(obs: Any, name: str, value: float | str | bool, *, data_type: str | None = None,
                comment: str | None = None) -> None:
    if obs is None or obs is NOOP:
        return
    if isinstance(value, bool):
        value, data_type = (1.0 if value else 0.0), data_type or "BOOLEAN"
    try:
        obs.score_trace(**_clean_kwargs({"name": name, "value": value, "data_type": data_type,
                                         "comment": comment}))
    except Exception:  # noqa: BLE001
        logger.debug(f"[tracing] score {name} failed", exc_info=True)


def create_score(name: str, value: float | str | bool, *, trace_id: str | None = None,
                 session_id: str | None = None, data_type: str | None = None,
                 comment: str | None = None, metadata: Dict[str, Any] | None = None) -> bool:
    client = get_client()
    if client is None or not (trace_id or session_id):
        return False
    if isinstance(value, bool):
        value, data_type = (1.0 if value else 0.0), data_type or "BOOLEAN"
    try:
        client.create_score(**_clean_kwargs({
            "name": name, "value": value, "trace_id": trace_id, "session_id": session_id,
            "data_type": data_type, "comment": comment, "metadata": metadata,
        }))
        return True
    except Exception:  # noqa: BLE001
        logger.warning(f"[tracing] create_score {name} failed", exc_info=True)
        return False


def current_trace_id() -> Optional[str]:
    client = get_client()
    if client is None:
        from app.observability import otel

        return otel.current_ids()[0]
    try:
        return client.get_current_trace_id()
    except Exception:  # noqa: BLE001
        return None


def trace_url(trace_id: str | None) -> Optional[str]:
    client = get_client()
    if client is None or not trace_id:
        return None
    try:
        return client.get_trace_url(trace_id=trace_id)
    except Exception:  # noqa: BLE001
        return None


def flush() -> None:
    client = get_client()
    if client is not None:
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            logger.debug("[tracing] flush failed", exc_info=True)
    from app.observability import otel

    otel.force_flush()


def shutdown() -> None:
    client = get_client()
    if client is not None:
        try:
            client.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("[tracing] shutdown failed", exc_info=True)
    from app.observability import otel

    # Only flush: the global TracerProvider may be shared with Langfuse (and,
    # in tests, with an in-memory exporter). Shutting it down here would stop
    # span export for any later client in the same process.
    otel.force_flush()
