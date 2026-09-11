# Third-Party Notices

Questo file elenca le librerie software e i modelli AI di terze parti usati da
**Idra AI Chatbot**, con la relativa licenza. Il progetto è a **uso interno
aziendale** ed è distribuito come **SaaS self-hosted** (nessuna distribuzione
del codice sorgente o dei binari a soggetti esterni); questo file va comunque
mantenuto aggiornato per finalità di audit legale/procurement e per prevenire
l'introduzione accidentale di componenti con licenze incompatibili.

Ultimo aggiornamento: 2026-09-10.

---

## 1. Librerie Python (da `requirements.txt`)

| Pacchetto | Versione | Licenza | Tipo | Note |
|---|---|---|---|---|
| fastapi | 0.115.0 | MIT | Permissiva | — |
| uvicorn[standard] | 0.30.6 | BSD-3-Clause | Permissiva | — |
| pydantic | 2.8.2 | MIT | Permissiva | — |
| pydantic-settings | 2.4.0 | MIT | Permissiva | — |
| httpx | 0.27.2 | BSD-3-Clause | Permissiva | — |
| chromadb | >=1.0.0 | Apache-2.0 | Permissiva | client HTTP verso servizio ChromaDB |
| python-dotenv | >=1.2.2 | BSD-3-Clause | Permissiva | — |
| structlog | 24.2.0 | MIT / Apache-2.0 (dual) | Permissiva | — |
| motor | >=3.7 | Apache-2.0 | Permissiva | — |
| pymongo | >=4.9 | Apache-2.0 | Permissiva | — |
| PyJWT | >=2.8.0,<3 | MIT | Permissiva | — |

**Nessuna dipendenza copyleft (GPL/LGPL/AGPL/SSPL) presente.**

### Dipendenza opzionale non dichiarata

| Pacchetto | Licenza | Stato |
|---|---|---|
| sentence-transformers | Apache-2.0 | Importato in [app/common/utils/reranker_encoder.py](app/common/utils/reranker_encoder.py) ma **non presente** in `requirements.txt`. Se non installato manualmente, il reranker cross-encoder non è mai attivo (fallback automatico a ranking per distanza). Nessun problema di licenza (Apache-2.0), ma va deciso se includerla esplicitamente o rimuovere il codice che la referenzia. |

## 2. Immagine Docker base

| Componente | Licenza | Note |
|---|---|---|
| `python:3.12-slim` (Dockerfile) | PSF License (Python) + varie licenze Debian | Immagine ufficiale, non modificata; nessun obbligo aggiuntivo per uso interno |

## 3. Servizi containerizzati di terze parti

| Servizio | Licenza | Note |
|---|---|---|
| Ollama (runtime modelli locali) | MIT | Eseguito come servizio containerizzato, non modificato |
| ChromaDB (server vettoriale) | Apache-2.0 | Eseguito come servizio containerizzato, non modificato |
| MongoDB (Community Server) | SSPL (Server Side Public License) | Usato come servizio esterno/infrastruttura, non incorporato nel codice applicativo; verificare i termini SSPL con il proprio fornitore/versione se si offre l'app come servizio a terzi in futuro |

## 4. Modelli AI (eseguiti localmente via Ollama)

I modelli sono scaricati con `ollama pull <tag>` ed eseguiti localmente/self-hosted;
nessun dato viene inviato a servizi esterni. Ogni modello ha però una propria
licenza d'uso che si accetta scaricandolo.

| Modello | Uso | Licenza | Restrizioni note |
|---|---|---|---|
| `mxbai-embed-large` | Embedding (query + ingestione) | Apache-2.0 | Nessuna |
| `mistral-nemo` | Generazione (default in codice) | Apache-2.0 (Mistral AI) | Nessuna |
| `mixtral` | Generazione (default in README_PRODUZIONE.md) | Apache-2.0 (Mistral AI) | Nessuna |
| `qwen2.5:7b` | Generazione (default in `.env.example` e `semantic_enricher.py`) | Apache-2.0 | ⚠️ Solo per le taglie 0.5B/1.5B/7B/14B/32B. Le taglie **3B e 72B** usano la "Qwen License Agreement" (non Apache-2.0), con soglie di utilizzo e restrizioni commerciali. Verificare sempre la taglia esatta pullata. |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranking (attualmente inattivo, v. sopra) | Apache-2.0 | Nessuna |

### Modelli NON attualmente in uso ma da trattare con cautela se aggiunti in futuro

| Famiglia modello | Licenza | Restrizioni |
|---|---|---|
| Llama (Meta) | Llama Community License | Acceptable Use Policy da rispettare anche per uso interno (vieta usi specifici: armi, sorveglianza illecita, disinformazione, ecc.); licenza commerciale speciale richiesta solo oltre 700M MAU (non applicabile a uso interno aziendale) |
| Modelli con licenza "research-only" / "non-commercial" | Varie | Da evitare: l'uso aziendale, anche solo interno, è generalmente considerato "uso commerciale" e violerebbe questi termini |

---

## Come mantenere aggiornato questo file

- Ad ogni modifica di `requirements.txt`, aggiornare la relativa tabella (es. con `pip-licenses`).
- Ad ogni cambio del modello LLM/embedding/reranker di default (env var `OLLAMA_LLM_MODEL`, `OLLAMA_EMBEDDING_MODEL`), verificare la licenza del nuovo tag Ollama e aggiornare la tabella dei modelli.
- Vedi [LICENSE_ACTION_PLAN.md](LICENSE_ACTION_PLAN.md) per le raccomandazioni di processo/governance.
