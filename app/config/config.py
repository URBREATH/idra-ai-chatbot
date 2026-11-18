"""
config.py — Central configuration: NGSI field labels, format normalization,
and the system prompts used by the chatbot.

Language policy: the catalog data is in English, but the assistant must reply in
the user's language whenever it can be reliably detected, and default to English
otherwise. The resource content is translated into the user's language when shown.
"""
from typing import Dict, List

from app.prompts import load_prompt


FIELD_LABELS = {
    "title": "Title", "description": "Description", "datasetDescription": "Description", "keyword": "Keywords",
    "theme": "Theme", "publisher": "Publisher", "landingPage": "LandingPage",
    "format": "Format", "license": "License", "downloadURL": "URL",
    "accessUrl": "AccessURL", "modifiedDate": "Updated", "releaseDate": "Published",
    "rights": "Rights", "name": "Name", "address": "Address",
    "datasetDistribution": "DistributionIds",
    "distribution": "DistributionIds",
    "belongsToDataset": "BelongsToDataset",
    "isDistributionOf": "BelongsToDataset",
    "accessRights": "AccessRights",
    "issued": "Published",
    "modified": "Updated",
    # Idra MySQL source (app/mysql/repositories.py)
    "catalogue": "Catalogue",
    "country": "Country",
    "frequency": "Frequency",
    "version": "Version",
    "byteSize": "ByteSize",
}

FORMAT_CANON = {
    "csv": "CSV", "text/csv": "CSV",
    "geojson": "GeoJSON", "geo+json": "GeoJSON", "application/geo+json": "GeoJSON",
    "json": "JSON", "application/json": "JSON",
    "xml": "XML", "application/xml": "XML", "text/xml": "XML",
    "xlsx": "XLSX", "xls": "XLSX",
    "shp": "Shapefile", "shapefile": "Shapefile",
    "geotiff": "GeoTIFF", "tiff": "GeoTIFF", "tif": "GeoTIFF",
    "pdf": "PDF", "application/pdf": "PDF", "parquet": "Parquet", "wms": "WMS", "wfs": "WFS",
    # Seen in the Idra MySQL catalogue (EU file-type URIs, IANA media types, free text)
    "tsv": "TSV", "tab-separated-values": "TSV", "text/tab-separated-values": "TSV",
    "html": "HTML", "text/html": "HTML",
    "esri shapefile": "Shapefile", "esri shape": "Shapefile", "shapefile (shp)": "Shapefile",
    "zip": "ZIP", "application/zip": "ZIP",
    "rdf": "RDF", "rdfxml": "RDF", "rdf_xml": "RDF", "rdf+xml": "RDF", "application/rdf+xml": "RDF",
    "turtle": "Turtle", "text/turtle": "Turtle", "kml": "KML", "kmz": "KML",
    "gpkg": "GeoPackage", "geopackage": "GeoPackage", "geopackage+sqlite3": "GeoPackage",
    "ogc:wms": "WMS", "ogc:wfs": "WFS", "ogc:geojson": "GeoJSON",
    "ms_excel": "XLSX", "vnd.ms-excel": "XLSX",
    "vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    "vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
}


# ---------------------------------------------------------------------------
# Prompts live in app/prompts/*.md (see app/prompts/__init__.py). These
# constants are kept for backwards compatibility with the existing imports.
# ---------------------------------------------------------------------------

# Used for standard dataset/catalog queries. Injected as the system prompt;
# LINK_REMINDER is appended by build_prompt after the retrieval context, so
# the prompt file must NOT repeat it.
SYSTEM_INSTRUCTIONS = load_prompt("chat_system")

# Used when the query asks how to solve a problem with nature-based solutions.
# NBS_DECISION_REMINDER is appended at the end of the user block by build_prompt.
NBS_INSTRUCTIONS = load_prompt("chat_nbs_system")

# Appended by build_prompt after the retrieval context for non-NBS prompts.
# Small models follow rules they read last more reliably.
LINK_REMINDER = load_prompt("chat_link_reminder")

