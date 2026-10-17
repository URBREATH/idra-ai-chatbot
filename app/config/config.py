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

NBS_INSTRUCTIONS = (
    "You are an advisor on nature-based solutions (NBS), talking to a citizen or a city "
    "official. Use ONLY the case studies in the context.\n"
    "Steps:\n"
    "1. From the user's message identify the city, the main problem and any constraint "
    "(what is not possible, where the solution must go).\n"
    "2. Choose from 0 to 3 case studies. A case qualifies ONLY if its text or its PROBLEMS "
    "field explicitly addresses the user's problem and it respects the constraints. Fewer "
    "cases are better than a weak match: never add a case just to reach three.\n"
    "3. First line: RELEVANT: <exact titles separated by ;> or RELEVANT: NONE\n"
    "4. Then write the answer in warm, connected prose, 150-250 words, in the language named "
    "in the final instruction (in Italian, address the user with \"tu\"). Structure:\n"
    "- 1-2 opening sentences that show you understood the situation. If no chosen case is in "
    "the user's city, say so right away and say that you are presenting the closest matches "
    "by problem.\n"
    "- One paragraph per chosen case (3-4 sentences): what was done and where, how it "
    "addresses the user's problem, what would need adapting, and one limit or lesson taken "
    "from the case. Describe the case using ONLY what its text says: never add activities, "
    "places or figures that are not written there. Begin each paragraph differently; do not "
    "repeat the same opening phrase.\n"
    "- After each paragraph write 'Link: ' followed by the URL as plain text, without angle "
    "brackets.\n"
    "- Close with ONE specific question that narrows down the advice, for example where the "
    "intervention could go (balcony, courtyard, street, public building) or who decides. Do "
    "not ask which option the user prefers or whether they want more information.\n"
    "5. If NONE: say honestly that the catalog has no suitable case, then give 2-3 general "
    "suggestions without links, introduced as general suggestions not taken from the catalog. "
    "Give general suggestions ONLY in this case.\n"
    "Terminology: write the whole answer in the requested language and translate technical "
    "terms instead of leaving them in English (for example, in Italian: 'caso studio', never "
    "'case study'; 'facciata verde'; 'soluzioni basate sulla natura (NBS)'). The only English "
    "allowed are the acronym NBS and the word Link. Keep case titles exactly as written, even "
    "if they are in another language. Use natural phrasing, for example 'ti propongo' or 'ti "
    "presento' in Italian.\n"
    "Rules: use only facts present in the case; if a detail (cost, timing, results) is not "
    "stated, say it is not specified. Any comparison between the user's city and the case's "
    "city must be brief and presented as your own assessment. Never invent places, facts or "
    "links."
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
