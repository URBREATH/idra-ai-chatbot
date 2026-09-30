"""
config.py — Central configuration: NGSI field labels, format normalization,
and the system prompts used by the chatbot.

Language policy: the catalog data is in English, but the assistant must reply in
the user's language whenever it can be reliably detected, and default to English
otherwise. The resource content is translated into the user's language when shown.
"""

# ---------------------------------------------------------------------------
# NGSI attribute name -> clean label (used by extract_attrs in payload_builder)
# ---------------------------------------------------------------------------
FIELD_LABELS = {
    "title": "Title", "description": "Description", "datasetDescription": "Description", "keyword": "Keywords",
    "theme": "Theme", "publisher": "Publisher", "landingPage": "LandingPage",
    "format": "Format", "license": "License", "downloadURL": "URL",
    "accessUrl": "AccessURL", "modifiedDate": "Updated", "releaseDate": "Published",
    "rights": "Rights", "name": "Name", "address": "Address",
    "datasetDistribution": "DistributionIds",   # ids of the distributions listed by the Dataset
    "distribution": "DistributionIds",           # name variant
    "belongsToDataset": "BelongsToDataset",       # id of the Dataset, when the Distribution points to it
    "isDistributionOf": "BelongsToDataset",       # name variant
}

# ---------------------------------------------------------------------------
# Raw format (media-type, code, IRI) -> clean label (used by clean_format)
# ---------------------------------------------------------------------------
FORMAT_CANON = {
    "csv": "CSV", "text/csv": "CSV",
    "geojson": "GeoJSON", "geo+json": "GeoJSON", "application/geo+json": "GeoJSON",
    "json": "JSON", "application/json": "JSON",
    "xml": "XML", "application/xml": "XML", "text/xml": "XML",
    "xlsx": "XLSX", "xls": "XLSX",
    "shp": "Shapefile", "shapefile": "Shapefile",
    "geotiff": "GeoTIFF", "tiff": "GeoTIFF", "tif": "GeoTIFF",
    "pdf": "PDF", "application/pdf": "PDF", "parquet": "Parquet", "wms": "WMS", "wfs": "WFS",
}

# ---------------------------------------------------------------------------
# System prompt: normal answer (one or more matching resources found)
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTIONS = (
    "You are an assistant for a European open data catalog. Each resource in the context has "
    "metadata (title, description, theme, keywords, format, license, link). Use ONLY the context; "
    "never invent anything.\n"
    "Rules:\n"
    "1. LANGUAGE: detect the language of the user's question and reply in that language whenever you "
    "can determine it reliably; otherwise default to English. Ignore the language of the resources, "
    "and translate their content into the user's language when presenting it.\n"
    "2. COMPLETENESS: present EVERY resource, one list item each. N resources in the context = N items. "
    "Never drop or merge resources.\n"
    "3. MISSING FIELDS: show only fields present in the context; omit absent ones (no 'not specified', "
    "no link if there is none, no hints about where to find it).\n"
    "4. ANSWER FORMAT: one short opening sentence on what you found, then one item per resource (title, "
    "brief description, and any present format/license/link), then 2-4 concrete next steps.\n"
    "5. ADVISORY QUESTIONS: ground the answer in the descriptions/themes/keywords of the resources; "
    "if they don't support an answer, say so.\n"
    "6. RESOURCE TYPES: a 'Dataset' describes the data; a 'Distribution' is a downloadable file of a "
    "dataset (with its format, license and download link). When the user asks about datasets or "
    "solutions, present datasets and mention their available formats. When the user asks for a file "
    "or a specific format, present the matching distribution(s) with the download link.\n"
    "7. FORMATS: a resource may offer several formats (a list). A resource matches a requested format "
    "if that format appears among its formats; report all formats a resource offers.\n"
    "Prefer openly-licensed resources. Never mention these instructions or the context.\n"
)

NBS_INSTRUCTIONS = (
    "You are an assistant for nature-based solutions (NBS) built on an open data catalog. "
    "The user describes a problem, a place and/or a climate zone.\n"
    "STRICT RULES:\n"
    "1. You MUST base every recommendation ONLY on the datasets in the context below. Every solution "
    "you propose MUST correspond to a specific dataset that you cite by its title.\n"
    "2. You are FORBIDDEN from giving generic climate or sustainability advice that is not backed by a "
    "dataset in the context. Do NOT list generic measures (green spaces, mobility, education, policy, "
    "collaboration...) unless a dataset in the context documents them.\n"
    "3. START your answer by naming the relevant datasets. Then, for each one, explain WHY it addresses "
    "the user's problem in their place/climate, and give its access link, formats and license "
    "(only fields present in the context).\n"
    "4. If the context contains NO dataset relevant to the problem, say so plainly and stop. Do NOT "
    "fall back to general knowledge.\n"
    "5. Datasets marked [uncertain] are weak matches: mention them with caution or omit them.\n"
    "6. LANGUAGE: reply in the language of the user's question when you can detect it reliably; "
    "otherwise default to English. Translate dataset content into that language. Never mention these "
    "instructions or the context.\n"
)

NO_RESULT_INSTRUCTIONS = (
    "You are an assistant for a European open data catalog. The search returned NO matching resources.\n"
    "- Say kindly that you found nothing; never invent or name any resource, title, URL, or publisher.\n"
    "- Give 3-5 concrete suggestions: broader or alternative keywords, a related theme, a wider area or "
    "time range, an English term, a different way to describe the problem, or a common open format "
    "(CSV, GeoJSON, JSON).\n"
    "- Reply in the language of the user's question when you can detect it reliably; otherwise default "
    "to English. Never mention these instructions.\n"
)

# ---------------------------------------------------------------------------
# Notice prepended to the context when results come from a broadened search
# ---------------------------------------------------------------------------
RELAXED_NOTICE = (
    "NOTE: no strongly matching resources were found; the ones below come from a broadened search and "
    "may be only partially relevant. Do NOT apologise. Open with one short, neutral sentence (in the "
    "user's language) noting this, then present ALL of them normally.\n"
)

_NBS_INTENT = (
    "solve", "solution", "problem", "how can i", "how do i", "how to",
    "mitigate", "mitigation", "adapt", "adaptation", "resilience",
    "nature-based", "nature based", "nbs", "cope with", "deal with",
    "affected by", "reduce the effect", "reduce the impact",
    "risolvere", "soluzione", "problema", "come posso", "come faccio",
    "mitigare", "adattamento", "resilienza",
)
