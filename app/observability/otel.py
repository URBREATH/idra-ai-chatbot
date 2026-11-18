"""
otel.py — OpenTelemetry bootstrap for the Idra AI Chatbot.

This module owns the process-wide OTel configuration so that every signal
(traces, metrics, logs) shares the same Resource and the same backend settings,
following the OpenTelemetry best practices:

  * Resource attributes: service.name, service.version, service.namespace,
    deployment.environment.name, service.instance.id, host.name and any
    OTEL_RESOURCE_ATTRIBUTES pair.
  * W3C Trace Context propagation (traceparent/tracestate).
  * GenAI / HTTP / DB semantic-convention attributes on spans.
  * OTLP/HTTP exporters for traces, metrics and logs, all optional.
  * Optional Prometheus scrape endpoint for metrics.
  * Optional auto-instrumentation for httpx, pymongo and PyMySQL.
  * structlog processor that injects trace_id/span_id and redacts secrets.

Everything is env-gated and fail-safe: if the SDK is missing, the endpoint is
not configured or the collector is unreachable, the application keeps working
with no-op spans/metrics.

Main env variables:
  OTEL_ENABLED=true|false                 master switch (default true)
  OTEL_SERVICE_NAME=idra-ai-chatbot
  OTEL_SERVICE_VERSION=1.0.0
  OTEL_SERVICE_NAMESPACE=idra
  OTEL_DEPLOYMENT_ENVIRONMENT=production
  OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318
  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT / METRICS_ENDPOINT / LOGS_ENDPOINT
  OTEL_EXPORTER_OTLP_HEADERS=key=value,key2=value2
  OTEL_TRACES_EXPORTER=otlp|none          (default otlp when an endpoint exists)
  OTEL_METRICS_EXPORTER=otlp|prometheus|none
  OTEL_LOGS_EXPORTER=otlp|none
  OTEL_SAMPLE_RATE=1.0                    root sampler ratio (0..1)
  OTEL_PROMETHEUS_PORT=9464
  OTEL_INSTRUMENT_HTTPX / PYMONGO / PYMYSQL / FASTAPI = true|false
  OTEL_CAPTURE_IO=true|false              capture span input/output (default true)
  OTEL_REDACT_PII=true|false              redact e-mails in structured logs
"""
from __future__ import annotations

import contextlib
import functools
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

TRACER_NAME = "idra-ai-chatbot"
_METER_NAME = "idra-ai-chatbot"

_setup_done = False
_setup_result = False
_trace_endpoint: Optional[str] = None
_metrics_endpoint: Optional[str] = None
_logs_endpoint: Optional[str] = None
_tracer_provider = None
_meter_provider = None
_logger_provider = None
_instruments: Optional[Dict[str, Any]] = None
_service_version = os.getenv("OTEL_SERVICE_VERSION") or os.getenv("APP_VERSION") or "1.0.0"

# Trace-level attributes bound by tracing.trace_attributes() when Langfuse is
# not available but a generic OTLP trace backend is configured.
try:
    import contextvars

    _trace_attrs: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
        "otel_trace_attrs", default=None
    )
except Exception:  # pragma: no cover - contextvars is always available
    _trace_attrs = None


