"""
nbs_instructions.py — Domain knowledge for Nature-Based Solutions (NBS).

This module holds the NBS-specific logic that the chat_service calls. It does NOT
orchestrate the flow (that stays in chat_service): it only provides the building
blocks — recognizing NBS questions, recognizing NBS resources, mapping a problem
to the solutions that address it, cleaning/distilling the query, and extracting
the 'Problems' section that an NBS case study declares.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.config.config import PROBLEM_TO_NBS, _NBS_INTENT

def is_nbs_resource(entity: Dict[str, Any]) -> bool:
    """True if the entity is an NBS case study (marked by ':nbs:' in its id)."""
    entity_id = str(entity.get("_id", {}).get("id", "")).lower()
    return ":nbs:" in entity_id


def is_nbs_question(message: str) -> bool:
    m = str(message or "").lower()
    return any(w in m for w in _NBS_INTENT)


def expand_problem(message: str) -> List[str]:
    """Solution keywords relevant to the problem mentioned in the message."""
    m = message.lower()
    out: List[str] = []
    for key, terms in PROBLEM_TO_NBS.items():
        if key in m:
            for t in terms:
                if t not in out:
                    out.append(t)
    return out

_FILLER = (
    "hello", "hi", "i live in", "i am", "could you", "can you", "please",
    "i would like", "which", "what", "how can i", "how do i", "how to",
    "do you have", "there is", "there are", "affected by", "the effects of",
    "ciao", "vivo a", "vorrei", "quale", "quali", "come posso", "come faccio",
)


def distill_query(message: str) -> str:
    q = " " + str(message or "").lower() + " "
    for p in _FILLER:
        q = q.replace(" " + p + " ", " ")
    q = re.sub(r"[^a-z0-9àèéìòù\s-]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q or str(message or "")


def build_nbs_query(message: str) -> str:
    base = distill_query(message)
    extra = expand_problem(message)
    return (base + " " + " ".join(extra)).strip()


_SECTION_HEADERS = (
    "objective", "challenges", "problems", "potential impacts and benefits",
    "lessons learnt", "lessons learned", "area characterization",
)


def extract_problems_section(description: str, cap: int = 300) -> str:
    """Return the text under 'Problems:' up to the next section header."""
    if not description:
        return ""
    text = str(description).replace("\\n", "\n")   # handle literal \n if present
    low = text.lower()
    start = low.find("problems:")
    if start == -1:
        return ""
    start += len("problems:")
    end = len(text)
    for h in _SECTION_HEADERS:
        pos = low.find(h, start)
        if pos != -1:
            end = min(end, pos)
    section = text[start:end].strip(" \n-")
    section = re.sub(r"\s+", " ", section)
    return section[:cap]