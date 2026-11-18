"""Human-editable model pricing for observability cost metrics.

An operator edits ``model_pricing.yaml`` at the project root (or the file
pointed to by ``MODEL_PRICING_FILE``) and the application picks up the change
automatically: the file is re-read whenever its mtime changes, no restart is
required. Prices are expressed in the file currency (default USD) per 1000
tokens.

Resolution order for a model: exact name -> alias -> ``default`` block.
When the file is missing, ``tracing.token_cost`` falls back to the legacy
``LLM_INPUT_COST_PER_1K`` / ``LLM_OUTPUT_COST_PER_1K`` / ``EMBEDDING_COST_PER_1K``
environment variables.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILE = PROJECT_ROOT / "model_pricing.yaml"
RATE_KEYS = ("input_per_1k", "output_per_1k", "embedding_per_1k")

_lock = threading.Lock()
_cache_path: Optional[Path] = None
_cache_mtime: Optional[float] = None
_cache_data: Optional[Dict[str, Any]] = None
_missing_logged = False


def pricing_file() -> Path:
    raw = os.getenv("MODEL_PRICING_FILE", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_FILE


def _coerce_rates(raw: Any) -> Dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    rates: Dict[str, float] = {}
    for key in RATE_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        try:
            rates[key] = max(0.0, float(value))
        except (TypeError, ValueError):
            logger.warning("[pricing] invalid %s value %r, ignored", key, value)
    return rates


def _normalize(name: Any) -> str:
    """Case/provider/tag-insensitive model key used for fallback matching."""
    text = str(name or "").strip().lower()
    if not text:
        return ""
    text = text.rsplit("/", 1)[-1]
    text = text.split(":", 1)[0]
    return text.strip()


def _read(path: Path) -> Dict[str, Any]:
    import yaml

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError("top-level YAML must be a mapping")

    models_raw = raw.get("models") or {}
    aliases_raw = raw.get("aliases") or {}
    if not isinstance(models_raw, dict):
        raise ValueError("'models' must be a mapping")
    if not isinstance(aliases_raw, dict):
        raise ValueError("'aliases' must be a mapping")

    models = {str(name): _coerce_rates(rates) for name, rates in models_raw.items()}
    aliases = {
        str(canonical): [str(alias) for alias in (values or [])]
        if isinstance(values, (list, tuple))
        else []
        for canonical, values in aliases_raw.items()
    }
    return {
        "path": str(path),
        "currency": str(raw.get("currency") or "USD").upper(),
        "models": models,
        "aliases": aliases,
        "default": _coerce_rates(raw.get("default") or {}),
    }


def load(force: bool = False) -> Optional[Dict[str, Any]]:
    """Return the parsed pricing document, reloading it when the file changes."""
    global _cache_path, _cache_mtime, _cache_data, _missing_logged

    path = pricing_file()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        if not _missing_logged:
            logger.info("[pricing] %s not found; using env cost fallback", path)
            _missing_logged = True
        return None

    if not force and _cache_data is not None and _cache_path == path and _cache_mtime == mtime:
        return _cache_data

    with _lock:
        if not force and _cache_data is not None and _cache_path == path and _cache_mtime == mtime:
            return _cache_data
        try:
            data = _read(path)
        except Exception:  # noqa: BLE001
            logger.warning("[pricing] cannot load %s; keeping previous values", path, exc_info=True)
            return _cache_data if _cache_path == path else None
        _cache_path, _cache_mtime, _cache_data = path, mtime, data
        _missing_logged = False
        logger.info("[pricing] loaded %d model(s) from %s (currency=%s)",
                    len(data["models"]), path, data["currency"])
        return data


def get_rates(model: Optional[str], kind: str = "generation") -> Optional[Dict[str, float]]:
    """Rates for a model, or None when the pricing file is not configured."""
    data = load()
    if data is None:
        return None

    models: Dict[str, Dict[str, float]] = data["models"]
    rates: Optional[Dict[str, float]] = None

    if model:
        if model in models:
            rates = models[model]
        else:
            normalized = _normalize(model)
            for name, candidate in models.items():
                if _normalize(name) == normalized:
                    rates = candidate
                    break
            if rates is None:
                for canonical, aliases in data["aliases"].items():
                    if any(_normalize(alias) == normalized for alias in aliases):
                        rates = models.get(canonical)
                        break

    if rates is None:
        rates = data["default"]
    return rates or {}


def currency() -> str:
    data = load()
    return str(data["currency"]) if data else "USD"


def main() -> int:
    data = load(force=True)
    if data is None:
        print(f"pricing file not found: {pricing_file()}")
        return 1
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