# --------------------------------------------------------------------- env
def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _parse_headers(raw: Optional[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for pair in (raw or "").split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            if key.strip():
                headers[key.strip()] = value.strip()
    return headers


def _parse_resource_attributes(raw: Optional[str]) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for pair in (raw or "").split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            if key.strip():
                attrs[key.strip()] = value.strip()
    return attrs


def _signal_endpoint(signal: str) -> Optional[str]:
    """Resolve the endpoint for traces/metrics/logs (OTLP/HTTP)."""
    specific = os.getenv(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT", "").strip()
    if specific:
        return specific
    base = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if base:
        return base.rstrip("/") + f"/v1/{signal}"
    return None


def _service_name() -> str:
    return os.getenv("OTEL_SERVICE_NAME", "idra-ai-chatbot").strip() or "idra-ai-chatbot"


def _deployment_environment() -> str:
    return (
        os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT")
        or os.getenv("LANGFUSE_TRACING_ENVIRONMENT")
        or os.getenv("NODE_ENV")
        or "development"
    ).strip()


def _resource():
    from opentelemetry.sdk.resources import Resource

    release = (
        os.getenv("LANGFUSE_RELEASE")
        or os.getenv("OTEL_SERVICE_VERSION")
        or os.getenv("APP_VERSION")
        or os.getenv("GIT_SHA")
        or ""
    ).strip()
    attributes = {
        "service.name": _service_name(),
        "service.version": _service_version,
        "service.namespace": os.getenv("OTEL_SERVICE_NAMESPACE", "idra").strip() or "idra",
        "service.instance.id": os.getenv("OTEL_SERVICE_INSTANCE_ID", "").strip() or str(uuid.uuid4()),
        "deployment.environment.name": _deployment_environment(),
        # Langfuse reads these two resource attributes (not the generic ones)
        # to tag/filter traces by environment and release.
        "langfuse.environment": _deployment_environment(),
        "langfuse.release": release,
    }
    host = os.getenv("HOSTNAME", "").strip()
    if host:
        attributes["host.name"] = host
    attributes.update(_parse_resource_attributes(os.getenv("OTEL_RESOURCE_ATTRIBUTES")))
    return Resource.create({k: v for k, v in attributes.items() if v})


# -------------------------------------------------------------------- setup
def setup() -> bool:
    """Configure the global OTel providers once. Never raises."""
    global _setup_done, _setup_result, _trace_endpoint, _metrics_endpoint, _logs_endpoint
    global _tracer_provider, _meter_provider, _logger_provider, _service_version
    if _setup_done:
        return _setup_result
    _setup_done = True
    try:
        if not _env_bool("OTEL_ENABLED", True):
            logger.info("[otel] disabled (OTEL_ENABLED=false)")
            return False

        from opentelemetry import metrics as otel_metrics
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        resource = _resource()
        trace_export = os.getenv("OTEL_TRACES_EXPORTER", "").strip().lower()
        metrics_export = os.getenv("OTEL_METRICS_EXPORTER", "").strip().lower()
        logs_export = os.getenv("OTEL_LOGS_EXPORTER", "").strip().lower()
        _trace_endpoint = _signal_endpoint("traces")
        _metrics_endpoint = _signal_endpoint("metrics")
        _logs_endpoint = _signal_endpoint("logs")

        headers = _parse_headers(os.getenv("OTEL_EXPORTER_OTLP_HEADERS"))
        timeout = _env_float("OTEL_EXPORTER_TIMEOUT", 10.0)

        # ---- traces
        # Always register a Resource-aware provider, even without a generic
        # exporter: Langfuse attaches to it and inherits service.* plus
        # langfuse.environment/release.
        existing = otel_trace.get_tracer_provider()
        if isinstance(existing, TracerProvider):
            provider = existing
        else:
            sampler = None
            rate = _env_float("OTEL_SAMPLE_RATE", _env_float("LANGFUSE_SAMPLE_RATE", 1.0))
            if rate < 1.0:
                from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

                sampler = ParentBased(TraceIdRatioBased(max(0.0, rate)))
            provider = TracerProvider(resource=resource, sampler=sampler)
            otel_trace.set_tracer_provider(provider)
        _tracer_provider = provider

        exporter_enabled = trace_export not in ("none", "no", "false", "0")
        if exporter_enabled and _trace_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                provider.add_span_processor(
                    BatchSpanProcessor(
                        OTLPSpanExporter(endpoint=_trace_endpoint, headers=headers or None, timeout=timeout)
                    )
                )
                logger.info("[otel] OTLP traces -> %s", _trace_endpoint)
            except Exception:  # noqa: BLE001
                logger.warning("[otel] cannot configure OTLP traces", exc_info=True)
        else:
            logger.info("[otel] local tracer provider ready (no OTLP trace endpoint)")

        # ---- metrics
        metric_readers = []
        metrics_enabled = metrics_export not in ("none", "no", "false", "0")
        if metrics_enabled and metrics_export in ("", "otlp") and _metrics_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

                metric_readers.append(
                    PeriodicExportingMetricReader(
                        OTLPMetricExporter(endpoint=_metrics_endpoint, headers=headers or None, timeout=timeout)
                    )
                )
                logger.info("[otel] OTLP metrics -> %s", _metrics_endpoint)
            except Exception:  # noqa: BLE001
                logger.warning("[otel] cannot configure OTLP metrics", exc_info=True)
        if metrics_enabled and metrics_export in ("prometheus", "prom"):
            try:
                from opentelemetry.exporter.prometheus import PrometheusMetricReader
                from prometheus_client import start_http_server

                port = _env_int("OTEL_PROMETHEUS_PORT", 9464)
                metric_readers.append(PrometheusMetricReader())
                start_http_server(port)
                logger.info("[otel] Prometheus metrics on :%d", port)
            except Exception:  # noqa: BLE001
                logger.warning("[otel] Prometheus exporter unavailable "
                               "(pip install opentelemetry-exporter-prometheus)", exc_info=True)
        if metric_readers:
            _meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
            otel_metrics.set_meter_provider(_meter_provider)
        elif metrics_enabled and metrics_export in ("", "otlp") and not _metrics_endpoint:
            logger.info("[otel] metrics disabled (no OTLP metrics endpoint)")

        # ---- logs
        logs_enabled = logs_export not in ("none", "no", "false", "0")
        if logs_enabled and logs_export in ("", "otlp") and _logs_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
                from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
                from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

                _logger_provider = LoggerProvider(resource=resource)
                _logger_provider.add_log_record_processor(
                    BatchLogRecordProcessor(
                        OTLPLogExporter(endpoint=_logs_endpoint, headers=headers or None, timeout=timeout)
                    )
                )
                handler = LoggingHandler(
                    level=getattr(logging, os.getenv("OTEL_LOG_LEVEL", "INFO").upper(), logging.INFO),
                    logger_provider=_logger_provider,
                )
                logging.getLogger().addHandler(handler)
                logger.info("[otel] OTLP logs -> %s", _logs_endpoint)
            except Exception:  # noqa: BLE001
                logger.warning("[otel] cannot configure OTLP logs", exc_info=True)

        _setup_result = _tracer_provider is not None
        return _setup_result
    except Exception:  # noqa: BLE001
        logger.warning("[otel] setup failed: tracing/metrics disabled", exc_info=True)
        _setup_result = False
        return False


def _langfuse_configured() -> bool:
    return bool(
        os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        and os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        and _env_bool("LANGFUSE_ENABLED", True)
    )


def tracing_enabled() -> bool:
    """True when spans can be exported (generic OTLP and/or Langfuse)."""
    setup()
    return bool(_tracer_provider is not None and (bool(_trace_endpoint) or _langfuse_configured()))


def enabled() -> bool:
    setup()
    return bool(_tracer_provider is not None)


def service_version() -> str:
    return _service_version


# --------------------------------------------------------------- attributes
def _json(value: Any, limit: int = 20000) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, default=str)
    except Exception:  # noqa: BLE001
        text = str(value)
    return text if len(text) <= limit else text[:limit] + f"... [+{len(text) - limit} chars]"


def _attribute_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value if not isinstance(value, str) or len(value) <= 20000 else value[:20000]
    if isinstance(value, (list, tuple)):
        flat = [v for v in value if isinstance(v, (bool, int, float, str))]
        return flat if len(flat) == len(value) else _json(value)
    return _json(value)


def set_attributes(span: Any, attributes: Dict[str, Any]) -> None:
    if span is None or not getattr(span, "is_recording", lambda: False)():
        return
    try:
        for key, value in attributes.items():
            clean = _attribute_value(value)
            if clean is not None:
                span.set_attribute(key, clean)
    except Exception:  # noqa: BLE001
        logger.debug("[otel] cannot set attributes", exc_info=True)


def annotate_current_span(**attributes: Any) -> None:
    from opentelemetry import trace as otel_trace

    set_attributes(otel_trace.get_current_span(), attributes)


def add_event(name: str, **attributes: Any) -> None:
    from opentelemetry import trace as otel_trace

    span = otel_trace.get_current_span()
    if span is None or not getattr(span, "is_recording", lambda: False)():
        return
    try:
        span.add_event(name, {k: v for k, v in ((k, _attribute_value(v)) for k, v in attributes.items()) if v is not None})
    except Exception:  # noqa: BLE001
        logger.debug("[otel] cannot add event", exc_info=True)


def record_exception(span: Any, exc: BaseException) -> None:
    from opentelemetry.trace import Status, StatusCode

    if span is None:
        return
    try:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, f"{type(exc).__name__}: {exc}"[:500]))
        set_attributes(span, {"error.type": type(exc).__name__})
    except Exception:  # noqa: BLE001
        logger.debug("[otel] cannot record exception", exc_info=True)


