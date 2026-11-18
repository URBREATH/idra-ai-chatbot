# CHANGELOG

Tutti i cambiamenti notevoli del progetto Idra AI Chatbot.

## 2026-11-18

### OpenTelemetry end-to-end (traces, metrics, logs, propagazione)

- Nuovo `app/observability/otel.py`: bootstrap unico con Resource condivisa
  (`service.name/version/namespace`, `deployment.environment.name`,
  `service.instance.id`), `TracerProvider` con sampler, exporter OTLP/HTTP per
  trace/metriche/log, export Prometheus opzionale, auto-instrumentation opzionale
  httpx/PyMongo/PyMySQL e shutdown/flush centralizzati.
- Langfuse e collector OTLP generico condividono lo stesso `TracerProvider`; se
  Langfuse è disattivato ma `OTEL_EXPORTER_OTLP_ENDPOINT` è configurato, la
  pipeline continua a produrre span tramite un adapter interno.
- Propagazione W3C `traceparent` in ingresso/uscita, header `x-trace-id` nelle
  risposte HTTP e `trace_id`/`span_id` in ogni log structlog.
- Semantic conventions: `gen_ai.*` (chat/embeddings, modelli, token, finish
  reason, retry), `http.*`, `db.*`, `openinference.span.kind`; eventi `retry`/
  `error` e status `ERROR` sugli span.
- Metriche OTel: latenza chat/HTTP/LLM/retrieval/DB/ingestion, token per tipo,
  costo LLM, entità ingestion, errori per componente; `/metrics` JSON invariato.
- Nuovi score di qualità: `retrieval_candidates_total`,
  `retrieval_precision_proxy`, `retrieval_score_gap`, `retrieval_latency_ms`,
  `answer_chars`, `context_chars`, `prompt_chars`, `answer_has_sources`,
  `language_method`, `prompt_type`.
- Nuove variabili `OTEL_*` in `.env.example` e README (sezioni 8.6-8.9), con
  identità `idra-ai-chatbot-observation`/`idra-collector`, collector
  `http://host.docker.internal:4318` (`localhost:4318` fuori Docker), protocollo
  `http/protobuf`, log `DEBUG` e tuning di batch/limiti SDK.
- Nuovo `model_pricing.yaml` con hot reload (`app/observability/pricing.py`):
  prezzi per modello in USD/1K token modificabili dall'operatore senza riavvio;
  le variabili `LLM_*_COST_PER_1K` restano solo come fallback.
- Nuovo `observability/slo.yaml`: SLO del deployment piccolo, budget di 10M
  token/mese (warning 80%, critico 100%) ed espressioni PromQL di esempio.
- Corretta l'auto-instrumentazione PyMongo (`PymongoInstrumentor`) e aggiunte
  `opentelemetry-exporter-prometheus`/strumentazioni al requirements locale.

### Prompt esternalizzati + metriche complete di ingestion (Langfuse)

- Prompt di sistema e dei task LLM spostati in `app/prompts/*.md`, caricati da
  `app/prompts/__init__.py` (`load_prompt`, `prompt_metadata`); `app/config/config.py`
  mantiene le costanti pubbliche per compatibilità.
- Ogni span rilevante riporta `prompt_name` e `prompt_version` nei metadata.
- `tracing.py`: nuovo collector di metriche annidabile (`collect_metrics`) con tempi per
  fase, token input/output/total, chiamate e costo per modello; `observe_step` accumula
  automaticamente la durata di ogni fase.
- Embedding: `usage_details` (input/total) e `cost_details` opzionali su ogni observation;
  le generazioni LLM registrano usage e costo.
- Trace `ingestion.run`: metadata `metrics` con tempi di ogni fase, token e costo totale,
  più score `tokens_input`, `tokens_output`, `tokens_total`, `cost_total` (e per entità).
- Nuove variabili `LLM_INPUT_COST_PER_1K`, `LLM_OUTPUT_COST_PER_1K`, `EMBEDDING_COST_PER_1K`
  per il calcolo del costo (default 0 per modelli locali).

## 2026-11-12

### Ingestion da MySQL Idra-Backend + NBS da Orion

- Nuovo modulo `app/mysql/` (`client.py`, `repositories.py`): lettura (read-only) delle tabelle
  DCAT-AP del backend Idra (`dcat_dataset`, `dcat_distribution`, `dcat_keyword`, `dcat_concept`,
  `dcat_agent_name`, `dcat_licensedocument`) con conversione in entità NGSI-like
  (title, description ripulito da HTML, keywords, themes, publisher, catalogue, country,
  formats, URL, license, date, flag NBS).
- Nuovo `app/ingestion/sources.py`: selezione sorgenti via `INGEST_SOURCES`
  (`mysql` = catalogo Idra, `mongo_nbs` = 13 casi studio NBS da Orion nodeID 8,
  `mongo` = flusso legacy Orion completo).
- Ingestion **incrementale** via content-hash SHA1 per entità: alle esecuzioni successive
  vengono reindicizzate solo le entità cambiate; le entità rimosse dalle sorgenti vengono
  eliminate da Chroma a fine run (reconciliation).
- Preflight dei modelli Ollama (embedding, LLM, enrichment) prima del run: 503 se mancanti.
- `POST /admin/ingestion/run` esegue in background e risponde subito con `run_id`
  (`"wait": true` per il run sincrono); `POST /admin/ingestion/status` per il progresso;
  409 se un run è già in corso.
