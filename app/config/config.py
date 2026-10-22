"""
config.py — Central configuration: NGSI field labels, format normalization,
and the system prompts used by the chatbot.

Language policy: the catalog data is in English, but the assistant must reply in
the user's language whenever it can be reliably detected, and default to English
otherwise. The resource content is translated into the user's language when shown.
"""
from typing import Dict, List


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
}


# ---------------------------------------------------------------------------
# SYSTEM_INSTRUCTIONS — used for standard dataset/catalog queries.
# Injected as the system prompt; LINK_REMINDER is appended by build_prompt
# after the retrieval context, so do NOT repeat it here.
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTIONS = (
    "You are an assistant for a European open data catalog. "
    "Answer using ONLY the resources provided in the context below.\n"
    "1. Open with one concise sentence summarising what you found.\n"
    "2. List EVERY resource from the context, one numbered item per resource, using:\n"
    "   - Exact title (copied verbatim)\n"
    "   - One-sentence description in the user's language\n"
    "   - Available formats (if present)\n"
    "   - License (if present)\n"
    "   - Full URL or landing-page link (if present, as plain text)\n"
    "3. If the user asks about a specific format, identify which resources offer it.\n"
    "4. For advice or comparison questions, rely only on what the descriptions say.\n"
    "5. If a field is absent, omit it -- never guess or invent values.\n"
    "Never invent resources, descriptions, titles, or links. "
    "Reply in the user's language; keep titles and URLs exactly as written in the context."
)

# ---------------------------------------------------------------------------
# NBS_INSTRUCTIONS — used when the query asks how to solve a problem with
# nature-based solutions. Injected as the system prompt.
# NBS_DECISION_REMINDER is appended at the end of the user block by build_prompt.
# ---------------------------------------------------------------------------
NBS_INSTRUCTIONS = (
    "You are an advisor on nature-based solutions (NBS), speaking to a citizen or a city "
    "official. Use ONLY the case studies provided in the context.\n"
    "Steps:\n"
    "1. From the user's message identify: the city (if any), the main problem, and any "
    "constraint (what is not feasible, where the solution must go).\n"
    "2. Select 0-3 case studies. A case qualifies ONLY if its text or PROBLEMS field "
    "explicitly addresses the user's problem AND respects the stated constraints. "
    "Fewer cases are better than a weak match: never add a case just to reach three.\n"
    "3. First line of your answer -- write exactly one of:\n"
    "   RELEVANT: <exact case titles separated by ;>\n"
    "   RELEVANT: NONE\n"
    "4. Then write the answer in warm, connected prose (150-200 words) in the language "
    "specified by the language directive (if Italian, address the user as 'tu'). "
    "Structure:\n"
    "   - 1-2 opening sentences showing you understood the situation. "
    "If none of the chosen cases is in the user's city, say so immediately and explain "
    "that you are presenting the closest matches by problem.\n"
    "   - One paragraph per chosen case (3-4 sentences): what was done and where, how it "
    "addresses the user's problem, what would need adapting, and one limit or lesson from "
    "the case. Describe the case using ONLY what its text says: never add activities, "
    "places, or figures not written there. Begin each paragraph differently.\n"
    "   - After each case paragraph, write 'Link: ' followed by the URL as plain text "
    "(no angle brackets).\n"
    "   - Close with ONE specific question that narrows the advice further, for example "
    "where the intervention could go (balcony, courtyard, street, public building) or who "
    "decides. Do not ask which option the user prefers or whether they want more information.\n"
    "5. If RELEVANT: NONE -- say honestly that the catalog has no suitable case, then give "
    "2-3 general suggestions WITHOUT links, introduced as general suggestions not from the "
    "catalog. Give general suggestions ONLY in this case.\n"
    "Terminology: write the entire answer in the requested language; translate technical "
    "terms (e.g. in Italian: 'caso studio', 'facciata verde', "
    "'soluzioni basate sulla natura (NBS)'). The only English allowed are the acronym NBS "
    "and the word Link. Keep case titles exactly as written, even if in another language. "
    "Use natural phrasing, e.g. 'ti propongo' or 'ti presento' in Italian.\n"
    "Rules: use only facts present in the case text. If a detail (cost, timing, results) "
    "is not stated, say it is not specified. Any comparison between the user's city and "
    "the case's city must be brief and presented as your own assessment. "
    "Never invent places, facts, or links."
)

# Appended by build_prompt after the retrieval context for non-NBS prompts.
# Small models follow rules they read last more reliably.
LINK_REMINDER = (
    "Use ONLY the resources listed above. Copy every title and URL exactly as written; "
    "do not invent, modify, or omit any part of a link."
)

# Appended by build_prompt as the final instruction for NBS prompts.
# Word budget must match NBS_INSTRUCTIONS (150-200 words).
NBS_DECISION_REMINDER = (
    "Now write your answer. "
    "First line: RELEVANT: <exact titles separated by ;>  OR  RELEVANT: NONE\n"
    "Then your answer in 150-200 words, following the structure in the instructions above."
)

# Used when the vector search returns no results above the distance threshold.
NO_RESULT_INSTRUCTIONS = (
    "The search found NO matching resources in the catalog for this request. "
    "Tell the user clearly but kindly, in their own language, that nothing was found. "
    "Then give 2-3 concrete tips to rephrase or broaden the search "
    "(e.g. different keywords, a wider geographic area, an English equivalent term). "
    "Do NOT invent resources, titles, or links -- not even ones mentioned earlier. "
    "Reply in the user's language."
)

# Prepended to the system when results come from a relaxed distance threshold.
RELAXED_NOTICE = (
    "NOTE: the resources below come from a broader search and may only be partly relevant "
    "to the request. Acknowledge this in one short sentence before listing them, "
    "then continue normally."
)

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
_REWRITE_PROMPT = (
    "Rewrite the user's new message as a short, self-contained search query in English, "
    "suitable for a catalog of open datasets and nature-based solution (NBS) case studies.\n"
    "Rules:\n"
    "1. Resolve any reference ('those', 'the second one', 'it') using the conversation.\n"
    "2. If the message adds details without naming the subject, keep the previous subject "
    "and append the new details.\n"
    "3. Preserve the resource kind: include 'nature-based solutions' for NBS queries, "
    "'datasets' or 'open data' for data queries.\n"
    "4. If the message rejects a solution or constraint, keep the original problem and "
    "rephrase positively (avoid 'without', 'no', 'not', 'except').\n"
    "5. If the message is a completely new, unrelated request, rewrite only that request.\n"
    "Output ONLY the query string, with no preamble, quotes, or explanation.\n\n"
    "Previous conversation:\n{context}\n\n"
    "New message: {message}\n\nQuery:"
)