def record_exception_current(exc: BaseException) -> None:
    from opentelemetry import trace as otel_trace

    record_exception(otel_trace.get_current_span(), exc)


def set_gen_ai_attributes(
    *,
    system: Optional[str] = None,
    operation: Optional[str] = None,
    request_model: Optional[str] = None,
    response_model: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    finish_reason: Optional[str] = None,
    **extra: Any,
) -> None:
    """Attach the (experimental) OTel GenAI semantic conventions."""
    attributes: Dict[str, Any] = {
        "gen_ai.operation.name": operation,
        "gen_ai.system": system,
        "gen_ai.provider.name": system,
        "gen_ai.request.model": request_model,
        "gen_ai.response.model": response_model,
        "gen_ai.usage.input_tokens": input_tokens,
        "gen_ai.usage.output_tokens": output_tokens,
        "gen_ai.response.finish_reasons": [finish_reason] if finish_reason else None,
        **extra,
    }
    annotate_current_span(**attributes)


def set_http_status(span: Any, status_code: int) -> None:
    from opentelemetry.trace import Status, StatusCode

    set_attributes(span, {"http.response.status_code": status_code})
    if status_code >= 500 and span is not None:
        try:
            span.set_status(Status(StatusCode.ERROR, f"HTTP {status_code}"))
        except Exception:  # noqa: BLE001
            pass


