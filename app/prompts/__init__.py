"""Prompt registry.

System prompts and LLM task prompts live in dedicated Markdown files instead of
Python string literals: they can be reviewed, versioned and changed without
touching the application logic. Use :func:`load_prompt` (or the helpers below)
so every prompt is read from a single, well-known place.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the stripped content of ``<name>.md`` from this directory."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=None)
def prompt_metadata(name: str) -> dict[str, str]:
    """Stable identifiers for tracing: file name plus a short content hash."""
    text = load_prompt(name)
    return {
        "prompt_name": name,
        "prompt_version": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12],
    }


def format_prompt(name: str, **kwargs: object) -> str:
    """Load a prompt and fill its ``{placeholders}``."""
    return load_prompt(name).format(**kwargs)
