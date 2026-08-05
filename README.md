# Idra AI Chatbot

A conversational assistant for a **European open data catalog**, built on a Retrieval-Augmented
Generation (RAG) pipeline. Instead of relying only on what a language model learned during
training, the chatbot first retrieves the relevant resources from its own knowledge base (the
catalog's datasets and entities) and then feeds them to a locally-run model, which answers while
staying grounded in that data. This keeps answers factual and traceable, with links back to the
source resources.

---

## Overview

The system takes a user question, turns it into a vector, searches a vector store for the most
similar catalog resources, assembles them into context, and asks a local language model to produce
a grounded answer together with its sources. When nothing matches, it does not stay silent: it
explains that no resources were found and suggests concrete ways to refine the search, always
pointing only to openly-licensed data. Conversations are remembered for a short, privacy-bounded
window so that follow-up questions keep their context.

All models run locally through [Ollama](https://ollama.com), so no data leaves the deployment for
inference.

---

## Architecture

The application is a FastAPI service that orchestrates three supporting services, all running as
Docker containers on the same Compose network. A fourth service (Keycloak) is optional and only
needed where verified identity is required.

| Service        | Role                                                      | Internal port |
|----------------|-----------------------------------------------------------|:-------------:|
| **app**        | FastAPI application: chat API and RAG orchestration       | 3000          |
| **mongo**      | Conversational memory + source entities/datasets          | 27017         |
| **chromadb**   | Vector store (embeddings), API v2                         | 8000          |
| **ollama**     | Local models: embeddings + answer generation              | 11434         |
| keycloak *(opt.)* | JWT issuer for authenticated, multi-tenant access      | 8080          |

Within the Docker network, containers reach each other **by service name and internal port** (for
example `mongo:27017`, `chromadb:8000`, `ollama:11434`) — not by any port published to the host.

---

## How it works (RAG pipeline)

A single request flows through four steps:

1. **Embed the query** — the question is turned into a 1024-dimension vector by Ollama using
   `mxbai-embed-large`. The embedding model is fixed, because the Chroma collection is indexed at
   that dimensionality.
2. **Vector search** — ChromaDB returns the resources most semantically similar to the query.
3. **Assemble context** — the retrieved resources are formatted, optionally prepended with recent
   conversation history.
4. **Generate** — Ollama produces the final answer from the assembled prompt, grounded in the
   context, with a selectable generation model.

---

## Conversational memory

Memory is entirely a prompt-side mechanism: the model itself holds no state between requests. Every
message — both the user's and the assistant's — is stored as a document in MongoDB's
`conversations` collection, grouped by `conversationId`. On each new turn the most recent messages
of that conversation are re-injected into the prompt, giving the model the illusion of remembering.

Three conditions must all hold for memory to work: a valid JWT is present (its `sub` claim provides
the `userId` under which messages are saved), the `conversationId` stays the same across turns, and
the app reads and writes the same MongoDB instance being inspected. Without a token the chat still
answers, but nothing is persisted.

Memory is not permanent. Each message is created with a seven-day `expiresAt`, and a MongoDB TTL
index removes it automatically after that — a deliberate choice aligned with the GDPR right to
erasure (Art. 17). Note that the TTL background task runs roughly every 60 seconds, so deletion is
eventual rather than instantaneous.

---

## Tech stack

Python · FastAPI · MongoDB · ChromaDB (vector store) · Ollama (local LLMs) · Docker & Docker
Compose · JWT authentication.

---

## Recommended Project Structure

The application code is organized by responsibility, with one package per concern (ingestion,
retrieval, storage clients, and chat orchestration):

```text
app/
├── chat/
    └── controllers
    └── dto
    └── services
│   └── __init__.py
├── chroma/
│   ├── client.py
│   └── __init__.py
├── common/
│   ├── guards/
│   └── utils
├── conversation/
│   └── __init__.py
├── ingestion/
│   └── service.py
├── mongodb/
│   ├── client.py
│   └── repositories.py
├── retrieval/
│   └── __init__.py
├── ollama/
│   └── client.py
├── __init__.py
├── main.py
├── auth.py
├── tests/
│   ├── data/
│   └── repositories.py
```

---

## Prerequisites

Docker Engine with the Docker Compose plugin. Because the language models run locally, RAM is the
main constraint: on a 16 GB machine without a dedicated GPU, a 7B-class generation model
(e.g. `qwen2.5:7b`) is a sensible reference. A NVIDIA GPU with the NVIDIA Container Toolkit enables
hardware acceleration, but CPU-only inference works too.

---

## Quick start

The steps below get the stack running. For the full, verification-driven walkthrough (data import,
standalone Ollama, connectivity checks, troubleshooting) see the **Installation Guide**.

**1. Clone and configure.** Create a `.env.test` file next to `docker-compose-example.yml` — it must exist,
since Compose parses it even when starting a single service. The Installation Guide lists the
required settings and sensible values.

**2. Start MongoDB and import the source data:**

```bash
docker compose up -d mongo
docker compose exec -T mongo mongoimport \
  --db rag_platform --collection <collectionName> --jsonArray < entities.json
```

**3. Pull the models into Ollama** (embedding model is required and fixed; generation model is your
choice):

```bash
docker compose exec ollama ollama pull mxbai-embed-large
docker compose exec ollama ollama pull mistral-nemo
```

**4. Start the whole stack:**

```bash
docker compose up -d --build
curl -s http://localhost:3000/health
```

**5. Populate the vector store (ingestion)** and then ask a question:

```bash
export ADMIN_TOKEN="<value from .env.test>"

curl -s -X POST http://localhost:3000/admin/ingestion/run \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"fullReindex": true}'

curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:3000/chat \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'X-Tenant-Id: default-tenant' \
  -d '{"message":"have you got some datasets related to <select city>?", "conversationId":"memory_test001"}'
```

Copying data into MongoDB does **not** make it searchable on its own — you must run ingestion so the
resources are embedded into ChromaDB before the chat can retrieve anything.

---

## API

| Method & path                 | Description                                                   |
|-------------------------------|---------------------------------------------------------------|
| `POST /chat`                  | Ask a question; returns `answer`, `sources`, `conversationId` |
| `GET  /chat/{conversationId}` | Retrieve a conversation (ownership-checked, `403` otherwise)   |
| `GET  /models`                | List generation models available in Ollama                    |
| `POST /admin/ingestion/run`   | Run ingestion (requires `ADMIN_TOKEN`)                         |
| `GET  /health`                | Reports the status of `mongo`, `chroma`, and `ollama`          |

FastAPI serves interactive API documentation automatically at `/docs` (Swagger UI) and `/redoc`,
with the raw schema at `/openapi.json` — the authoritative place to confirm exact request and
response fields.

The chat request body accepts `message`, and optionally `conversationId` (required for memory) and
`model`. Passing a valid user JWT via `Authorization: Bearer <token>` enables conversational memory;
`ADMIN_TOKEN` authorizes the admin routes only, not `/chat`.

---

## Health check

`GET /health` actively probes each dependency rather than returning a fixed value: it pings MongoDB,
hits ChromaDB's `/api/v2/heartbeat`, and queries Ollama's `/api/tags`. If every dependency responds
it returns `status: "UP"` with HTTP `200`; if any is unreachable it returns `status: "DEGRADED"`
with HTTP `503`, so monitors and orchestrators can react to the status code.

## License

*(Add the project's license here — e.g. Apache-2.0 or EUPL, per the URBREATH project's conventions.)*