# -------------------------------------------------------------- propagation
def extract_context(headers: Any):
    try:
        from opentelemetry.propagate import extract

        return extract(dict(headers or {}))
    except Exception:  # noqa: BLE001
        return None


def trace_headers() -> Dict[str, str]:
    """Current W3C trace context as response headers."""
    try:
        from opentelemetry.propagate import inject

        carrier: Dict[str, str] = {}
        inject(carrier)
        trace_id, _ = current_ids()
        if trace_id:
            carrier["x-trace-id"] = trace_id
        return carrier
    except Exception:  # noqa: BLE001
        return {}


def current_ids() -> Tuple[Optional[str], Optional[str]]:
    from opentelemetry import trace as otel_trace

    try:
        span = otel_trace.get_current_span()
        context = span.get_span_context()
        if not context or not context.is_valid:
            return None, None
        return format(context.trace_id, "032x"), format(context.span_id, "016x")
    except Exception:  # noqa: BLE001
        return None, None


# ------------------------------------------------------------------- spans
_KIND_MAP = {
    "generation": "LLM",
    "embedding": "EMBEDDING",
    "retriever": "RETRIEVER",
    "reranker": "RERANKER",
    "tool": "TOOL",
    "agent": "AGENT",
    "guardrail": "GUARDRAIL",
    "chain": "CHAIN",
    "span": "CHAIN",
    "event": "CHAIN",
}

_OPERATION_MAP = {
    "generation": "chat",
    "embedding": "embeddings",
    "retriever": "retrieval",
}


def _tracer():
    from opentelemetry import trace as otel_trace

    return otel_trace.get_tracer(TRACER_NAME, _service_version)


