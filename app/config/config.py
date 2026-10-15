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


SYSTEM_INSTRUCTIONS = (                                   # [CHANGED] versione corta
    "You present resources of an open data catalog using ONLY the context.\n"
    "1. Start with one short sentence on what you found.\n"
    "2. List EVERY resource in the context, one numbered item each: exact title, one-sentence "
    "description, formats, license and link (only the fields present).\n"
    "3. If the user asks for a format, say which resources offer it among their formats.\n"
    "4. For advice questions, use only what the descriptions say.\n"
    "Never invent resources, fields or links. Reply in the user's language, keeping titles and "
    "links exactly as written."
)

NBS_INSTRUCTIONS = (                                                  # [CHANGED] versione corta per mistral:7b
    "You recommend nature-based solutions (NBS) using ONLY the case studies in the context.\n"
    "Follow these steps:\n"
    "1. Read the user's problem and constraints: where they live, what is NOT possible for them, "
    "where the solution must go (e.g. on the building, in the street).\n"
    "2. Choose the case studies whose measures solve THAT problem AND respect the constraints. "
    "Choose none if none fits.\n"
    "3. Write the first line: RELEVANT: <exact titles, separated by ;> or RELEVANT: NONE\n"
    "4. For each chosen case study write its title, then 2 sentences on why it fits the user's "
    "situation, then 'Link: <link from the context>'. If the case study is in another city, say so.\n"
    "5. If NONE, write 2-3 short general suggestions suited to the user's climate, without links.\n"
    "Rules: at most 120 words after the first line. Never invent facts, places or links. Never "
    "describe measures the case study does not mention. Do not copy the context. Reply in the "
    "user's language, keeping titles and links exactly as written."
)

# [NEW] Ripetuto in fondo al prompt, subito prima della domanda: i modelli piccoli
# seguono meglio le regole che leggono per ultime, dopo un contesto lungo.
LINK_REMINDER = (                                   # [CHANGED] versione corta
    "Use only the resources above. Copy titles and links exactly as written and do not invent "
    "anything."
)

# [NEW] promemoria NBS letto per ultimo: la decisione esplicita sulla pertinenza
NBS_DECISION_REMINDER = (                                             # [CHANGED] una sola istruzione
    "Now answer. First line: RELEVANT: <titles> or RELEVANT: NONE. Then at most 120 words."
)

NO_RESULT_INSTRUCTIONS = (                                   # [CHANGED] versione corta
    "The search found NO new matching resources in the catalog. Say so kindly and give 2-3 tips "
    "to rephrase the search (other keywords, a wider area, an English term). Never invent "
    "resources, titles or links. Reply in the user's language."
)


RELAXED_NOTICE = (                                   # [CHANGED] versione corta
    "NOTE: these resources come from a broader search and may be only partly relevant: say so in "
    "one short sentence, then continue normally."
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
    # [CHANGED] era "coast": scattava anche per chi VIVE sulla costa ("I live on the coast")
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
    # Italian
    "non posso", "non è possibile", "non e possibile", "invece di", "un'alternativa",
    "alternativa", "qualcos'altro", "qualcosa d'altro", "non va bene", "non funziona",
    "non voglio", "ce n'è un'altra", "ce ne sono altre", "qualcos altro",
)

# [CHANGED] valido sia per i dataset sia per le NBS: nel catalogo sono tutti dcat:Dataset
_REWRITE_PROMPT = (                                   # [CHANGED] versione corta
    "Rewrite the user's new message as a short standalone search query in English, for a catalog "
    "of open datasets and nature-based solution (NBS) case studies.\n"
    "Rules:\n"
    "1. Resolve references ('those', 'the second one') using the conversation.\n"
    "2. If the message adds details or does not name the subject, keep the previous subject and "
    "add the details.\n"
    "3. Keep the kind of resource: include 'nature-based solutions' for NBS, 'datasets' for data.\n"
    "4. If the message rejects a solution, keep the problem and use only positive words (no "
    "'without', 'no', 'not').\n"
    "5. If it is a new, unrelated request, rewrite only that message.\n"
    "Output ONLY the query.\n\n"
    "Previous conversation:\n{context}\n\n"
    "New message: {message}\n\nQuery:"
)