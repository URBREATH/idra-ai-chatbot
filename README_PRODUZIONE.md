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

### 3.1 File d'ambiente

> **Attenzione (verificato nel codice)**: il `docker-compose-example.yml` presente nella root
> del progetto carica realmente `env_file: .env.test` per il servizio `app` (non
> `.env.production` come indicato in precedenza in questo documento). Il compose
> avvia anche un servizio `ollama` proprio (container `ollama`, volume `ollama_data`),
> quindi **non** è più necessario `host.docker.internal`/`extra_hosts` per Ollama.
> Prima di andare in produzione:
> - rinominare il file creato qui sotto in `.env.test` (per usarlo così com'è),
>   **oppure** modificare `docker-compose-example.yml` per puntare a `.env.production`;
> - eseguire il pull dei modelli nel container `ollama` (vedi sezione 4).

Creare il file nella root del progetto:

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

# JWT (CAMBIARE IN PRODUZIONE)
JWT_SECRET=<generare con: openssl rand -hex 32>
JWT_EXPIRES_IN=1h

# Admin token per gli endpoint /admin/* (confronto diretto, NON è un JWT)
ADMIN_TOKEN=<generare con: openssl rand -hex 32>

# Tenant
DEFAULT_TENANT_ID=default-tenant
```

> Note:
> - Ollama gira come servizio containerizzato (`ollama`) definito in `docker-compose-example.yml`:
>   nessuna configurazione di rete aggiuntiva (`extra_hosts`/`host.docker.internal`) necessaria.
> - Se si preferisce usare un'istanza Ollama già installata sull'host (es. per sfruttare una
>   GPU non passata al container), impostare `OLLAMA_HOST=host.docker.internal`, rimuovere il
>   servizio `ollama` da `docker-compose-example.yml` e aggiungere
>   `extra_hosts: ["host.docker.internal:host-gateway"]` al servizio `app` (necessario su Linux).

---

## 4. Preparazione Modelli Ollama

```bash
# Embedding model (nel container ollama del compose)
docker exec ollama ollama pull mxbai-embed-large

# LLM principale
docker exec ollama ollama pull mixtral

# Verifica
docker exec ollama ollama list
```

> I modelli vengono scaricati nel volume Docker `ollama_data` (persistente tra i riavvii).
> Il container `app` accede a Ollama via rete Docker interna (`ollama:11434`),
> pertanto non è necessario montare i modelli all'interno del container `app`.

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
| orion_mongo | 27017 | MongoDB |
| rag_chroma | 8000 | ChromaDB |

---

## 6. Inizializzazione Database

> **Attenzione (verificato nel codice)**: questa non è una collection creata/gestita
> da questo applicativo. `app/mongodb/repositories.py` **legge soltanto** (nessun
> insert/update) dalle collection `entities` e `deleted_datasets` del database
> `orion`, che devono già esistere e contenere entità NGSI-LD nel formato descritto
> in `DATABASE_SCHEMA.md` (tipicamente popolate da un **FIWARE Orion Context
> Broker** esterno, non da un file `datasets.json` generico). Il blocco seguente
> è utile solo per creare dati di **test locale** con lo schema corretto.

### 6.1 MongoDB - Dati di Test (schema Orion/NGSI-LD)

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
> `ObjectId` semplice) e i campi `attrs`, `modDate`, `creDate` come da schema Orion
> (vedi `DATABASE_SCHEMA.md`). Il formato "un documento piatto per dataset" non è
> supportato dal codice attuale.

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
  -d '{"model": "mixtral", "messages": [{"role": "user", "content": "test"}]}'
```

---

## 10. Monitoraggio

### 10.1 Log

```bash
# App logs
docker logs -f idra_ai_chatbot

# MongoDB logs
docker logs -f orion_mongo

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
docker exec orion_mongo mongodump --db orion --out /backup

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

`docker-compose-example.yml` definisce già una rete dedicata `rag_network` (default del progetto),
che isola i container (`app`, `mongodb`, `chromadb`) dal resto dell'host.
Verificare che le porte di `mongodb` (27017) e `chromadb` (8000) non siano esposte
pubblicamente in produzione (rimuovere o bindare a `127.0.0.1` le porte in `docker-compose-example.yml`).

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
| MONGODB_URI | Connessione MongoDB | mongodb://localhost:27017/orion |
| CHROMA_HOST | Host ChromaDB | localhost |
| CHROMA_PORT | Porta ChromaDB | 8000 |
| OLLAMA_HOST | Host Ollama | localhost |
| OLLAMA_PORT | Porta Ollama | 11434 |
| OLLAMA_EMBEDDING_MODEL | Modello embedding | mxbai-embed-large |
| OLLAMA_LLM_MODEL | Modello LLM | mixtral |
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