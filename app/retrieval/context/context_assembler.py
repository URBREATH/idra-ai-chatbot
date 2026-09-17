from typing import Any

from app.chat.dto.models import SourceReference

CONTEXT_SEPARATOR = "\n\n---\n\n"


def assemble_context(
    documents: list[str],
    metadatas: list[dict[str, Any]],
) -> tuple[str, list[SourceReference]]:
    """Deduplicate retrieved chunks by dataset_id and assemble the LLM context.
    Il contesto per ogni risorsa unisce il testo semantico (document) con i campi
    strutturati presi dai METADATI (title, description, format, license, url),
    cosi' il modello puo' citarli senza inventarli."""
    if not documents:
        return "", []
    seen_dataset_ids: set[str] = set()
    context_parts: list[str] = []
    sources: list[SourceReference] = []
    for document, metadata in zip(documents, metadatas):
        if not metadata:
            continue
        dataset_id = metadata.get("dataset_id")
        if not dataset_id:
            continue
        if dataset_id in seen_dataset_ids:
            continue
        seen_dataset_ids.add(dataset_id)

        # Blocco di contesto ESPLICITO: campi dai metadati + testo semantico.
        title = metadata.get("title") or dataset_id
        block = "\n".join(filter(None, [
            f"Title: {title}",
            f"Description: {metadata.get('description')}" if metadata.get("description") else None,
            f"Format: {metadata.get('format')}" if metadata.get("format") else None,
            f"License: {metadata.get('license')}" if metadata.get("license") else None,
            f"Publisher: {metadata.get('publisher')}" if metadata.get("publisher") else None,
            f"Link: {metadata.get('url')}" if metadata.get("url") else None,
        ]))
        context_parts.append(block)

        sources.append(
            SourceReference(
                title=title,
                datasetId=dataset_id,
                publisher=metadata.get("publisher"),
                url=metadata.get("url"),
            )
        )
    return CONTEXT_SEPARATOR.join(context_parts), sources
