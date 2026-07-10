from typing import Any

from app.chat.dto.models import SourceReference

CONTEXT_SEPARATOR = "\n\n---\n\n"


def assemble_context(
    documents: list[str],
    metadatas: list[dict[str, Any]],
) -> tuple[str, list[SourceReference]]:
    """Deduplicate retrieved chunks by dataset_id and assemble the LLM context.

    Returns a tuple of (context_text, sources) where sources is a list of
    SourceReference DTOs suitable for the ChatResponse contract (API_SPEC.md).
    """
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

        context_parts.append(document)
        sources.append(
            SourceReference(
                title=metadata.get("title") or dataset_id,
                datasetId=dataset_id,
                publisher=metadata.get("publisher"),
                url=metadata.get("url"),
            )
        )

    return CONTEXT_SEPARATOR.join(context_parts), sources