# Appended by build_prompt as the final instruction for NBS prompts.
# Word budget must match NBS_INSTRUCTIONS (150-200 words).
NBS_DECISION_REMINDER = load_prompt("chat_nbs_decision_reminder")

# Used when the vector search returns no results above the distance threshold.
NO_RESULT_INSTRUCTIONS = load_prompt("chat_no_result_system")

# Prepended to the system when results come from a relaxed distance threshold.
RELAXED_NOTICE = load_prompt("chat_relaxed_notice")

# Shared prompt used both by chat_service (LLM fallback) and tests.
LANGUAGE_DETECTION_PROMPT = load_prompt("chat_language_detection")

PROBLEM_TO_NBS: Dict[str, List[str]] = {
    "heat":        ["green roof", "urban trees", "tree canopy", "shading", "cooling",
                    "green facade", "urban park", "green space"],
    "caldo":       ["green roof", "urban trees", "shading", "cooling", "urban park"],
    "island":      ["green roof", "urban trees", "shading", "cooling", "green space"],
    "flood":       ["rain garden", "wetland", "permeable pavement", "retention pond",
                    "sustainable drainage", "stormwater", "bioswale"],
    "rain":        ["rain garden", "permeable pavement", "sustainable drainage", "stormwater"],
    "pioggia":     ["rain garden", "permeable pavement", "sustainable drainage", "stormwater"],
    "alluv":       ["wetland", "rain garden", "permeable pavement", "retention pond", "stormwater"],
    "drought":     ["water retention", "soil moisture", "rainwater harvesting", "green infrastructure"],
    "sicc":        ["water retention", "rainwater harvesting", "soil moisture"],
    "air quality": ["urban trees", "green belt", "vegetation barrier", "green wall"],
    "pollution":   ["urban trees", "green belt", "green wall"],
    "biodiversity":["habitat restoration", "green corridor", "urban meadow", "wetland", "biodiversity"],
    "erosion":     ["vegetated slope", "bioengineering", "riverbank restoration", "sand dune"],
    # "coast" was too broad (fired for "I live on the coast"); use the specific compound key.
    "coastal erosion": ["sand dune", "salt marsh", "coastal vegetation", "riverbank restoration"],
}

_NBS_INTENT = (
    "nbs", "nature-based", "nature based", "solution", "solve", "problem",
    "how can i", "how do i", "how to", "mitigate", "mitigation", "adapt",
    "adaptation", "resilience", "cope with", "deal with", "affected by",
    "suggest", "recommend",

    "soluzione", "risolvere", "problema", "come posso", "come faccio",
    "mitigare", "adattamento", "resilienza", "suggerisci", "consigli",
)

_REFERENCE_MARKERS = (
    "those", "these", "that one", "that dataset", "that solution", "that nbs",
    "the first", "the second", "the third", "the last",
    "of them", "of these", "of those", "only the", "just the", "the previous",
    "earlier", "above", "it ", " its ",
    # Italian
    "quelli", "quello", "questi", "quelle", "quella", "il primo", "il secondo",
    "il terzo", "l'ultimo", "solo i", "solo quelli", "di quelli", "di questi",
    "il precedente",
)

_REACTION_MARKERS = (
    "i can't", "i cannot", "cannot", "can't", "can not", "not possible",
    "instead of", "other than", "rather than", "alternative", "something else",
    "won't work", "not an option", "not feasible", "is there another",
    "what else", "any other", "don't want", "do not want",
    # Italian (both accented and ASCII-safe variants for robustness)
    "non posso", "non è possibile", "non e possibile", "invece di", "un'alternativa",
    "alternativa", "qualcos'altro", "qualcosa d'altro", "non va bene", "non funziona",
    "non voglio", "ce n'è un'altra", "ce ne sono altre", "qualcos altro",
)

# Used by chat_followup.rewrite_query to turn a follow-up message into a
# standalone English search query for ChromaDB.
_REWRITE_PROMPT = load_prompt("chat_query_rewrite")
REWRITE_PROMPT = _REWRITE_PROMPT
