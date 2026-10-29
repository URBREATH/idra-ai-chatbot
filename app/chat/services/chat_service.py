import asyncio
import json
import os
import re                                    # [NEW] per estrarre i link dalle risposte
import unicodedata                           # [NEW] confronto dei titoli senza accenti
import uuid
import logging

from dotenv import load_dotenv
from fastapi import HTTPException
from lingua import LanguageDetectorBuilder

from app.chat.dto.models import ChatResponse
from app.chat.services.chat_followup import is_followup, rewrite_query
from app.retrieval.embeddings.query_embedder import embed_query
from app.retrieval.vector_search.searcher import vector_search, DEFAULT_N_RESULTS
from app.retrieval.reranker.reranker import rerank
from app.retrieval.context.context_assembler import assemble_context
from app.ollama import client as ollama_client
from app.conversation import services as conversation_services
from app.config.config import (
    SYSTEM_INSTRUCTIONS, NO_RESULT_INSTRUCTIONS, RELAXED_NOTICE, NBS_INSTRUCTIONS,
    PROBLEM_TO_NBS, FORMAT_CANON, LINK_REMINDER, NBS_DECISION_REMINDER,
    _NBS_INTENT, _REFERENCE_MARKERS, _REACTION_MARKERS,
)
from app.instructions.nbs_instructions import is_nbs_question

load_dotenv()

logger = logging.getLogger(__name__)

TOP_K = int(os.getenv("TOP_K", 10))
DISTANCE_THRESHOLD = float(os.getenv("DISTANCE_THRESHOLD", "0.55"))
DISTANCE_THRESHOLD_STEP = float(os.getenv("DISTANCE_THRESHOLD_STEP", "0.10"))
DISTANCE_THRESHOLD_MAX = float(os.getenv("DISTANCE_THRESHOLD_MAX", "0.75"))
LOG_TOP_FOUND = int(os.getenv("LOG_TOP_FOUND", 10))
MAX_N_RESULTS = int(os.getenv("MAX_N_RESULTS", 100))
NBS_QUERY_EXPANSION = os.getenv("NBS_QUERY_EXPANSION", "true").lower() == "true"   # [NEW]
# Limiti per non superare la finestra di contesto di Ollama
MAX_RESOURCES = int(os.getenv("MAX_RESOURCES", 6))            # risorse distinte passate al modello
MAX_DATASETS = int(os.getenv("MAX_DATASETS", 8))              # limite separato per i dataset
MAX_DOC_CHARS = int(os.getenv("MAX_DOC_CHARS", 1200))         # caratteri per risorsa
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", 3000)) # caratteri di cronologia

LANGUAGE_CONFIDENCE_THRESHOLD = float(os.getenv("LANGUAGE_CONFIDENCE_THRESHOLD", "0.70"))
LANGUAGE_CONFIDENCE_MARGIN = float(os.getenv("LANGUAGE_CONFIDENCE_MARGIN", "0.20"))
LANGUAGE_DETECTION_TIMEOUT = float(os.getenv("LANGUAGE_DETECTION_TIMEOUT", "10.0"))

_LANGUAGE_DETECTOR = LanguageDetectorBuilder.from_all_languages().build()


def _log_found_resources(documents, metadatas, distances) -> None:
    n_show = min(LOG_TOP_FOUND, len(documents))
    logger.debug("Prime %d risorse trovate (soglia base=%.3f, tetto=%.3f):",
                 n_show, DISTANCE_THRESHOLD, DISTANCE_THRESHOLD_MAX)
    for rank in range(n_show):
        meta = metadatas[rank] or {}
        dist = distances[rank]
        label = meta.get("title") or meta.get("dataset_id") or "(senza titolo)"
        entro = "OK " if dist <= DISTANCE_THRESHOLD else "  -"
        logger.debug("  #%2d  dist=%.4f  [%s]  %s", rank + 1, dist, entro, label)


# ---------------------------------------------------------------------------
# [NEW] Controllo dei link: un link e' valido solo se compare nel testo
# che il modello ha ricevuto (contesto di Chroma e/o cronologia della chat).
# ---------------------------------------------------------------------------
URL_RE = re.compile(r"https?://[^\s)\]>\"'<]+")

NO_ALTERNATIVE_MESSAGE = (
    "I couldn't find other resources in the catalog for this request. "
    "You could try rephrasing it or relaxing a constraint."
)


