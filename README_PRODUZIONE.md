# Idra AI Chatbot - Guida alla Produzione

Platform: Local Multi-Tenant RAG per metadati europei (NGSI-LD, DCAT-AP, SDMX).

---

## 1. Prerequisiti di Sistema

| Requisito | Versione Minima |
|-----------|-----------------|
| OS | Linux (Ubuntu 22.04+ consigliato) |
| CPU | x86_64 con supporto AVX2 |
| RAM | 150 GB minimo (modello LLM 16B) |
| Docker | 24.x + Docker Compose v2 |
| Ollama | 0.1.32+ |
| Python | 3.12 (eseguito all'interno del container) |

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

### 3.1 File `.env.production`

Il file `.env.production` viene caricato automaticamente dal servizio `app` di `docker-compose.yml`
(tramite `env_file: .env.production`). Creare il file nella root del progetto:

```bash
# App
PORT=3000

# MongoDB
MONGODB_URI=mongodb://rag_mongodb:27017/rag_platform

# ChromaDB
CHROMA_HOST=rag_chroma
CHROMA_PORT=8000

# Ollama (in esecuzione sull'host)
OLLAMA_HOST=host.docker.internal
OLLAMA_PORT=11434
OLLAMA_EMBEDDING_MODEL=mxbai-embed-large
OLLAMA_LLM_MODEL=enggpt-2-16b-a3b

# JWT (CAMBIARE IN PRODUZIONE)
JWT_SECRET=<generare con: openssl rand -hex 32>
JWT_EXPIRES_IN=1h

# Admin token per gli endpoint /admin/* (confronto diretto, NON è un JWT)
ADMIN_TOKEN=<generare con: openssl rand -hex 32>

# Tenant
DEFAULT_TENANT_ID=default-tenant
```

> Note:
> - Su Linux, `host.docker.internal` viene risolto tramite `extra_hosts: ["host.docker.internal:host-gateway"]`
>   già configurato nel servizio `app` di `docker-compose.yml`.
> - Per Ollama è necessario esporre l'host (`0.0.0.0`) impostando `OLLAMA_HOST=0.0.0.0:11434` sull'host.

---

## 4. Preparazione Modelli Ollama

```bash
# Embedding model
ollama pull mxbai-embed-large

# LLM principale
ollama pull enggpt-2-16b-a3b

# Verifica
ollama list
```

> I modelli vengono scaricati nella directory `~/.ollama/models` sull'host.
> Il container `app` accede a Ollama via rete (`host.docker.internal:11434`),
> pertanto non è necessario montare i modelli all'interno del container.

---

## 5. Deployment con Docker Compose

### 5.1 Docker Compose Produzione

```bash
# Avvio servizi
docker-compose up -d

# Verifica stato
docker-compose ps

# Log
docker-compose logs -f app
```

### 5.2 Servizi

| Servizio | Porta | Descrizione |
|----------|-------|-------------|
| idra_ai_chatbot | 3000 | FastAPI App |
| rag_mongodb | 27017 | MongoDB |
| rag_chroma | 8000 | ChromaDB |

---

## 6. Inizializzazione Database

### 6.1 MongoDB - Import Dati

```bash
# Copia il file JSON con i dataset nel container
docker cp datasets.json rag_mongodb:/datasets.json

# Import dei documenti nella collection `datasets`
docker exec -i rag_mongodb mongoimport \
  --db rag_platform --collection datasets \
  --file /datasets.json --jsonArray

# Creazione indici (incluso tenant_id, usato dalle query in app/mongodb/repositories.py)
docker exec -i rag_mongodb mongosh rag_platform <<EOF
db.datasets.createIndex({ "_id.type": 1 })
db.datasets.createIndex({ "publisher": 1 })
db.datasets.createIndex({ "theme": 1 })
db.datasets.createIndex({ "tenant_id": 1, "updatedAt": 1 })
db.deleted_datasets.createIndex({ "tenant_id": 1, "deletedAt": 1 })
db.chat_feedback.createIndex({ "tenantId": 1 })
EOF
```

> Il file `datasets.json` non è incluso nel repository: deve essere fornito dall'operatore.
> Ogni documento deve contenere i campi `tenant_id` e `updatedAt` per supportare l'ingestion incrementale.

### 6.2 Verifica Connessioni

```bash
# Health check
curl http://localhost:3000/health

# Response attesa (i sotto-stati sono attualmente segnaposto "UNKNOWN"):
# {"status":"UP","mongo":"UNKNOWN","chroma":"UNKNOWN","ollama":"UNKNOWN"}
```

> L'endpoint `/health` (vedi `app/main.py`) restituisce sempre `status: UP` e i sotto-stati
> come `UNKNOWN`: non esegue ancora check reali su Mongo/Chroma/Ollama.
> Per verificare effettivamente le dipendenze, usare i comandi delle sezioni 9.2 e 10.

---

## 7. Ingestione Dati

### 7.1 Ingestione Manuale

```bash
# Endpoint (richiede ADMIN_TOKEN, NON un JWT - vedi app/auth.py)
curl -X POST http://localhost:3000/admin/ingestion/run \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fullReindex": false}'
```

> Il percorso reale è `/admin/ingestion/run` (nessun prefisso `/api/v1`).
> `$ADMIN_TOKEN` è il valore plain-text impostato in `.env.production`.

### 7.2 Ingestione Programmata (Cron)

```bash
# Aggiungi al crontab del server
0 3 * * * docker exec idra_ai_chatbot python -c "import asyncio; from app.ingestion.service import ingest_tenant; asyncio.run(ingest_tenant('default-tenant'))"
```

> Il container `idra_ai_chatbot` deve essere già in esecuzione; le variabili d'ambiente
> (MONGODB_URI, CHROMA_HOST, OLLAMA_HOST...) sono ereditate dal container stesso.
> In alternativa, è possibile invocare l'endpoint HTTP `/admin/ingestion/run` con `curl`
> per beneficiare della stessa code path del container.

---

## 8. Testing

### 8.1 Unit Test

```bash
# Installazione dipendenze test
pip install pytest pytest-asyncio pytest-mock httpx

# Esecuzione
pytest tests/ -v --cov=app
```

### 8.2 Test Health Endpoint

```bash
pytest tests/test_health.py -v
```

---

## 9. Verifica Produzione

### 9.1 Smoke Test API

```bash
# Health
curl http://localhost:3000/health

# Chat (endpoint placeholder)
curl -X POST http://localhost:3000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'
```

### 9.2 Verifica Modelli

```bash
# Embedding (endpoint /api/embed nelle versioni recenti di Ollama; /api/embeddings è legacy)
curl http://localhost:11434/api/embed \
  -d '{"model": "mxbai-embed-large", "input": "test"}'

# Chat
curl http://localhost:11434/api/chat \
  -d '{"model": "enggpt-2-16b-a3b", "messages": [{"role": "user", "content": "test"}]}'
```

---

## 10. Monitoraggio

### 10.1 Log

```bash
# App logs
docker logs -f idra_ai_chatbot

# MongoDB logs
docker logs -f rag_mongodb

# ChromaDB logs
docker logs -f rag_chroma
```

### 10.2 Metriche (implementare)

- p95 latency
- retrieval count
- rerank duration
- embedding duration
- LLM duration
- no-result rate

---

## 11. Backup & Recovery

```bash
# MongoDB dump
docker exec rag_mongodb mongodump --db rag_platform --out /backup

# ChromaDB persiste su volume `chromadb_data`
docker run --rm -v chromadb_data:/chroma/chroma -v $(pwd):/backup alpine tar czf /backup/chromadb_backup.tar.gz /chroma/chroma
```

---

## 12. Troubleshooting

| Problema | Soluzione |
|----------|-----------|
| ChromaDB connection refused | Verificare `CHROMA_HOST` punti a `rag_chroma` in docker-compose |
| Ollama OOM | Impostare `OLLAMA_KEEP_ALIVE=10m` per offloaded model |
| MongoDB auth failed | Impostare `MONGO_INITDB_ROOT_USERNAME/PASSWORD` |
| Embedding dimension mismatch | Verificare modello Chroma compatibile con embedding model |

---

## 13. Sicurezza

### 13.1 JWT Secret

```bash
# Genera segreto
openssl rand -hex 32
# Impostare in .env.production
```

### 13.2 Network Isolation

`docker-compose.yml` definisce già una rete dedicata `rag_network` (default del progetto),
che isola i container (`app`, `mongodb`, `chromadb`) dal resto dell'host.
Verificare che le porte di `mongodb` (27017) e `chromadb` (8000) non siano esposte
pubblicamente in produzione (rimuovere o bindare a `127.0.0.1` le porte in `docker-compose.yml`).

---

## 14. Scaling

### 14.1 Horizontal (Multi-Tenant)

- Un collection ChromaDB per tenant
- Sharding MongoDB per `tenant_id`
- Load balancer con routing per tenant

### 14.2 Verticale

- Aumentare RAM per modelli più grandi
- GPU con CUDA support (se disponibile)

---

## 15. Comandi Utili

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

## 16. Variabili Ambiente Riferimento

| Variabile | Descrizione | Default |
|-----------|-----------|---------|
| PORT | Porta FastAPI | 3000 |
| MONGODB_URI | Connessione MongoDB | mongodb://localhost:27017/rag_platform |
| CHROMA_HOST | Host ChromaDB | localhost |
| CHROMA_PORT | Porta ChromaDB | 8000 |
| OLLAMA_HOST | Host Ollama | localhost |
| OLLAMA_PORT | Porta Ollama | 11434 |
| OLLAMA_EMBEDDING_MODEL | Modello embedding | mxbai-embed-large |
| OLLAMA_LLM_MODEL | Modello LLM | enggpt-2-16b-a3b |
| JWT_SECRET | Chiave JWT | - |
| JWT_EXPIRES_IN | Scadenza JWT | 1h |
| ADMIN_TOKEN | Token (plain) per endpoint /admin/* | - |
| DEFAULT_TENANT_ID | Tenant default | default-tenant |

---

## 17. Struttura Progetto

```
/app
├── main.py              # FastAPI entry point
├── mongodb/
│   ├── client.py        # Motor client
│   └── repositories.py  # Dataset queries
├── chroma/
│   └── client.py        # ChromaDB client
├── ollama/
│   └── client.py        # LLM/embedding API
├── ingestion/
│   └── service.py       # Ingestion pipeline
└── tests/
    └── conftest.py      # Test fixtures
```

---

## 18. Ringraziamenti

Progetto sviluppato per compliance GDPR con infrastruttura 100% on-premise.