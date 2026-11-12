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

**Ollama**: ogni `generate_embedding` / `generate_completion` produce una observation
`embedding`/`generation` con model, model_parameters, usage (prompt/output/total tokens,
durations) e timing (eval_ms, tokens/second).

**Ingestion** — trace `ingestion.run` per run (sessione `ingestion-<run_id>`) con span
`read_index`, `full_reindex_delete`, `load_sources`, `plan`, `chroma_upsert`,
`remove_stale`, più **una trace per entità** (`ingestion.entity`, disattivabile con
`LANGFUSE_TRACE_INGESTION_ENTITIES=false`) con span `ingestion.semantic_enrichment` e
score `enrichment_terms`/`enrichment_status`/`chunks`. Score a livello di run:
`entities_indexed`, `entities_unchanged`, `entities_errors`, `chunks_upserted`,
`entities_deleted`, più p50/p95 secondi per entità nei metadata.

### 8.2 Feedback utente

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

### 8.3 Dashboard e query

- UI: `http://localhost:3100` (login: credenziali `LANGFUSE_INIT_USER_*`).
- Filtri utili: `session.id = conv-<id>`, tag `chat`, tag `ingestion`, tag
  `tenant:<tenant_id>`, environment `development` (`LANGFUSE_TRACING_ENVIRONMENT`).
- Grafici consigliati: `retrieval_best_distance` (p95), `exit_path=no_result` (rate),
  `user_feedback` (ratio positivo), durata `llm.answer`, `tokens_per_second`.
- API v4 `events_only`: gli endpoint legacy `GET /api/public/traces` sono disabilitati;
  le trace sono esportate via OTLP (`POST /api/public/otel/v1/traces`) e consultate da UI.
  Gli score restano inviabili via `POST /api/public/scores` (l'SDK li gestisce).

### 8.4 Configurazione privacy/volume

| Variabile | Effetto |
|-----------|---------|
| `LANGFUSE_CAPTURE_IO=false` | non salva prompt/risposte/documenti, solo metriche e metadata (consigliato se i dati sono sensibili) |
| `LANGFUSE_MAX_IO_CHARS` | troncamento input/output salvati (default 20000) |
| `LANGFUSE_SAMPLE_RATE` | campionamento trace (es. `0.25` = 25% delle richieste) |
| `LANGFUSE_TRACE_INGESTION_ENTITIES=false` | solo trace run-level durante l'ingestion (riduce volume) |

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
│   ├── service.py             # Pipeline ingestion (trace run + per-entity)
│   ├── semantic_enricher.py   # Enrichment LLM (instrumentato)
│   └── sources.py             # Sorgenti: mysql / mongo_nbs / mongo
├── observability/
│   └── tracing.py             # Langfuse/OTel helpers (no-op senza chiavi)
└── static/index.html          # UI chat + pulsanti feedback
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