def _urls(text: str) -> set:
    """Tutti i link di un testo, senza punteggiatura o slash finali."""
    return {u.rstrip(".,;:!?/") for u in URL_RE.findall(text or "")}


def invented_links(answer: str, allowed_text: str) -> list:
    """Link scritti dal modello che NON erano nel testo che ha ricevuto."""
    return sorted(_urls(answer) - _urls(allowed_text))


def _resource_url(meta: dict) -> str:                           # [NEW]
    """Link della risorsa: 'url' e, se manca, la landing page."""
    meta = meta or {}
    return str(meta.get("url") or meta.get("landingPage") or meta.get("landing_page") or "")


def list_resources(metadatas: list,
                   header: str = "These are the resources I found in the catalog:") -> str:   # [CHANGED]
    """Risposta sicura costruita solo con le risorse recuperate, sempre con il link."""
    lines, seen = [], set()
    for meta in metadatas:
        meta = meta or {}
        title = meta.get("title") or meta.get("dataset_id") or "Untitled"
        url = _resource_url(meta)
        if (url or title) in seen:          # piu' chunk della stessa risorsa
            continue
        seen.add(url or title)
        lines.append(f"- {title}: {url}" if url else f"- {title}")
    if not lines:
        return NO_ALTERNATIVE_MESSAGE
    return header + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# [NEW] Garanzia dei link: il codice controlla quali risorse la risposta cita
# (per link o per titolo) e aggiunge i link mancanti. Se la risposta non cita
# nessuna risorsa del catalogo, viene sostituita dalle risorse piu' vicine.
# ---------------------------------------------------------------------------
CLOSEST_HEADER = ("I couldn't match a specific resource to your request, but these are the "
                  "closest ones in the catalog:")
NO_MATCH_NOTICE = ("I didn't find any resource in the catalog related to your request. The "
                   "following suggestions are general advice, not based on case studies documented "
                   "in the catalog:\n\n")                                 # [NEW]