- Run completo verificato: 884 dataset + 6.663 distribuzioni (MySQL) + 13 NBS (Orion).

### Observability con Langfuse self-hosted (OpenTelemetry)

- Nuovo stack `observability/langfuse/` (docker compose: postgres, clickhouse, minio, redis,
  langfuse-web/worker, v4 `events_only`) su `http://localhost:3100`, collegato alla rete
  del chatbot. Le chiavi del progetto restano in `observability/langfuse/.env` (git-ignored).
- Nuovo modulo `app/observability/tracing.py`: wrapper Langfuse SDK v5 (OTel-native, OTLP/HTTP)
  con fallback no-op silenzioso quando le chiavi non sono configurate. Nessun errore di
  tracing può rompere chat o ingestion.
- **Pipeline chat strumentata** (`app/chat/services/chat_service.py`, `chat_followup.py`,
  `app/chat/controllers/chat_controller.py`): trace `chat` per richiesta (sessione =
  conversationId, tag `tenant:<id>`) con span `chat.load_history`, `chat.language_detection`,
  `chat.query_rewrite`, `retrieval.search`, `retrieval.rerank`, `chat.context_assembly`,
  `chat.guardrails`, `llm.*`; score automatici aggregabili in dashboard
  (`retrieval_best_distance`, `exit_path`, `language`, `rerank_method`, `answer_sources`,
  `answer_no_result`, `nbs_mode`, ...).
- `app/retrieval/reranker/reranker.py`: span `retrieval.rerank` con metodo
  (cross_encoder/distance) e ranking completo.
- **Ingestion strumentata** (`app/ingestion/service.py`, `semantic_enricher.py`): trace
  `ingestion.run` per run + una trace per entità (`ingestion.entity`, disattivabile con
  `LANGFUSE_TRACE_INGESTION_ENTITIES=false`) con span di arricchimento semantico; score a
  livello di run (`entities_indexed`, `entities_unchanged`, `entities_errors`,
  `chunks_upserted`, `entities_deleted`) e p50/p95 secondi per entità nei metadata.
  Fix propagazione attributi trace: il corpo del run ora gira dentro il contesto
  `propagate_attributes` (session/tags/trace_name corretti su tutti gli span).
- `app/ollama/client.py`: ogni embedding/generation produce una observation con model,
  usage_details (token prompt/output/total) e timing (eval_ms, tokens/second).
- `GET /health` ora esegue **check reali** su mongo, chroma, ollama, mysql e langfuse
  (`langfuse` è UP/DISABLED e non abbassa lo stato complessivo).

### Feedback utente end-to-end

- `ChatResponse.traceId` restituito da `POST /chat` (`app/chat/dto/models.py`).
- Pulsanti 👍/👎 nella UI (`app/static/index.html`) → `POST /chat/feedback` (body:
  `conversationId`, `rating` positive|negative, `traceId` opzionale, `comment` opzionale):
  crea lo score `user_feedback` (BOOLEAN) in Langfuse sulla trace (o sessione) e persiste
  il feedback in MongoDB (TTL 90 giorni). Rating invalido → 422.

### Resilienza client Ollama

- Retry automatico su errori transitori (5xx HTTP / transport): `OLLAMA_MAX_RETRIES=3`,
  backoff lineare `OLLAMA_RETRY_BACKOFF=2.0`; il body d'errore reale di Ollama viene loggato.
- Switch da `/api/embeddings` (legacy) a `/api/embed` con `truncate: true`: risolti i 500
  "input length exceeds the context length" su chunk 1200-1280 char oltre il contesto
  512-token di mxbai-embed-large; `prompt_tokens` registrato nei trace.

### Test

- Suite completa **verde: 147 passed, 0 falliti** (prima: 32 falliti pre-esistenti / 115 passed).
- Nuovi test: `tests/test_observability.py` (6) e `tests/test_mysql_ingestion.py` (8)
  con OpenTelemetry `InMemorySpanExporter` — nessun server richiesto.
- Test legacy riparati al contratto attuale: payload_builder/semantic_enricher (formato
  blocchi → documento unico, modello da env), chunker (chunk_id con dataset_id, payload
  vuoto → `[]`), chroma/tenancy (delete `$in`, `configuration` hnsw, admin-token auth),
  chat_endpoint (fixture `ADMIN_TOKEN`, `userId` nel body, persistenza spostata in
  `generate_answer`), mongodb_client (contratto env-driven), retrieval_pipeline
  (filtro `$and`, rerank top_k), runtime_validation/dcp2 (fake Chroma con `count()`,
  `include`, `$and`, `delete $in`; golden records con `entity_type`).

### Documentazione

- `README_PRODUZIONE.md` aggiornato: sorgenti ingestion (MySQL/NBS), stack Langfuse
  (avvio, fix `HOSTNAME=0.0.0.0`, rete condivisa), health reali, endpoint ingestion
  background/status, sezione observability (span, score, feedback, privacy env),
  variabili d'ambiente nuove, backup volumi Langfuse, troubleshooting esteso.

### Miglioramenti minimi al codice

- `app/ingestion/chunker.py`: payload vuoto e senza titolo → `[]` (nessun chunk "N/A"
  spazzatura nell'indice; riattivato il ramo "no chunks → no upsert").
- `requirements.txt`: aggiunto `langfuse==5.2.0` (SDK OTel-native); SDK OTel aggiornati
  a 1.45.2 per compatibilità con chromadb.
