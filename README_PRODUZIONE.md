# Idra AI Chatbot - Guida alla Produzione

Platform: Local Multi-Tenant RAG per metadati europei (NGSI-LD, DCAT-AP, SDMX).

Sorgenti dati supportate:
- **MongoDB Orion** (FIWARE Orion Context Broker): entità NGSI-LD, inclusi i 13 casi studio NBS (nodeID 8).
- **MySQL Idra-Backend**: cataloghi DCAT-AP (`dcat_dataset`, `dcat_distribution`, `dcat_keyword`, `dcat_concept`, `dcat_agent_name`, `dcat_licensedocument`).
- **Observability**: Langfuse self-hosted (OpenTelemetry-native) per tracciare chat, retrieval e ingestion.

---

## 1. Prerequisiti di Sistema

| Requisito | Versione Minima |
|-----------|-----------------|
| OS | Linux (Ubuntu 22.04+ consigliato) / Windows 10+ con Docker Desktop |
| CPU | x86_64 con supporto AVX2 |
| RAM | 150 GB minimo per il modello LLM 16B; **>= 12 GB allocati a Docker** (con 2 GB Docker va in hang durante pull/build) |
| Docker | 24.x + Docker Compose v2 |
| Ollama | 0.1.32+ |
| Python | 3.12 (eseguito all'interno del container) |
| MySQL | 8.x (database Idra-Backend, può girare in un compose separato) |

> **Nota Docker Desktop (Windows)**: se Docker si blocca su pull/build/buildkit, aumentare la RAM
> allocata (Settings → Resources → Memory, es. 12288 MiB). Backup dei settings in
> `%APPDATA%\Docker\settings-store.json.bak` / `settings.json.bak`.

---

## 2. Installazione Dipendenze Globali

```bash
# Docker (Ubuntu)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Docker Compose
sudo apt-get install -y docker-compose-plugin

# Ollama
curl -fsSL https://ollama.com/install.sh | sh
```

---

## 3. Configurazione Ambiente

### 3.1 File d'ambiente

> **Attenzione (verificato nel codice)**: il `docker-compose-example.yml` presente nella root
> del progetto carica realmente `env_file: .env.test` per il servizio `app` (non
> `.env.production`). Il compose avvia anche un servizio `ollama` proprio (container
> `ollama`, volume `ollama_data`), quindi **non** è più necessario
> `host.docker.internal`/`extra_hosts` per Ollama.
> Prima di andare in produzione:
> - rinominare il file creato qui sotto in `.env.test` (per usarlo così com'è),
>   **oppure** modificare `docker-compose-example.yml` per puntare a `.env.production`;
> - eseguire il pull dei modelli nel container `ollama` (vedi sezione 4).

Creare il file nella root del progetto (template completo in `.env.example`):

```bash
# App
PORT=3000

# MongoDB (nome container reale: orion_mongo, database: orion)
MONGODB_URI=mongodb://orion_mongo:27017/orion

# ChromaDB (nome container reale: rag_chroma)
CHROMA_HOST=rag_chroma
CHROMA_PORT=8000

# Ollama (servizio proprio del compose, container/servizio: ollama)
OLLAMA_HOST=ollama
OLLAMA_PORT=11434
OLLAMA_EMBEDDING_MODEL=mxbai-embed-large
OLLAMA_LLM_MODEL=mixtral
# Modello usato per l'enrichment semantico dei termini di ricerca (può essere più leggero del LLM principale)
OLLAMA_ENRICHMENT_MODEL=llama3.1

# JWT (CAMBIARE IN PRODUZIONE)
JWT_SECRET=<generare con: openssl rand -hex 32>
JWT_EXPIRES_IN=1h

# Admin token per gli endpoint /admin/* (confronto diretto, NON è un JWT)
ADMIN_TOKEN=<generare con: openssl rand -hex 32>

# Tenant
DEFAULT_TENANT_ID=default-tenant

# --- Sorgenti ingestion ---
# Valori separati da virgola: mysql (catalogo Idra), mongo_nbs (casi studio NBS da Orion).
# Vuoto/"mongo" = solo comportamento legacy MongoDB.
INGEST_SOURCES=mysql,mongo_nbs

# MySQL Idra-Backend (host sul network del compose del backend, es. idra-backend_idra_main)
MYSQL_HOST=db
MYSQL_PORT=3306
MYSQL_USER=...
MYSQL_PASSWORD=...
MYSQL_DATABASE=idra

# --- Observability: Langfuse self-hosted (observability/langfuse/) ---
# Tracing attivo solo se entrambe le chiavi sono impostate; altrimenti no-op silenzioso.
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=http://langfuse-web:3000
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_RELEASE=
LANGFUSE_SAMPLE_RATE=1.0
# false = non inviare prompt/risposte/documenti, solo metriche e metadata
LANGFUSE_CAPTURE_IO=true
LANGFUSE_MAX_IO_CHARS=20000
# false = solo la trace a livello di run di ingestion (senza una trace per entità)
LANGFUSE_TRACE_INGESTION_ENTITIES=true
```

> Note:
> - Ollama gira come servizio containerizzato (`ollama`) definito in `docker-compose-example.yml`:
>   nessuna configurazione di rete aggiuntiva necessaria.
> - Se si preferisce usare un'istanza Ollama già installata sull'host (es. per sfruttare una
>   GPU non passata al container), impostare `OLLAMA_HOST=host.docker.internal`, rimuovere il
>   servizio `ollama` da `docker-compose-example.yml` e aggiungere
>   `extra_hosts: ["host.docker.internal:host-gateway"]` al servizio `app` (necessario su Linux).
> - Il container `app` deve essere collegato anche alla rete dove gira MySQL Idra-Backend
>   (es. `idra-backend_idra_main`, external network) e a `langfuse_rag_network` (vedi sezione 5.3).

---

## 4. Preparazione Modelli Ollama

```bash
# Embedding model (nel container ollama del compose)
docker exec ollama ollama pull mxbai-embed-large

# LLM principale
docker exec ollama ollama pull mixtral

# Modello enrichment semantico (leggere: i tempi di ingestion dipendono molto da questo)
docker exec ollama ollama pull llama3.1

# Verifica
docker exec ollama ollama list
```

> I modelli vengono scaricati nel volume Docker `ollama_data` (persistente tra i riavvii).
> Il container `app` accede a Ollama via rete Docker interna (`ollama:11434`),
> pertanto non è necessario montare i modelli all'interno del container `app`.
>
> **Tempi indicativi ingestion completa** (884 dataset + 6.663 distribuzioni + 13 NBS, enrichment LLM attivo):
> 12-14 ore con `llama3.1` su CPU. Le esecuzioni successive sono **incrementali** (content-hash,
> solo entità cambiate) e quindi molto più rapide. Il preflight dei modelli (`/admin/ingestion/run`)
> restituisce 503 se un modello richiesto non è presente.

---

## 5. Deployment con Docker Compose

### 5.1 Docker Compose App

```bash
# Avvio servizi
docker-compose up -d

# Verifica stato
docker-compose ps

# Log
docker-compose logs -f app
```

### 5.2 Servizi App

| Servizio | Porta | Descrizione |
|----------|-------|-------------|
| idra_ai_chatbot | 3000 | FastAPI App |
| orion_mongo | 27017 | MongoDB (Orion) |
| rag_chroma | 8000 | ChromaDB |
| ollama | 11434 | LLM/Embedding |
| langfuse-web | 3100 (host) → 3000 (container) | UI + API Langfuse |

### 5.3 Stack Langfuse (Observability)

Il compose dedicato si trova in `observability/langfuse/` (postgres, clickhouse, minio,
redis, langfuse-web, langfuse-worker). Langfuse v4 gira in modalità `events_only`:
le trace arrivano via **OpenTelemetry/OTLP over HTTP** su `/api/public/otel/v1/traces`.

```bash
cd observability/langfuse

# 1. Generare il file d'ambiente con le chiavi del progetto (una tantum):
#    copiare .env.example in .env e impostare:
#    LANGFUSE_INIT_ORG_ID, LANGFUSE_INIT_ORG_NAME (es. idra),
#    LANGFUSE_INIT_PROJECT_ID, LANGFUSE_INIT_PROJECT_NAME (es. idra-ai-chatbot),
#    LANGFUSE_INIT_PROJECT_PUBLIC_KEY (pk-lf-...), LANGFUSE_INIT_PROJECT_SECRET_KEY (sk-lf-...),
#    LANGFUSE_INIT_USER_EMAIL / LANGFUSE_INIT_USER_PASSWORD (login UI),
#    NEXTAUTH_SECRET, SALT, credenziali ClickHouse/Postgres/Minio/Redis.
#    NB: la public key serve anche come ADMIN_TOKEN per /api/public/health.

# 2. Avvio (prima esecuzione: crea org/progetto/utente/chiavi automaticamente)
docker compose --env-file .env up -d

# 3. FIX NECESSARIO (v4 con due reti): Next.js non binda alle porte pubblicate.
#    In docker-compose.yml, servizio langfuse-web:
#      environment:
#        - HOSTNAME=0.0.0.0
#    poi: docker compose --env-file .env up -d --force-recreate langfuse-web
```

**Collegamento alla rete del chatbot**: la UI è raggiungibile dall'host su
`http://localhost:3100`; il chatbot deve raggiungere il servizio sulla rete interna.
Aggiungere al compose del chatbot una rete esterna condivisa, oppure collegare i container:

```bash
# Il servizio langfuse-web deve raggiungere il container app sull'unica rete condivisa.
# 1. una volta sola: aggiungere langfuse-web alla rete del chatbot
docker network connect rag_network langfuse-langfuse-web-1
# 2. in docker-compose.yml di observability/langfuse dichiararla per renderla persistente:
#    networks:
#      rag_network:
#        external: true
#      default: {}
#    e nel servizio langfuse-web: networks: [default, rag_network]
# 3. il chatbot usa LANGFUSE_BASE_URL=http://langfuse-web:3000 (nome servizio, porta container)
```

Verifica:

```bash
# Health (la public key fa da basic-auth username)
curl -u "pk-lf-..." http://localhost:3100/api/public/health

# Health dalla rete interna del chatbot
docker exec idra_ai_chatbot curl -s http://langfuse-web:3000/api/public/health
```

> **Sicurezza**: non esporre la porta 3100 pubblicamente in produzione; bindarla a
> `127.0.0.1:3100:3000` o proteggerla con reverse proxy. Le chiavi (`observability/langfuse/.env`)
> sono coperte dal pattern `.env` in `.gitignore`.

---

## 6. Inizializzazione Database

### 6.1 MongoDB - Dati Orion (NGSI-LD)

> **Nota (verificato nel codice)**: `app/mongodb/repositories.py` **legge soltanto** (nessun
> insert/update) dalle collection `entities` e `deleted_datasets` del database `orion`,
> che devono esistere e contenere entità NGSI-LD nel formato descritto in
> `DATABASE_SCHEMA.md` (popolate da un FIWARE Orion Context Broker esterno). Il blocco
> seguente è utile solo per creare dati di **test locale** con lo schema corretto.

```bash
# Copia il file JSON con le entità di test nel container (schema NGSI-LD, vedi DATABASE_SCHEMA.md)
docker cp entities.json orion_mongo:/entities.json

# Import dei documenti nella collection `entities`
docker exec -i orion_mongo mongoimport \
  --db orion --collection entities \
  --file /entities.json --jsonArray

# Indici consigliati per le query usate in app/mongodb/repositories.py
[ 'deleted_datasets', 'conversations', 'entities' ]
```

> Ogni documento deve avere `_id` come oggetto `{ id, type, servicePath }` (non un
> `ObjectId` semplice) e i campi `attrs`, `modDate`, `creDate` come da schema Orion.
> Il formato "un documento piatto per dataset" non è supportato dal codice attuale.

### 6.2 MySQL Idra-Backend

Il chatbot **legge soltanto** dal database del backend Idra. Avviare il compose del backend
(es. `idra-backend`) e collegare il container `app` alla sua rete (es.
`idra-backend_idra_main`). Non è richiesta alcuna inizializzazione lato chatbot:
le tabelle `dcat_*` devono essere già popolate dal backend.

```bash
# Esempio: collegare il container app alla rete del backend
docker network connect idra-backend_idra_main idra_ai_chatbot

# Verifica: MYSQL_HOST deve essere il nome del servizio MySQL del backend (es. "db")
docker exec idra_ai_chatbot python -c "from app.mysql.client import ping_mysql; ping_mysql()"
```

### 6.3 Verifica Connessioni

```bash
# Health check
curl http://localhost:3000/health
```

Response attesa con tutte le dipendenze attive:

```json
{"status":"UP","mongo":"UP","chroma":"UP","ollama":"UP","mysql":"UP","langfuse":"UP"}
```

> L'endpoint `/health` esegue **check reali** su Mongo, Chroma, Ollama, MySQL e Langfuse.
> `mysql` è UP quando `INGEST_SOURCES` include `mysql` e la connessione riesce;
> `langfuse` è UP/DISABLED (le chiavi mancanti degradano a no-op senza abbassare lo stato
> complessivo). Con `INGEST_SOURCES` senza `mysql`, il campo mysql riporta `DISABLED`.

---

## 7. Ingestione Dati

### 7.1 Come funziona

- **Sorgenti** (`INGEST_SOURCES`): `mysql` legge i cataloghi Idra-Backend e li converte in
  entità NGSI-like (title, description ripulito dall'HTML, keywords, themes, publisher,
  catalogue, country, formats, URL, license, date, flag NBS); `mongo_nbs` legge da Orion i
  soli casi studio NBS (nodeID 8). Il flusso legacy `mongo` (tutte le entità Orion) resta disponibile.
- **Incrementale**: ogni entità produce un content-hash (SHA1); alla successiva esecuzione
  vengono reindicizzate solo le entità cambiate.
- **Reconciliation**: a fine run le entità non più presenti nelle sorgenti vengono rimosse da Chroma.
- **Esecuzione in background**: `POST /admin/ingestion/run` avvia il run in background e
  risponde subito con `run_id`; con `"wait": true` il run è sincrono.
- **Preflight**: prima del run vengono verificati i modelli Ollama richiesti
  (embedding, LLM principale, enrichment): 503 se mancanti.
- **Rientranza**: 409 se un run è già in corso.

### 7.2 Ingestione Manuale

```bash
# Endpoint (richiede ADMIN_TOKEN, NON un JWT - vedi app/auth.py)
curl -X POST http://localhost:3000/admin/ingestion/run \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fullReindex": false}'

# Run sincrono (blocca fino al termine; usare con timeout elevato)
curl -X POST http://localhost:3000/admin/ingestion/run \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fullReindex": false, "wait": true}'

# Stato del run corrente/ultimo
curl http://localhost:3000/admin/ingestion/status -H "Authorization: Bearer $ADMIN_TOKEN"
# {"running":true,"processed":123,"remaining":761,"start_time":"...","sources":["mysql","mongo_nbs"],...}
```

### 7.3 Ingestione Programmata (Cron)

```bash
# Aggiungi al crontab del server: invocare l'endpoint HTTP beneficia della stessa
# code path del container (preflight, background run, tracing, 409 re-entrancy).
0 3 * * * curl -s -X POST http://localhost:3000/admin/ingestion/run \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"fullReindex": false}'
```

### 7.4 Full Reindex

`{"fullReindex": true}` cancella la collection e reindicizza tutto. Usarlo dopo un cambio
di modello embedding (dimensioni diverse) o di pipeline di chunking.

---

## 8. Observability (Langfuse)

### 8.1 Cosa viene tracciato

**Chat / Retrieval** — trace `chat` per richiesta (sessione = conversationId, tag
`tenant:<id>`), con span:

| Span | Contenuto |
|------|-----------|
| `chat.load_history` | numero messaggi cronologia |
| `chat.language_detection` | metodo e confidenza |
| `chat.query_rewrite` | query riscritta (LLM) |
| `retrieval.search` | retriever, query, top-k, risultati con rank/distance/kept, soglie e relax |
| `retrieval.rerank` | metodo (cross_encoder/distance) e ranking |
| `chat.context_assembly` | risorse nel contesto |
| `llm.answer` / `llm.no_result_answer` / `llm.query_rewrite` / `llm.language_detection` | generazioni con token e latenze |
| `chat.guardrails` | sanificazione output (link inventati rimossi) |

**Score automatici per trace** (numerici e categorici, aggregabili in dashboard):
`retrieval_best_distance`, `retrieval_candidates_kept`, `retrieval_threshold_final`,
`retrieval_threshold_relaxed`, `answer_sources`, `context_resources`,
`invented_links_removed`, `answer_no_result`, `answer_cited_resource`, `nbs_mode`,
`exit_path` (categorico: answered/no_result), `language`, `rerank_method`.

**Ollama / API remoti**: ogni `generate_embedding` / `generate_completion` produce una
observation `embedding`/`generation` con model, model_parameters, usage
(prompt/output/total tokens, durations) e timing (eval_ms, tokens/second). L'`input`
della generation contiene i `messages` esatti (`system` + `user`) inviati al provider;
l'`input` dell'embedding contiene il testo esatto. I metadata riportano `provider`
(`ollama` o `openai`), `endpoint` e `request` (body HTTP completo, troncato a
`LANGFUSE_MAX_IO_CHARS`), così il prompt è verificabile sia in locale sia in remoto.
L'enrichment usa la generation dedicata `llm.enrichment`.

**Ingestion** — trace `ingestion.run` per run (sessione `ingestion-<run_id>`) con span
`read_index`, `full_reindex_delete`, `load_sources`, `plan`, `build_payload`, `chunk`,
`embeddings`, `semantic_enrichment`, `chroma_upsert`, `remove_stale`, più **una trace per
entità** (`ingestion.entity`, disattivabile con `LANGFUSE_TRACE_INGESTION_ENTITIES=false`)
con span `ingestion.semantic_enrichment` e score `enrichment_terms`/`enrichment_status`/
`chunks`/`tokens_total`/`cost_total`. Score a livello di run: `entities_indexed`,
`entities_unchanged`, `entities_errors`, `chunks_upserted`, `entities_deleted`,
`tokens_input`, `tokens_output`, `tokens_total`, `cost_total`, più p50/p95 secondi per
entità nei metadata.

I metadata della trace `ingestion.run` contengono il riepilogo `metrics` con:
`timings_ms` (somma dei tempi di ogni fase), `usage` (token input/output/total),
`cost` (se configurato), `calls` per tipo e `models` con token/costo per modello.
Gli embedding riportano `usage_details` (input/total) e, se configurato, `cost_details`.
Se il modello locale non restituisce token, il conteggio resta 0 ma la fase è comunque
temporizzata.

### 8.2 Prompt versionati

I prompt di sistema e i prompt dei task LLM (lingua, rewrite, enrichment) vivono in
`app/prompts/*.md`; il codice li carica tramite `app.prompts.load_prompt`. Ogni span
rilevante riporta `prompt_name` e `prompt_version` (hash breve del file) nei metadata,
così in Langfuse è immediato capire quale prompt ha prodotto una risposta. Per
l'enrichment lo span `ingestion.semantic_enrichment` espone in `input` sia il testo
sorgente sia il prompt renderizzato (`{text}` già sostituito), identico a quello
inviato nella generation `llm.enrichment`.

### 8.3 Feedback utente

- `POST /chat` restituisce `traceId` nel payload (`ChatResponse.traceId`).
- La UI mostra pulsanti 👍/👎 sotto ogni risposta dell'assistente.
- `POST /chat/feedback` (body: `conversationId`, `rating` `"positive"|"negative"`,
  `traceId` opzionale, `comment` opzionale) crea lo score `user_feedback` (BOOLEAN) in
  Langfuse sulla trace (o sulla sessione se traceId assente) e persiste il feedback in
  MongoDB (TTL 90 giorni). Rating invalido → 422.

```bash
curl -X POST http://localhost:3000/chat/feedback -H "Content-Type: application/json" \
  -d '{"conversationId":"...","rating":"positive","traceId":"<traceId dalla risposta chat>","comment":"utile"}'
```

### 8.4 Dashboard e query

- UI: `http://localhost:3100` (login: credenziali `LANGFUSE_INIT_USER_*`).
- Filtri utili: `session.id = conv-<id>`, tag `chat`, tag `ingestion`, tag
  `tenant:<tenant_id>`, environment `development` (`LANGFUSE_TRACING_ENVIRONMENT`).
- Grafici consigliati: `retrieval_best_distance` (p95), `exit_path=no_result` (rate),
  `user_feedback` (ratio positivo), durata `llm.answer`, `tokens_per_second`.
- API v4 `events_only`: gli endpoint legacy `GET /api/public/traces` sono disabilitati;
  le trace sono esportate via OTLP (`POST /api/public/otel/v1/traces`) e consultate da UI.
  Gli score restano inviabili via `POST /api/public/scores` (l'SDK li gestisce).

### 8.5 Configurazione privacy/volume

| Variabile | Effetto |
|-----------|---------|
| `LANGFUSE_CAPTURE_IO=false` | non salva prompt/risposte/documenti, solo metriche e metadata (consigliato se i dati sono sensibili) |
| `LANGFUSE_MAX_IO_CHARS` | troncamento input/output salvati (default 20000) |
| `LANGFUSE_SAMPLE_RATE` | campionamento trace (es. `0.25` = 25% delle richieste) |
| `LANGFUSE_TRACE_INGESTION_ENTITIES=false` | solo trace run-level durante l'ingestion (riduce volume) |
| `MODEL_PRICING_FILE` | percorso alternativo del listino (default `model_pricing.yaml` nella root) |
| `LLM_INPUT_COST_PER_1K` / `LLM_OUTPUT_COST_PER_1K` / `EMBEDDING_COST_PER_1K` | fallback legacy usato solo se `model_pricing.yaml` non esiste |
| `OTEL_CAPTURE_IO=false` | non salva input/output sugli span OTel generici |
| `OTEL_REDACT_PII=true` | maschera le email nei log strutturati |

**Listino prezzi modificabile (`model_pricing.yaml`).** Il file nella root del
progetto contiene `currency`, `default`, `aliases` e `models`; ogni modello ha
`input_per_1k`, `output_per_1k` e/o `embedding_per_1k`. Il file viene riletto
automaticamente quando cambia (nessun riavvio): un operatore può aggiornare i
prezzi mentre l'app è in esecuzione. Per verificare il contenuto caricato:

```bash
python -m app.observability.pricing
```

Se il file manca o è invalido, l'app usa le variabili `LLM_*_COST_PER_1K` e
continua a funzionare. Le metriche `idra.llm.cost` e i `cost_details` Langfuse
assumono USD.

### 8.6 OpenTelemetry (traces, metrics, logs)

Il bootstrap è in `app/observability/otel.py`. Langfuse e il collector OTLP
generico condividono lo stesso `TracerProvider` e le stesse **Resource
attributes**: in questa installazione `service.name=idra-ai-chatbot-observation`,
`service.namespace=idra-collector`, `service.version=1.0.0`,
`deployment.environment.name=development`, `service.instance.id` generato a ogni
processo, `host.name` dal container e `deployment.platform.name=docker` da
`OTEL_RESOURCE_ATTRIBUTES`. Langfuse riceve anche `langfuse.environment` e
`langfuse.release`, le sole Resource attributes che usa per filtrare le trace.

Configurazione applicata:

- Langfuse **self-hosted** raggiunto direttamente da `LANGFUSE_BASE_URL`
  (`http://langfuse-web:3000` nella rete Docker `langfuse_default`).
- Collector OTLP/HTTP generico su `OTEL_EXPORTER_OTLP_ENDPOINT`; dal container
  app vale `http://host.docker.internal:4318` (il `localhost` del container non
  è l'host), per un processo locale `http://localhost:4318`.
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`, traces/metrics/logs tutti via OTLP.
- Sampling head-based al 100% (`OTEL_SAMPLE_RATE=1.0`): adatto a un deployment
  piccolo con budget di 10M token/mese; per volumi maggiori usare tail sampling
  nel collector o abbassare il ratio.
- Log al massimo dettaglio (`LOG_LEVEL=DEBUG`) con correlazione
  `trace_id`/`span_id`, batch OTel configurati esplicitamente (BSP/BLRP/metriche)
  e limiti SDK per non troncare prompt/documenti ma evitare payload enormi.

Se Langfuse non è configurato ma `OTEL_EXPORTER_OTLP_ENDPOINT` sì, la pipeline
continua a produrre span generici (adapter interno con le stesse span/fasi):
nessun codice applicativo cambia.

- **Traces** (`OTEL_TRACES_EXPORTER=otlp|none`): span HTTP server, span applicativi
  (`chat`, `retrieval.*`, `llm.*`, `ingestion.*`, `db.*`) con propagazione W3C
  `traceparent` in ingresso e in uscita (header `x-trace-id` nella risposta).
- **Metrics** (`OTEL_METRICS_EXPORTER=otlp|prometheus|none`): `idra.chat.requests`,
  `idra.chat.duration`, `http.server.request.duration`,
  `gen_ai.client.operation.duration`, `gen_ai.client.token.usage`, `idra.llm.cost`,
  `idra.retrieval.duration`, `idra.retrieval.candidates`, `idra.db.operation.duration`,
  `idra.ingestion.duration`, `idra.ingestion.entities`, `idra.errors`.
  Con `prometheus` viene esposto `http://0.0.0.0:9464/metrics`.
- **Logs** (`OTEL_LOGS_EXPORTER=otlp|none`): structlog/JSON già configurato; un
  `LoggingHandler` OTel invia gli stessi record al collector. Ogni riga include
  `trace_id` e `span_id` per correlare log e trace.
- **Auto-instrumentation** opzionale (`OTEL_INSTRUMENT_HTTPX/PYMONGO/PYMYSQL`):
  aggiunge span client HTTP e DB senza modificare il codice. Se i pacchetti non
  sono installati viene loggato un debug e l'app continua.
- **Health**: `/health` riporta anche `langfuse`; `/metrics` resta il JSON
  applicativo, separato dal endpoint Prometheus.

Esempio collector minimo (OTLP/HTTP):

```yaml
# docker-compose.yml (estratto)
otel-collector:
  image: otel/opentelemetry-collector-contrib:latest
  command: ["--config=/etc/otelcol/config.yaml"]
  volumes: ["./otel-collector.yaml:/etc/otelcol/config.yaml"]
  ports: ["4318:4318"]
```

```yaml
# otel-collector.yaml (estratto)
receivers:
  otlp:
    protocols: { http: { endpoint: 0.0.0.0:4318 } }
exporters:
  debug: {}
  prometheus: { endpoint: 0.0.0.0:8888 }
service:
  pipelines:
    traces:  { receivers: [otlp], exporters: [debug] }
    metrics: { receivers: [otlp], exporters: [prometheus] }
    logs:    { receivers: [otlp], exporters: [debug] }
```

### 8.7 Semantic conventions, errori e qualità

- **GenAI**: `gen_ai.system`/`gen_ai.provider.name`, `gen_ai.operation.name`
  (`chat`/`embeddings`), `gen_ai.request.model`, `gen_ai.response.model`,
  `gen_ai.usage.input_tokens`/`output_tokens`, `gen_ai.response.finish_reasons`,
  `http.request.resend_count` sui retry.
- **HTTP/DB**: `http.request.method`, `http.route`, `http.response.status_code`,
  `server.address`/`server.port`, `db.system.name`, `db.operation.name`,
  `db.namespace`, `db.collection.name`.
- **OpenInference**: `openinference.span.kind` (LLM/EMBEDDING/RETRIEVER/RERANKER/
  TOOL/AGENT/GUARDRAIL/CHAIN), compatibile con Phoenix e altri backend.
- **Errori/retry**: status `ERROR`, evento `exception`, eventi `retry` con
  `attempt`/`reason`; metriche `idra.errors{component,error.type}`.
- **Qualità (score Langfuse + metriche OTel)**: oltre agli score esistenti,
  `retrieval_candidates_total`, `retrieval_precision_proxy`,
  `retrieval_score_gap`, `retrieval_latency_ms`, `answer_chars`, `context_chars`,
  `prompt_chars`, `answer_has_sources`, `language_method`, `prompt_type`.
  Recall@k/MRR/nDCG e groundedness richiedono un dataset di ground-truth o un
  LLM-as-judge: non sono calcolabili senza dati etichettati.
- **Governance**: `OTEL_SAMPLE_RATE` per il sampling head-based (tail sampling nel
  collector), `LANGFUSE_CAPTURE_IO`/`OTEL_CAPTURE_IO` per non inviare prompt,
  `OTEL_REDACT_PII` per le email nei log; audit/retention restano nel backend
  (Langfuse/ClickHouse o collector) secondo la policy aziendale.

### 8.8 Configurazione applicata e dati residui

La configurazione scelta è già applicata in `.env.example` (locale) e
`.env.test` (Docker). Non servono altre modifiche al codice per il funzionamento
standard:

1. **Backend**: Langfuse self-hosted (nessun cloud, nessun header di auth OTLP
   verso il collector).
2. **Collector**: `http://host.docker.internal:4318` dal container,
   `http://localhost:4318` da un processo locale, protocollo `http/protobuf`.
3. **Identità**: `idra-ai-chatbot-observation` / `idra-collector` / `1.0.0` /
   `development`; release Langfuse `1.0.0`.
4. **Privacy**: dati di libero accesso, cattura completa di input/output
   (`OTEL_CAPTURE_IO=true`, `LANGFUSE_CAPTURE_IO=true`, `OTEL_REDACT_PII=false`).
5. **Costi**: listino in `model_pricing.yaml`, modificabile dall'operatore a
   caldo; valori iniziali a 0 per i modelli locali e da compilare per i modelli
   remoti.
6. **Volume**: budget dichiarato 10.000.000 token/mese per tutti i modelli LLM
   remoti, con avviso all'80% e critico al 100% (vedi 8.9).
7. **Log**: livello `DEBUG` e limiti SDK configurati per il massimo dettaglio.

Restano da fornire solo se cambia l'infrastruttura o la policy:

- endpoint/credenziali reali se il collector non è più su `localhost:4318`;
- retention e residenza dati del backend Langfuse/collector;
- eventuale pseudonimizzazione di `user_id` o mascheramento di campi;
- canali di notifica per gli alert (Slack/email/PagerDuty) e relativo routing;
- prezzi reali per i modelli remoti nel file `model_pricing.yaml`.

### 8.9 SLO, budget e alert

Le soglie per il deployment piccolo sono in `observability/slo.yaml`:

| Area | Obiettivo |
|------|-----------|
| Chat | p95 ≤ 15 s, p99 ≤ 30 s, error rate ≤ 2% |
| LLM | error rate ≤ 1% |
| Retrieval | p95 ≤ 1,5 s, precision proxy ≥ 0,5 |
| Ingestion | success rate ≥ 98%, p95 ≤ 15 min |
| Osservabilità | export OTLP riuscito ≥ 99%, ≤ 100 span persi/ora |
| Budget | 10M token/mese (warning 80%, critico 100%) |

Il file contiene anche le espressioni PromQL di esempio per latenza chat,
error rate, latenza retrieval, ingestion lenta, budget token e fallimenti di
export del collector. Le soglie non bloccano l'app: il budget è monitorato, non
applicato con un hard stop.

---

## 9. Testing

### 9.1 Unit Test

```bash
# Installazione dipendenze test
pip install pytest pytest-asyncio pytest-mock httpx

# Esecuzione
pytest tests/ -v --cov=app
```

> Test di observability (`tests/test_observability.py`) e ingestion MySQL
> (`tests/test_mysql_ingestion.py`) usano OpenTelemetry `InMemorySpanExporter`:
> non richiedono un server Langfuse attivo.
> Test health endpoint: `pytest tests/test_health.py -v`.

---

## 10. Verifica Produzione

### 10.1 Smoke Test API

```bash
# Health
curl http://localhost:3000/health

# Chat (JWT bearer)
curl -X POST http://localhost:3000/chat -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"message": "Quali dataset sulla qualità dell''aria a Torino?", "conversationId": "conv-test"}'
# La risposta include "traceId" per il feedback e la ricerca in Langfuse.
```

### 10.2 Verifica Modelli

```bash
# Embedding (endpoint /api/embed nelle versioni recenti di Ollama; /api/embeddings è legacy)
curl http://localhost:11434/api/embed \
  -d '{"model": "mxbai-embed-large", "input": "test"}'

# Chat
curl http://localhost:11434/api/chat \
  -d '{"model": "mixtral", "messages": [{"role": "user", "content": "test"}]}'
```

### 10.3 Verifica Trace end-to-end

1. Eseguire una richiesta `/chat` e annotare il `traceId` della risposta.
2. Aprire `http://localhost:3100` (o filtrare per traceId in UI) e verificare la trace
   `chat` con i suoi span (`retrieval.search`, `llm.answer`, ...) e gli score.
3. Inviare un feedback e verificare lo score `user_feedback` sulla stessa trace.

---

## 11. Monitoraggio

### 11.1 Log

```bash
# App logs
docker logs -f idra_ai_chatbot

# MongoDB logs
docker logs -f orion_mongo

# ChromaDB logs
docker logs -f rag_chroma

# Langfuse logs
docker compose -f observability/langfuse/docker-compose.yml logs -f langfuse-web langfuse-worker
```

### 11.2 Metriche (Langfuse)

Il punto unico per metriche e statistiche è la UI/API Langfuse (sez. 8): p95 latency,
token usage, no-result rate, exit path, feedback ratio, statistiche ingestion
(entità indicizzate/invariate/errori, secondi per entità p50/p95) sono già registrati
come score/metadata per trace e run.

---

## 12. Backup & Recovery

```bash
# MongoDB dump
docker exec orion_mongo mongodump --db orion --out /backup

# ChromaDB persiste su volume `chromadb_data`
docker run --rm -v chromadb_data:/chroma/chroma -v $(pwd):/backup alpine tar czf /backup/chromadb_backup.tar.gz /chroma/chroma

# Langfuse (volumi del compose in observability/langfuse/)
docker run --rm -v langfuse_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/langfuse_postgres.tar.gz /data
docker run --rm -v langfuse_clickhouse_data:/data -v $(pwd):/backup alpine tar czf /backup/langfuse_clickhouse.tar.gz /data
docker run --rm -v langfuse_minio_data:/data -v $(pwd):/backup alpine tar czf /backup/langfuse_minio.tar.gz /data
```

> I nomi esatti dei volumi dipendono dal nome del progetto compose (`docker volume ls | grep langfuse`).

---

## 13. Troubleshooting

| Problema | Soluzione |
|----------|-----------|
| ChromaDB connection refused | Verificare `CHROMA_HOST` punti a `rag_chroma` in docker-compose |
| Ollama OOM | Impostare `OLLAMA_KEEP_ALIVE=10m` per offloaded model |
| MongoDB auth failed | Impostare `MONGO_INITDB_ROOT_USERNAME/PASSWORD` |
| Embedding dimension mismatch | Full reindex (`{"fullReindex": true}`) dopo cambio modello embedding |
| Docker Desktop hang su build/pull | Aumentare RAM allocata (min. 12 GB, vedi sezione 1) |
| Langfuse UI non risponde / porte non bindate | Aggiungere `HOSTNAME=0.0.0.0` al servizio `langfuse-web` e ricreare il container (sez. 5.3) |
| `langfuse: DOWN` in /health | Verificare che langfuse-web sia sulla rete del chatbot e `LANGFUSE_BASE_URL=http://langfuse-web:3000` |
| `mysql: DOWN` in /health | Verificare rete condivisa con il backend Idra e credenziali `MYSQL_*`; verificare `INGEST_SOURCES` contenga `mysql` |
| Ingestion 409 | Un run è già in corso: interrogare `/admin/ingestion/status` |
| Ingestion 503 | Preflight modelli Ollama fallito: `docker exec ollama ollama pull <modello mancante>` |
| API Langfuse `traces` 404/not available | Langfuse v4 `events_only`: gli endpoint legacy trace sono disabilitati, usare la UI (sez. 8.3) |
| `ModuleNotFoundError opentelemetry...common._exporter_metrics` | Conflitto SDK OTel con chromadb: aggiornare `opentelemetry-exporter-otlp-proto-grpc`/`-otlp` a >= 1.45.2 |

---

## 14. Sicurezza

### 14.1 JWT Secret

```bash
# Genera segreto
openssl rand -hex 32
# Impostare in .env.test (o .env.production se si modifica il compose)
```

### 14.2 Network Isolation

`docker-compose-example.yml` definisce già una rete dedicata `rag_network` (default del
progetto), che isola i container dal resto dell'host. In produzione:

- non esporre pubblicamente le porte di `mongodb` (27017), `chromadb` (8000),
  `langfuse` (3100) e `mysql` (3306): rimuoverle o bindarle a `127.0.0.1`;
- il container `app` ha bisogno di connessioni in uscita verso: orion_mongo, rag_chroma,
  ollama, il MySQL del backend Idra e langfuse-web (tutte reti Docker interne).

### 14.3 Dati osservati

Con `LANGFUSE_CAPTURE_IO=false` Langfuse non archivia contenuti (prompt, risposte,
documenti) ma solo metriche e metadata: configurazione consigliata per dati sensibili
(compliance GDPR, infrastruttura 100% on-premise).

---

## 15. Scaling

### 15.1 Horizontal (Multi-Tenant)

- Un collection ChromaDB per tenant
- Sharding MongoDB per `tenant_id`
- Load balancer con routing per tenant

### 15.2 Verticale

- Aumentare RAM per modelli più grandi
- GPU con CUDA support (se disponibile)

---

## 16. Comandi Utili

```bash
# Build immagine
docker-compose build

# Ricostruisci
docker-compose up -d --build

# Stop
docker-compose down

# Pulisci volumi
docker-compose down -v

# Shell nel container
docker exec -it idra_ai_chatbot bash
```

---

## 17. Variabili Ambiente Riferimento

| Variabile | Descrizione | Default |
|-----------|-----------|---------|
| PORT | Porta FastAPI | 3000 |
| MONGODB_URI | Connessione MongoDB | mongodb://localhost:27017/orion |
| CHROMA_HOST | Host ChromaDB | localhost |
| CHROMA_PORT | Porta ChromaDB | 8000 |
| OLLAMA_HOST | Host Ollama | localhost |
| OLLAMA_PORT | Porta Ollama | 11434 |
| OLLAMA_EMBEDDING_MODEL | Modello embedding | mxbai-embed-large |
| OLLAMA_LLM_MODEL | Modello LLM | mixtral |
| OLLAMA_ENRICHMENT_MODEL | Modello enrichment semantico ingestion | llama3.1 |
| JWT_SECRET | Chiave JWT | - |
| JWT_EXPIRES_IN | Scadenza JWT | 1h |
| ADMIN_TOKEN | Token (plain) per endpoint /admin/* | - |
| DEFAULT_TENANT_ID | Tenant default | default-tenant |
| INGEST_SOURCES | Sorgenti ingestion (mysql, mongo_nbs, mongo) | (legacy mongo) |
| MYSQL_HOST | Host MySQL Idra-Backend | - |
| MYSQL_PORT | Porta MySQL | 3306 |
| MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE | Credenziali MySQL | - |
| LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY | Chiavi progetto Langfuse (tracing off se assenti) | - |
| LANGFUSE_BASE_URL | Endpoint Langfuse dal container app | - |
| LANGFUSE_TRACING_ENVIRONMENT | Environment etichettato sulle trace | development |
| LANGFUSE_RELEASE | Release etichettata sulle trace | - |
| LANGFUSE_SAMPLE_RATE | Campionamento trace (0-1) | 1.0 |
| LANGFUSE_CAPTURE_IO | Salva prompt/risposte/documenti | true |
| LANGFUSE_MAX_IO_CHARS | Troncamento input/output salvati | 20000 |
| LANGFUSE_TRACE_INGESTION_ENTITIES | Trace per singola entità in ingestion | true |
| MODEL_PRICING_FILE | Percorso del listino modificabile (default `model_pricing.yaml`) | `model_pricing.yaml` |
| LLM_INPUT_COST_PER_1K / LLM_OUTPUT_COST_PER_1K | Fallback legacy costo LLM (usato solo senza file) | 0 |
| EMBEDDING_COST_PER_1K | Fallback legacy costo embedding | 0 |
| OTEL_ENABLED | Master switch OpenTelemetry | true |
| OTEL_SDK_DISABLED | Disattiva l'SDK OTel a monte (debug) | false |
| OTEL_SERVICE_NAME / OTEL_SERVICE_VERSION / OTEL_SERVICE_NAMESPACE | Identità del servizio | idra-ai-chatbot-observation / 1.0.0 / idra-collector |
| OTEL_DEPLOYMENT_ENVIRONMENT | Environment sulle Resource | development |
| OTEL_SERVICE_INSTANCE_ID | ID istanza (vuoto = UUID per processo) | - |
| OTEL_RESOURCE_ATTRIBUTES | Attributi Resource extra | deployment.platform.name=docker |
| OTEL_EXPORTER_OTLP_ENDPOINT | Collector OTLP/HTTP (base) | http://localhost:4318 (Docker: host.docker.internal) |
| OTEL_EXPORTER_OTLP_PROTOCOL | Protocollo OTLP | http/protobuf |
| OTEL_EXPORTER_OTLP_TRACES_ENDPOINT / METRICS_ENDPOINT / LOGS_ENDPOINT | Override per signal | - |
| OTEL_EXPORTER_OTLP_HEADERS | Header auth collector (`k=v,k2=v2`) | - |
| OTEL_EXPORTER_TIMEOUT | Timeout export OTLP (s) | 10 |
| OTEL_TRACES_EXPORTER / OTEL_METRICS_EXPORTER / OTEL_LOGS_EXPORTER | `otlp`/`prometheus`/`none` | otlp |
| OTEL_SAMPLE_RATE | Campionamento head-based (0-1) | 1.0 |
| OTEL_PROMETHEUS_PORT | Porta scrape Prometheus | 9464 |
| OTEL_INSTRUMENT_HTTPX / PYMONGO / PYMYSQL | Auto-instrumentation | true |
| OTEL_CAPTURE_IO / OTEL_REDACT_PII | Input/output sugli span OTel / maschera email nei log | true / false |
| OTEL_HTTP_EXCLUDE_PATHS | Path esclusi dagli span HTTP | - |
| OTEL_BSP_* / OTEL_BLRP_* | Coda, batch, delay e timeout di span/log | 2048 / 512 / 5000 ms / 30000 ms |
| OTEL_METRIC_EXPORT_INTERVAL / TIMEOUT | Intervallo e timeout export metriche | 60000 / 30000 ms |
| OTEL_ATTRIBUTE_* / OTEL_SPAN_* / OTEL_LOGRECORD_* | Limiti SDK per attributi, eventi e link | 512 / 65535 / 256 / 128 |
| OTEL_MONTHLY_TOKEN_BUDGET | Budget token/mese per dashboard e alert | 10000000 |
| LOG_LEVEL | Livello log applicativo | DEBUG |

---

## 18. Struttura Progetto

```
/app
├── main.py                    # FastAPI entry point (health, feedback, admin)
├── auth.py                    # JWT + admin token
├── mongodb/
│   ├── client.py              # Motor client
│   └── repositories.py        # Dataset/conversations/feedback queries (read-only su orion)
├── mysql/
│   ├── client.py              # Connessione MySQL (PyMySQL)
│   └── repositories.py        # Lettura tabelle dcat_* Idra-Backend
├── chroma/
│   └── client.py              # ChromaDB client
├── ollama/
│   └── client.py              # LLM/embedding API (instrumentata)
├── retrieval/
│   └── reranker/reranker.py   # Reranker (instrumentato)
├── chat/
│   ├── services/              # chat_service, chat_followup (instrumentati)
│   ├── controllers/           # chat_controller (root trace + score)
│   └── dto/models.py          # ChatResponse (traceId), FeedbackRequest
├── ingestion/
│   ├── service.py             # Pipeline ingestion (trace run + per-entity, metriche fasi/token)
│   ├── semantic_enricher.py   # Enrichment LLM (instrumentato)
│   └── sources.py             # Sorgenti: mysql / mongo_nbs / mongo
├── prompts/
│   ├── __init__.py            # Loader + prompt metadata (nome/versione)
│   └── *.md                   # Prompt di sistema e dei task LLM
├── observability/
│   ├── tracing.py             # Langfuse helper + metriche/token/costi (no-op senza chiavi)
│   ├── pricing.py             # Listino modelli con hot reload + validazione CLI
│   └── otel.py                # OTel bootstrap: Resource, OTLP/Prometheus, log, propagazione
└── static/index.html          # UI chat + pulsanti feedback
/model_pricing.yaml            # Listino prezzi modificabile dall'operatore
/observability/slo.yaml        # SLO, budget 10M token e regole di alert
/observability/langfuse/
├── docker-compose.yml         # Stack Langfuse v4 (postgres, clickhouse, minio, redis)
└── .env.example               # Template chiavi/config
/tests
├── test_observability.py      # Tracing (InMemorySpanExporter, no server richiesto)
└── test_mysql_ingestion.py    # Sorgente MySQL, hash incrementale, stale removal
```

---

## 19. Ringraziamenti

Progetto sviluppato per compliance GDPR con infrastruttura 100% on-premise
(osservabilità inclusa: Langfuse self-hosted).