def _ascii_words(text: str) -> set:
    """Parole di almeno 4 caratteri, minuscole e senza accenti."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]{4,}", t))


_STOP = {"that", "this", "with", "from", "have", "they", "their", "which", "would", "could",
         "there", "these", "those", "into", "along", "were", "your", "what", "when", "where",
         "whenever", "about", "also", "some", "other", "more", "than", "then", "them"}


def best_excerpt(text: str, query: str, limit: int) -> str:                 # [NEW]
    """Estratto della descrizione entro `limit` caratteri: l'inizio (di che progetto
    si tratta) piu' i paragrafi con piu' parole della domanda, nell'ordine originale.
    Se nessun paragrafo e' pertinente, tiene semplicemente l'inizio."""
    text = str(text or "").replace("\\n", "\n")
    if len(text) <= limit:
        return text
    head = text[: limit // 3]
    qwords = _ascii_words(query) - _STOP
    paragraphs, pos = [], 0
    for p in text.split("\n"):
        if p.strip() and pos >= len(head):
            paragraphs.append((pos, p.strip(), len((_ascii_words(p) - _STOP) & qwords)))
        pos += len(p) + 1
    chosen, used = [], len(head)
    for start, p, score in sorted(paragraphs, key=lambda x: -x[2]):
        if score == 0:
            break
        if used + len(p) + 1 <= limit:
            chosen.append((start, p))
            used += len(p) + 1
    if not chosen:
        return text[:limit]
    return head.rstrip() + " [...]\n" + "\n".join(p for _, p in sorted(chosen))


def _is_mentioned(resource: dict, answer_words: set, answer_urls: set) -> bool:
    """Citata se compare il suo link, o almeno il 60% delle parole del suo titolo."""
    url = _resource_url(resource).rstrip(".,;:!?/")
    if url and url in answer_urls:
        return True
    title_words = _ascii_words(resource.get("title"))
    return bool(title_words) and len(title_words & answer_words) / len(title_words) >= 0.6


def ensure_links(answer: str, resources: list, fallback: list | None = None) -> str:
    """Aggiunge il link a ogni risorsa citata che ne e' priva.
    Se nessuna risorsa e' citata e c'e' un fallback, restituisce le risorse piu' vicine."""
    answer_urls, answer_words = _urls(answer), _ascii_words(answer)
    mentioned, seen = [], set()
    for r in resources:
        r = r or {}
        key = r.get("dataset_id") or r.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        if _is_mentioned(r, answer_words, answer_urls):
            mentioned.append(r)
    if not mentioned:
        if fallback:
            logger.warning("Answer cites no catalog resource: replaced with the closest resources")
            return list_resources(fallback, header=CLOSEST_HEADER)
        return answer
    missing = [r for r in mentioned
               if _resource_url(r) and _resource_url(r).rstrip(".,;:!?/") not in answer_urls]
    if not missing:
        return answer
    logger.debug("Links added by code: %s", [r.get("title") for r in missing])
    lines = [f"- {r.get('title') or 'Untitled'}: {_resource_url(r)}" for r in missing]
    return answer.rstrip() + "\n\nLinks:\n" + "\n".join(lines)


# is_nbs_question is imported from app.instructions.nbs_instructions


_DATA_WORDS = {"dataset", "datasets", "data", "dati"}


def asks_for_datasets(text: str) -> bool:
    """True se il testo chiede esplicitamente dataset/dati e non nomina le NBS."""
    t = str(text or "").lower()
    if "nbs" in re.findall(r"[a-z]+", t) or "nature-based" in t or "nature based" in t:
        return False
    return bool(set(re.findall(r"[a-zàèéìòù]+", t)) & _DATA_WORDS)


def problem_terms(text: str) -> list:
    """Termini di soluzione per i problemi citati nel testo (da PROBLEM_TO_NBS).
    La chiave deve trovarsi a INIZIO parola: 'rain' non scatta in 'drainage'."""
    t = str(text or "").lower()
    out = []
    for key, terms in PROBLEM_TO_NBS.items():
        if re.search(r"\b" + re.escape(key), t):
            for term in terms:
                if term not in out:
                    out.append(term)
    return out

_FILTER_WORDS = {"only", "solo", "soltanto"}


def requested_format(message: str) -> str | None:
    """Formato citato nel messaggio, normalizzato con FORMAT_CANON (es. 'csv' -> 'CSV')."""
    for word in re.findall(r"[a-z0-9]+", str(message or "").lower()):
        if word in FORMAT_CANON:
            return FORMAT_CANON[word]
    return None


def refers_to_previous(message: str) -> bool:
    """True se il messaggio si riferisce ai risultati precedenti ('these', 'only', 'quelli'...)."""
    words = set(re.findall(r"[a-zàèéìòù]+", str(message or "").lower()))
    return is_followup(message) or bool(words & _FILTER_WORDS)


def _formats_of(resource: dict) -> list:
    """Formati di una risorsa come lista, sia che siano salvati come lista sia come stringa."""
    formats = resource.get("format") or []
    if isinstance(formats, str):
        formats = formats.split(",")
    return [str(f).strip() for f in formats if str(f).strip()]


def compact_resources(metadatas: list, answer: str) -> list:
    """Risorse da salvare con la risposta: una per dataset, solo i campi utili.
    Se la risposta contiene link, tiene solo le risorse effettivamente mostrate."""
    out, seen = [], set()
    for meta in metadatas:
        meta = meta or {}
        key = meta.get("dataset_id") or meta.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            "dataset_id": meta.get("dataset_id"),
            "title": meta.get("title"),
            "url": _resource_url(meta) or None,
            "format": _formats_of(meta),
            "is_nbs": bool(meta.get("is_nbs")),
        })
    shown_urls = _urls(answer)
    shown = [r for r in out if r["url"] and str(r["url"]).rstrip(".,;:!?/") in shown_urls]
    return shown or out


def filter_by_format(resources: list, fmt: str) -> str:
    """Risposta deterministica: le risorse precedenti disponibili nel formato richiesto."""
    if not any(_formats_of(r) for r in resources):
        return ("The resources in my previous answer don't include format information, "
                f"so I can't tell which ones are available in {fmt}.")
    kept = [r for r in resources if fmt.upper() in [f.upper() for f in _formats_of(r)]]
    if not kept:
        return f"None of the resources in my previous answer is available in {fmt}."
    lines = []
    for r in kept:
        link = f" - {r['url']}" if r.get("url") else ""
        lines.append(f"- {r.get('title') or 'Untitled'} ({', '.join(_formats_of(r))}){link}")
    return f"From my previous answer, these resources are available in {fmt}:\n" + "\n".join(lines)


def build_prompt(
    message: str,
    retrieval_context: str,
    conversation_context: str | None = None,
    relaxed: bool = False,
    system: str = SYSTEM_INSTRUCTIONS,
    lang_code: str | None = None,
) -> tuple[str, str]:
    """Build the system prompt and the user prompt.

    Returns (system_prompt, user_prompt) to inject into the LLM chat completion
    under the respective 'system' and 'user' roles, avoiding redundant token duplication.
    """
    retrieval_block = retrieval_context.strip() if retrieval_context and retrieval_context.strip() else "(no context available)"
    system_parts = []
    if lang_code:
        system_parts.append(_language_directive(lang_code).strip())
    system_parts.append(str(system).strip())
    if relaxed:
        system_parts.append(RELAXED_NOTICE.strip())
    system_prompt = "\n\n".join(system_parts)

    prompt_parts = []
    if conversation_context:
        prompt_parts.append("Previous conversation:")
        prompt_parts.append(conversation_context)
        prompt_parts.append("")
    prompt_parts.append("Context (metadata of the retrieved resources):")
    prompt_parts.append(retrieval_block)
    prompt_parts.append("")
    if system.strip().startswith(NBS_INSTRUCTIONS.strip().split("\n")[0]):
        prompt_parts.append(f"Question: {message}")
        prompt_parts.append("")
        prompt_parts.append(NBS_DECISION_REMINDER)
    else:
        prompt_parts.append(LINK_REMINDER)
        prompt_parts.append("")
        prompt_parts.append(f"Question: {message}")
    prompt_parts.append("")
    prompt_parts.append("Answer:")
    return system_prompt, "\n".join(prompt_parts)






_LANGUAGE_DETECTION_PROMPT = (
    "Identify the language of the user message below. Return ONLY its lowercase "
    "ISO 639-1 two-letter code, with no punctuation or explanation. Detect the "
    "language from the message itself, not from the topic or named entities.\n\n"
    "User message as a JSON string:\n{message}\n\nLanguage code:"
)


def _detect_language_locally(text: str) -> tuple[str | None, float, float]:
    """Return a reliable local detection plus confidence and candidate margin."""
    confidence_values = _LANGUAGE_DETECTOR.compute_language_confidence_values(text)
    if not confidence_values:
        return None, 0.0, 0.0

    best = confidence_values[0]
    second_confidence = confidence_values[1].value if len(confidence_values) > 1 else 0.0
    margin = best.value - second_confidence
    iso_code = best.language.iso_code_639_1
    code = iso_code.name.lower() if iso_code else None
    logger.debug(
        "Local language detection: code=%s confidence=%.3f margin=%.3f",
        code, best.value, margin,
    )
    if best.value >= LANGUAGE_CONFIDENCE_THRESHOLD or margin >= LANGUAGE_CONFIDENCE_MARGIN:
        return code, best.value, margin
    return None, best.value, margin


async def _detect_language_with_llm(text: str, model: str | None = None) -> str | None:
    """Ask the LLM for the message language as an ISO 639-1 code."""
    try:
        kwargs = {"temperature": 0.0}
        if model:
            kwargs["model"] = model
        raw = await ollama_client.generate_completion(
            _LANGUAGE_DETECTION_PROMPT.format(
                message=json.dumps(text, ensure_ascii=False),
            ),
            **kwargs,
        )
        code = raw.strip().lower()
        if re.fullmatch(r"[a-z]{2}", code):
            return code
        logger.debug("Language detector returned an invalid code: %r", raw)
    except Exception as e:
        logger.debug("Could not detect query language via LLM: %s", e)
    return None


async def _detect_language(text: str, model: str | None = None) -> str | None:
    if not any(character.isalpha() for character in text):
        logger.debug("Skipping language detection for input without letters")
        return None

    try:
        code, confidence, margin = _detect_language_locally(text)
    except (RuntimeError, UnicodeError, ValueError) as e:
        logger.debug("Local language detection failed: %s", e)
        code, confidence, margin = None, 0.0, 0.0
    if code:
        return code
    logger.debug(
        "Local language detection is ambiguous (confidence=%.3f, margin=%.3f); using LLM fallback",
        confidence, margin,
    )
    try:
        return await asyncio.wait_for(
            _detect_language_with_llm(text, model=model),
            timeout=LANGUAGE_DETECTION_TIMEOUT,
        )
    except TimeoutError:
        logger.debug(
            "Language detection LLM timed out after %.1f seconds",
            LANGUAGE_DETECTION_TIMEOUT,
        )
        return None


def _language_directive(lang_code: str | None) -> str:
    if not lang_code:
        return ""
    return (
        f'The user message language was identified as ISO 639-1 code "{lang_code}". '
        "You MUST write the entire answer exclusively in that language. Ignore the "
        "language of the context and conversation history.\n\n"
    )


def _build_no_result_prompt(
    message: str,
    conversation_context: str = "",
    lang_code: str | None = None,
) -> "tuple[str, str]":
    system = (_language_directive(lang_code) + NO_RESULT_INSTRUCTIONS).strip()
    user_parts: list[str] = []
    if conversation_context:
        user_parts.append("Previous conversation:")
        user_parts.append(conversation_context)
        user_parts.append("")
    user_parts.append(f"User's question: {message}")
    user_parts.append("")
    user_parts.append(
        "IMPORTANT: If the user's question refers to items already listed in the previous "
        "conversation (words like 'these', 'those', 'the second one'), answer using ONLY those "
        "items, with their titles and links copied exactly as written there. If the user asks "
        "for OTHER or NEW resources, say that this search did not find other matching "
        "resources, and give the suggestions to broaden or rephrase the search. Never write "
        "a title or a link that does not appear in the previous conversation."
    )
    user_parts.append("")
    user_parts.append("Answer:")
    return system, "\n".join(user_parts)


async def generate_answer(
        message: str,
        conversation_id: str | None,
        tenant_id: str,
        user_id: str | None = None,
        model: str | None = None,
) -> "ChatResponse":
    conversation_id = conversation_id or str(uuid.uuid4())
    logger.debug("MEMORIA - conversation_id=%s | user_id=%s", conversation_id, user_id)

    if model:
        available = await ollama_client.list_models()
        if model not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model}' not found. Valid models are: {available}",
            )
    effective_model = model or os.getenv("OLLAMA_LLM_MODEL", "mistral-nemo")
    logger.debug("Using LLM model for chat workflow: %s", effective_model)

    conversation_context = ""
    if user_id:
        try:
            conversation_context = await conversation_services.get_context_for_llm(
                conversation_id=conversation_id, user_id=user_id,tenant_id=tenant_id, limit=10,
            )
        except Exception as e:
            logger.debug(f"Could not load conversation context: {e}")
            conversation_context = ""

    lang_code = await _detect_language(message, model=model)
    logger.debug("Detected language for query: %s", lang_code)

    if user_id:
        try:
            await conversation_services.append_user_message(
                conversation_id=conversation_id, tenant_id=tenant_id,
                user_id=user_id, message_content=message,
            )
        except Exception as e:
            logger.debug(f"Could not persist user message: {e}")

    async def _respond(answer_text: str, sources_list: list,
                       resources: list | None = None) -> "ChatResponse":
        if user_id:
            try:
                await conversation_services.append_assistant_message(
                    conversation_id=conversation_id, tenant_id=tenant_id,
                    user_id=user_id, message_content=answer_text,
                    sources=resources,
                )
            except Exception as e:
                logger.debug(f"Could not persist assistant message: {e}")
        return ChatResponse(answer=answer_text, sources=sources_list, conversationId=conversation_id)

    async def _previous_sources() -> list:
        """Risorse salvate con l'ultima risposta che ne aveva (per i link nei follow-up)."""
        if not (user_id and conversation_context):
            return []
        try:
            return await conversation_services.get_last_sources(
                conversation_id=conversation_id, tenant_id=tenant_id, user_id=user_id,
            ) or []
        except Exception as e:
            logger.debug(f"Could not load previous sources: {e}")
            return []

    async def _no_result() -> "ChatResponse":
        system_nr, user_nr = _build_no_result_prompt(message, conversation_context, lang_code=lang_code)
        try:
            if model:
                answer = await ollama_client.generate_completion(user_nr, model=model, temperature=0.0, system=system_nr)
            else:
                answer = await ollama_client.generate_completion(user_nr, temperature=0.0, system=system_nr)
        except Exception as e:
            logger.debug(f"No-result generation failed, using fallback: {e}")
            answer = NO_ALTERNATIVE_MESSAGE

        bad = invented_links(answer, conversation_context)
        if bad:
            logger.warning("Invented links removed (no-result path): %s", bad)
            answer = NO_ALTERNATIVE_MESSAGE
        answer = ensure_links(answer, await _previous_sources())
        return await _respond(answer, [])

    fmt = requested_format(message)
    if user_id and conversation_context and fmt and refers_to_previous(message):
        previous = await _previous_sources()
        if previous:
            logger.debug("FORMAT FILTER %s on %d previous resources", fmt, len(previous))
            return await _respond(filter_by_format(previous, fmt), [])

    # Rewrite the query into a clean English search string.
    # When there is conversation history, the rewrite also resolves references and
    # positive-rephrases rejections. Without history, it still normalises the language
    # so that non-English queries embed closer to the English catalog content.
    search_text = await rewrite_query(message, conversation_context, model=model)

    # NBS guard: activate NBS mode only when the message asks how to SOLVE a problem
    # and does NOT explicitly request data/datasets from either the rewritten or the
    # original message (prevents "recommend me a dataset" from entering NBS mode).
    data_request = asks_for_datasets(search_text) or asks_for_datasets(message)   # [CHANGED]
    nbs = (is_nbs_question(message) or is_nbs_question(search_text)) and not data_request   # [CHANGED]

    m = " " + message.lower() + " "
    if conversation_context and any(w in m for w in _REFERENCE_MARKERS) \
            and not any(w in m for w in _REACTION_MARKERS):
        previous_titles = [s.get("title") for s in await _previous_sources() if s.get("title")]
        if previous_titles:
            search_text = search_text + " " + " ".join(dict.fromkeys(previous_titles))
            logger.debug("Reference to previous results: query + %s", list(dict.fromkeys(previous_titles)))
    logger.debug("NBS intent: message=%s search=%s datasets=%s -> %s",
                 is_nbs_question(message), is_nbs_question(search_text), data_request, nbs)

    if nbs and NBS_QUERY_EXPANSION:
        extra = problem_terms(message + " " + search_text)
        if extra:
            search_text = search_text + " " + " ".join(extra)
            logger.debug("NBS query expanded with: %s", extra)

    query_embedding = await embed_query(search_text)
    if not query_embedding:
        logger.debug("Empty query embedding; no-result workflow")
        return await _no_result()

    where = {"is_nbs": True} if nbs else None
    logger.debug("WHERE passato alla ricerca: %s", where)
    raw_results = vector_search(tenant_id, query_embedding, where=where)
    documents = (raw_results.get("documents") or [[]])[0]
    metadatas = (raw_results.get("metadatas") or [[]])[0]
    distances = (raw_results.get("distances") or [[]])[0]

    logger.debug("distances for query %r: %s", message, distances)
    if documents:
        _log_found_resources(documents, metadatas, distances)

    if not documents:
        logger.debug("Nessun candidato per tenant %s; no-result workflow", tenant_id)
        return await _no_result()

    threshold = DISTANCE_THRESHOLD
    kept = [i for i, d in enumerate(distances) if d <= threshold]
    relaxed = False
    while not kept and threshold < DISTANCE_THRESHOLD_MAX:
        threshold = round(min(threshold + DISTANCE_THRESHOLD_STEP, DISTANCE_THRESHOLD_MAX), 4)
        kept = [i for i, d in enumerate(distances) if d <= threshold]
        if kept:
            relaxed = True
            logger.debug("Nessun risultato sotto la soglia base %.3f; allargata a %.3f -> %d risultati",
                         DISTANCE_THRESHOLD, threshold, len(kept))

    if not kept:
        logger.debug("Nessun risultato entro la soglia massima %.3f; no-result", DISTANCE_THRESHOLD_MAX)
        return await _no_result()

    documents = [documents[i] for i in kept]
    metadatas = [metadatas[i] for i in kept]
    distances = [distances[i] for i in kept]

    top_indices = rerank(message, documents, metadatas, distances, top_k=TOP_K)
    if not top_indices:
        top_indices = list(range(len(documents)))[:TOP_K]

    seen, unique_indices = set(), []
    for i in top_indices:
        meta = metadatas[i] or {}
        key = meta.get("dataset_id") or meta.get("title") or f"chunk-{i}"
        if key not in seen:
            seen.add(key)
            unique_indices.append(i)

    if any(w in " " + message.lower() + " " for w in _REACTION_MARKERS):
        rejected = {r.get("dataset_id") for r in await _previous_sources() if r.get("dataset_id")}
        unique_indices = [i for i in unique_indices
                          if (metadatas[i] or {}).get("dataset_id") not in rejected]
        if not unique_indices:
            return await _no_result()

    top_indices = unique_indices[:MAX_RESOURCES if nbs else MAX_DATASETS]


    top_documents = [documents[i] for i in top_indices]
    top_metadatas = [metadatas[i] for i in top_indices]

    logger.debug("Risorse passate all'LLM (dopo soglia e rerank): %s",
                 [(m or {}).get("title") or (m or {}).get("dataset_id") for m in top_metadatas])

    top_documents = [str(d)[:MAX_DOC_CHARS] for d in top_documents]

    excerpt_query = message + " " + search_text
    context_metadatas = [
        {k: (best_excerpt(v, excerpt_query, MAX_DOC_CHARS) if isinstance(v, str) else v)
         for k, v in (m or {}).items()}
        for m in top_metadatas
    ]
    context, sources = assemble_context(top_documents, context_metadatas)   # [CHANGED]
    logger.debug("CONTEXT PASSATO AL MODELLO:\n%s", context[:2000])

    system_base = NBS_INSTRUCTIONS if nbs else SYSTEM_INSTRUCTIONS
    logger.debug("PROMPT SCELTO: %s", "NBS" if nbs else "GENERIC")
    system_prompt, user_prompt = build_prompt(
        message, context, conversation_context, relaxed=relaxed, system=str(system_base), lang_code=lang_code
    )
    logger.debug("PROMPT: %d caratteri (~%d token stimati)", len(user_prompt), len(user_prompt) // 4)

    if model:
        answer = await ollama_client.generate_completion(user_prompt, model=model, temperature=0.0, system=system_prompt)
    else:
        answer = await ollama_client.generate_completion(user_prompt, temperature=0.0, system=system_prompt)

    allowed_text = "\n".join([
        context or "",
        conversation_context or "",
        " ".join(str((m or {}).get("url") or "") for m in top_metadatas),
    ])

    no_relevant = False
    if nbs:
        lines = answer.strip().split("\n")
        first = lines[0].strip().strip("*").strip() if lines else ""
        if first.upper().startswith("RELEVANT"):
            decision = first.split(":", 1)[1].strip(" *") if ":" in first else ""
            answer = "\n".join(lines[1:]).strip()
            no_relevant = (not decision) or decision.upper().startswith("NONE")
            logger.debug("NBS relevance decision: %r", decision)

    current = compact_resources(top_metadatas, "")
    previous = await _previous_sources() if conversation_context else []

    cited = any(_is_mentioned(r, _ascii_words(answer), _urls(answer)) for r in current + previous)
    if nbs and (no_relevant or not cited):                              # [CHANGED]
        logger.warning("No relevant catalog resource: general advice with notice")
        allowed = set() if no_relevant else _urls(allowed_text)
        answer = URL_RE.sub(lambda m: m.group(0) if m.group(0).rstrip(".,;:!?/") in allowed else "", answer)
        answer = re.sub(r"(?im)^\s*links?\s*:\s*$\n?", "", answer)
        answer = re.sub(r"\s*\(\s*\)", "", answer)
        return await _respond(NO_MATCH_NOTICE + answer.strip(), [], resources=[])

    bad = invented_links(answer, allowed_text)
    if bad:
        logger.warning("Invented links removed: %s", bad)
        answer = list_resources(top_metadatas, header=CLOSEST_HEADER)

    if nbs and any(w in answer.lower() for w in ("potentially help", "main objective is not",
                                                  "potrebbe potenzialmente aiutare", "obiettivo principale non")):
        logger.warning("Forced NBS relevance: answer replaced")
        answer = list_resources(current, header=CLOSEST_HEADER)
    answer = ensure_links(answer, current + previous, fallback=current)

    return await _respond(answer, sources,
                          resources=compact_resources(top_metadatas, answer))   # [CHANGED]