def _observation_attributes(name: str, as_type: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    attributes: Dict[str, Any] = {
        "openinference.span.kind": _KIND_MAP.get(as_type, "CHAIN"),
        "langfuse.observation.type": as_type,
        "langfuse.observation.name": name,
    }
    operation = _OPERATION_MAP.get(as_type)
    if operation:
        attributes["gen_ai.operation.name"] = operation
    if kwargs.get("model"):
        attributes["gen_ai.request.model"] = kwargs["model"]
        attributes["llm.model_name"] = kwargs["model"]
    if kwargs.get("input") is not None and _env_bool("OTEL_CAPTURE_IO", _env_bool("LANGFUSE_CAPTURE_IO", True)):
        attributes["idra.input"] = kwargs["input"]
    if kwargs.get("metadata") is not None:
        attributes["idra.metadata"] = kwargs["metadata"]
    return {k: v for k, v in attributes.items() if v is not None}


class _OtelObservation:
    """Small adapter exposing the subset of the Langfuse observation API used
    by the pipeline, backed by a raw OpenTelemetry span."""

    def __init__(self, span: Any, as_type: str = "span"):
        self._span = span
        self._as_type = as_type
        _apply_trace_attrs(span)

    @property
    def trace_id(self) -> Optional[str]:
        try:
            return format(self._span.get_span_context().trace_id, "032x")
        except Exception:  # noqa: BLE001
            return None

    def update(self, **kwargs: Any) -> "_OtelObservation":
        attributes: Dict[str, Any] = {}
        if kwargs.get("model"):
            attributes["gen_ai.request.model"] = kwargs["model"]
        if kwargs.get("model_parameters") is not None:
            params = kwargs["model_parameters"]
            if isinstance(params, dict):
                for key, value in params.items():
                    attributes[f"gen_ai.request.{key}"] = value
            attributes["idra.model_parameters"] = params
        if kwargs.get("input") is not None and _env_bool("OTEL_CAPTURE_IO", _env_bool("LANGFUSE_CAPTURE_IO", True)):
            attributes["idra.input"] = kwargs["input"]
        if kwargs.get("output") is not None and _env_bool("OTEL_CAPTURE_IO", _env_bool("LANGFUSE_CAPTURE_IO", True)):
            attributes["idra.output"] = kwargs["output"]
        if kwargs.get("metadata") is not None:
            attributes["idra.metadata"] = kwargs["metadata"]
        usage = kwargs.get("usage_details") or {}
        for key, attr in (("input", "gen_ai.usage.input_tokens"),
                          ("output", "gen_ai.usage.output_tokens"),
                          ("total", "gen_ai.usage.total_tokens")):
            if isinstance(usage.get(key), (int, float)):
                attributes[attr] = usage[key]
        cost = kwargs.get("cost_details") or {}
        for key in ("input", "output", "total"):
            if isinstance(cost.get(key), (int, float)):
                attributes[f"idra.cost.{key}"] = cost[key]
        level = kwargs.get("level")
        status_message = kwargs.get("status_message")
        if level:
            attributes["idra.level"] = level
        if status_message:
            attributes["idra.status_message"] = status_message
        set_attributes(self._span, attributes)
        if level == "ERROR":
            from opentelemetry.trace import Status, StatusCode

            try:
                self._span.set_status(Status(StatusCode.ERROR, str(status_message or "error")[:500]))
            except Exception:  # noqa: BLE001
                pass
        return self

    def end(self, **kwargs: Any) -> "_OtelObservation":
        self.update(**kwargs)
        try:
            self._span.end()
        except Exception:  # noqa: BLE001
            pass
        return self

    def score(self, **kwargs: Any) -> None:
        add_event("score", **kwargs)

    def score_trace(self, **kwargs: Any) -> None:
        add_event("score", **kwargs)

    def start_observation(self, name: str, as_type: str = "span", **kwargs: Any) -> "_OtelObservation":
        span = _tracer().start_span(name, attributes=_observation_attributes(name, as_type, kwargs))
        return _OtelObservation(span, as_type)

    @contextlib.contextmanager
    def start_as_current_observation(self, name: str, as_type: str = "span", **kwargs: Any):
        with _tracer().start_as_current_span(
            name, attributes=_observation_attributes(name, as_type, kwargs)
        ) as span:
            yield _OtelObservation(span, as_type)


def _apply_trace_attrs(span: Any) -> None:
    if _trace_attrs is None:
        return
    attrs = _trace_attrs.get() or {}
    if not attrs or span is None:
        return
    values: Dict[str, Any] = {k: v for k, v in attrs.items() if v}
    session_id = values.pop("session_id", None)
    user_id = values.pop("user_id", None)
    tags = values.pop("tags", None)
    metadata = values.pop("metadata", None)
    trace_name = values.pop("trace_name", None)
    if trace_name:
        values["idra.trace_name"] = trace_name
    if session_id:
        values["session.id"] = session_id
        values["langfuse.session.id"] = session_id
    if user_id:
        values["user.id"] = user_id
        values["enduser.id"] = user_id
    if tags:
        values["idra.tags"] = tags
    if metadata:
        values["idra.trace_metadata"] = metadata
    set_attributes(span, values)


@contextlib.contextmanager
def observe_step(name: str, as_type: str = "span", **kwargs: Any) -> Iterator[_OtelObservation]:
    """Fallback used by tracing.observe_step when Langfuse is not configured."""
    if not tracing_enabled():
        yield tracing_noop()
        return
    started = time.perf_counter()
    cm = _tracer().start_as_current_span(name, attributes=_observation_attributes(name, as_type, kwargs))
    span = cm.__enter__()
    obs = _OtelObservation(span, as_type)
    try:
        yield obs
    except BaseException as exc:
        obs.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")
        try:
            cm.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:  # noqa: BLE001
            pass
        raise
    else:
        try:
            cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
    finally:
        # The timing is also recorded by tracing.observe_step; nothing to do here.
        _ = started


def start_root(name: str, as_type: str = "span", **kwargs: Any) -> _OtelObservation:
    if not tracing_enabled():
        return tracing_noop()
    span = _tracer().start_span(name, attributes=_observation_attributes(name, as_type, kwargs))
    return _OtelObservation(span, as_type)


@contextlib.contextmanager
def bind_trace_attributes(*, session_id: Optional[str] = None, user_id: Optional[str] = None,
                          tags: Optional[list] = None, metadata: Optional[dict] = None,
                          trace_name: Optional[str] = None) -> Iterator[None]:
    if _trace_attrs is None:
        yield
        return
    token = _trace_attrs.set({
        "session_id": session_id, "user_id": user_id, "tags": tags,
        "metadata": metadata, "trace_name": trace_name,
    })
    try:
        yield
    finally:
        _trace_attrs.reset(token)


def tracing_noop():
    """Avoid importing tracing (circular): a tiny local no-op observation."""
    return _NOOP


class _Noop:
    id = None
    trace_id = None

    def update(self, **_: Any):
        return self

    def end(self, **_: Any):
        return self

    def score(self, **_: Any):
        return None

    def score_trace(self, **_: Any):
        return None

    def start_as_current_observation(self, **_: Any):
        return contextlib.nullcontext(self)

    def start_observation(self, **_: Any):
        return self


_NOOP = _Noop()


# ----------------------------------------------------------------- metrics
def _get_instruments() -> Dict[str, Any]:
    global _instruments
    if _instruments is not None:
        return _instruments
    from opentelemetry import metrics as otel_metrics

    meter = otel_metrics.get_meter(_METER_NAME, _service_version)
    _instruments = {
        "http_requests": meter.create_counter(
            "idra.http.requests", unit="{request}", description="HTTP requests by method/route/status"
        ),
        "chat_requests": meter.create_counter(
            "idra.chat.requests", unit="{request}", description="Chat requests by outcome"
        ),
        "chat_duration": meter.create_histogram(
            "idra.chat.duration", unit="s", description="End-to-end chat latency"
        ),
        "http_duration": meter.create_histogram(
            "http.server.request.duration", unit="s", description="HTTP server latency"
        ),
        "gen_ai_duration": meter.create_histogram(
            "gen_ai.client.operation.duration", unit="s", description="LLM/embedding call latency"
        ),
        "gen_ai_tokens": meter.create_histogram(
            "gen_ai.client.token.usage", unit="{token}", description="Tokens consumed per call"
        ),
        "llm_cost": meter.create_counter(
            "idra.llm.cost", unit="USD", description="Estimated LLM/embedding cost"
        ),
        "retrieval_duration": meter.create_histogram(
            "idra.retrieval.duration", unit="s", description="Retrieval phase latency"
        ),
        "retrieval_candidates": meter.create_histogram(
            "idra.retrieval.candidates", unit="{candidate}", description="Candidate/kept results"
        ),
        "ingestion_duration": meter.create_histogram(
            "idra.ingestion.duration", unit="s", description="Ingestion run latency"
        ),
        "ingestion_entities": meter.create_counter(
            "idra.ingestion.entities", unit="{entity}", description="Entities processed by ingestion"
        ),
        "db_duration": meter.create_histogram(
            "idra.db.operation.duration", unit="s", description="Database operation latency"
        ),
        "errors": meter.create_counter(
            "idra.errors", unit="{error}", description="Errors by component and type"
        ),
    }
    return _instruments


def _instrument(name: str) -> Any:
    try:
        return _get_instruments()[name]
    except Exception:  # noqa: BLE001
        return None


def _safe_record(func_name: str, *args: Any, **kwargs: Any) -> None:
    try:
        instrument = _instrument(func_name)
        if instrument is None:
            return
        if func_name in ("http_requests", "chat_requests", "llm_cost", "ingestion_entities", "errors"):
            instrument.add(*args, **kwargs)
        else:
            instrument.record(*args, **kwargs)
    except Exception:  # noqa: BLE001
        logger.debug("[otel] metric %s failed", func_name, exc_info=True)


def record_http_request(method: str, route: str, status_code: int, duration_s: float) -> None:
    attrs = {
        "http.request.method": method,
        "http.route": route,
        "http.response.status_code": status_code,
    }
    _safe_record("http_duration", duration_s, attrs)
    _safe_record("http_requests", 1, {
        "http.request.method": method,
        "http.route": route,
        "http.response.status_code": status_code,
    })


def record_chat(duration_s: float, *, exit_path: str = "unknown", model: str = "unknown") -> None:
    _safe_record("chat_duration", duration_s, {"idra.exit_path": exit_path, "gen_ai.request.model": model})
    _safe_record("chat_requests", 1, {"idra.exit_path": exit_path, "gen_ai.request.model": model})


def record_llm_call(
    *,
    system: str,
    operation: str,
    model: str,
    duration_s: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_total: float = 0.0,
    success: bool = True,
    error_type: Optional[str] = None,
) -> None:
    attrs = {
        "gen_ai.system": system,
        "gen_ai.provider.name": system,
        "gen_ai.operation.name": operation,
        "gen_ai.request.model": model,
        "error.type": error_type,
    }
    attrs = {k: v for k, v in attrs.items() if v is not None}
    _safe_record("gen_ai_duration", duration_s, attrs)
    if input_tokens:
        _safe_record("gen_ai_tokens", input_tokens, {**attrs, "gen_ai.token.type": "input"})
    if output_tokens:
        _safe_record("gen_ai_tokens", output_tokens, {**attrs, "gen_ai.token.type": "output"})
    if cost_total:
        _safe_record("llm_cost", cost_total, {**attrs})
    if not success:
        _safe_record("errors", 1, {"idra.component": f"llm.{operation}", "error.type": error_type or "unknown"})


def record_retrieval(duration_s: float, *, candidates: int, kept: int, best_distance: Optional[float] = None) -> None:
    attrs = {"idra.retrieval.kept": kept, "idra.retrieval.best_distance": best_distance}
    attrs = {k: v for k, v in attrs.items() if v is not None}
    _safe_record("retrieval_duration", duration_s, attrs)
    _safe_record("retrieval_candidates", candidates, {"idra.retrieval.stage": "candidates"})
    _safe_record("retrieval_candidates", kept, {"idra.retrieval.stage": "kept"})


def record_db_operation(system: str, operation: str, duration_s: float, *, success: bool = True,
                        error_type: Optional[str] = None, namespace: Optional[str] = None,
                        collection: Optional[str] = None) -> None:
    attrs = {
        "db.system": system,
        "db.system.name": system,
        "db.operation": operation,
        "db.operation.name": operation,
        "db.namespace": namespace,
        "db.collection.name": collection,
        "error.type": error_type,
    }
    attrs = {k: v for k, v in attrs.items() if v is not None}
    _safe_record("db_duration", duration_s, attrs)
    if not success:
        _safe_record("errors", 1, {"idra.component": f"db.{system}", "error.type": error_type or "unknown"})


def record_ingestion(duration_s: float, *, processed: int = 0, total: int = 0, unchanged: int = 0,
                     deleted: int = 0, errors: int = 0) -> None:
    attrs = {"idra.ingestion.errors": errors}
    _safe_record("ingestion_duration", duration_s, attrs)
    for name, value in (("processed", processed), ("unchanged", unchanged),
                        ("deleted", deleted), ("errors", errors)):
        if value:
            _safe_record("ingestion_entities", value, {"idra.ingestion.stage": name})
    if total:
        _safe_record("ingestion_entities", total, {"idra.ingestion.stage": "total"})


# ------------------------------------------------------- db span handling
@contextlib.contextmanager
def db_operation(operation: str, system: str, *, namespace: Optional[str] = None,
                 collection: Optional[str] = None, **attributes: Any) -> Iterator[Any]:
    """Span + metric around a database call. Yields the raw OTel span or None."""
    if not tracing_enabled():
        yield None
        return
    started = time.perf_counter()
    span_cm = _tracer().start_as_current_span(
        f"{system}.{operation}",
        attributes={
            "db.system": system, "db.system.name": system,
            "db.operation": operation, "db.operation.name": operation,
            "db.namespace": namespace, "db.collection.name": collection,
            **attributes,
        },
    )
    span = span_cm.__enter__()
    try:
        yield span
    except BaseException as exc:
        record_exception(span, exc)
        try:
            span_cm.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:  # noqa: BLE001
            pass
        record_db_operation(system, operation, time.perf_counter() - started, success=False,
                            error_type=type(exc).__name__, namespace=namespace, collection=collection)
        raise
    else:
        try:
            span_cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
        record_db_operation(system, operation, time.perf_counter() - started, namespace=namespace,
                            collection=collection)


def traced_db(operation: str, system: str, *, namespace: Optional[str] = None,
              collection: Optional[str] = None, **attributes: Any) -> Callable:
    """Decorator for async database functions."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            with db_operation(operation, system, namespace=namespace, collection=collection, **attributes):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def traced_db_sync(operation: str, system: str, *, namespace: Optional[str] = None,
                   collection: Optional[str] = None, **attributes: Any) -> Callable:
    """Decorator for synchronous database functions."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            with db_operation(operation, system, namespace=namespace, collection=collection, **attributes):
                return func(*args, **kwargs)

        return wrapper

    return decorator


# ------------------------------------------------------- auto-instrumentation
def instrument_libraries() -> None:
    """Best-effort auto-instrumentation. Packages are optional dependencies."""
    if not _env_bool("OTEL_ENABLED", True):
        return

    def _instrument(env_name: str, default: bool, importer: Callable[[], Any]) -> None:
        if not _env_bool(env_name, default):
            return
        try:
            instrumentor = importer()
            if not getattr(instrumentor, "is_instrumented_by_opentelemetry", False):
                instrumentor.instrument()
            logger.info("[otel] %s auto-instrumented", env_name)
        except ImportError:
            logger.debug("[otel] %s package not installed", env_name)
        except Exception:  # noqa: BLE001
            logger.warning("[otel] %s instrumentation failed", env_name, exc_info=True)

    _instrument("OTEL_INSTRUMENT_HTTPX", True, lambda: __import__(
        "opentelemetry.instrumentation.httpx", fromlist=["HTTPXClientInstrumentor"]
    ).HTTPXClientInstrumentor())
    _instrument("OTEL_INSTRUMENT_PYMONGO", True, lambda: __import__(
        "opentelemetry.instrumentation.pymongo", fromlist=["PymongoInstrumentor"]
    ).PymongoInstrumentor())
    _instrument("OTEL_INSTRUMENT_PYMYSQL", True, lambda: __import__(
        "opentelemetry.instrumentation.pymysql", fromlist=["PyMySQLInstrumentor"]
    ).PyMySQLInstrumentor())


# -------------------------------------------------------- structlog bridge
_SECRET_KEYS = {
    "authorization", "password", "passwd", "secret", "api_key", "apikey",
    "access_token", "refresh_token", "jwt", "cookie", "set-cookie",
}
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _redact(value: Any) -> Any:
    if not _env_bool("OTEL_REDACT_PII", False):
        return value
    if isinstance(value, str):
        return _EMAIL_RE.sub("[redacted-email]", value)
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    return value


def trace_context_processor(_logger: Any, _method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """structlog processor: trace correlation + secret redaction."""
    trace_id, span_id = current_ids()
    if trace_id:
        event_dict.setdefault("trace_id", trace_id)
    if span_id:
        event_dict.setdefault("span_id", span_id)
    for key in list(event_dict):
        if key.lower() in _SECRET_KEYS:
            event_dict[key] = "[redacted]"
    if _env_bool("OTEL_REDACT_PII", False):
        event_dict = {k: _redact(v) for k, v in event_dict.items()}
    return event_dict


# ------------------------------------------------------------------ shutdown
def force_flush(timeout_millis: int = 30000) -> None:
    for provider in (_tracer_provider, _meter_provider, _logger_provider):
        if provider is None:
            continue
        try:
            provider.force_flush(timeout_millis)
        except Exception:  # noqa: BLE001
            logger.debug("[otel] force_flush failed", exc_info=True)


def shutdown() -> None:
    for provider in (_tracer_provider, _meter_provider, _logger_provider):
        if provider is None:
            continue
        try:
            provider.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("[otel] shutdown failed", exc_info=True)
