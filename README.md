# Local Multi-Tenant RAG Platform for European Metadata

## Overview

This project implements a fully on-premise Retrieval Augmented Generation (RAG) platform for querying and exploring European metadata repositories based on:

* NGSI-LD
* DCAT-AP
* SDMX
* ISTAT datasets

The system operates entirely on local infrastructure and is designed to comply with GDPR requirements.

Key characteristics:

* CPU-only deployment
* Multi-tenant architecture
* Local embedding generation
* Local LLM inference
* Zero-hallucination response policy
* Incremental ingestion pipeline
* ChromaDB vector search

---

## Goals

### Functional Goals

* Explore datasets using natural language.
* Search across metadata repositories.
* Support conversational interaction.
* Return only information contained in indexed datasets.

### Non-Functional Goals

* Full GDPR compliance.
* On-premise execution.
* No external AI services.
* Tenant isolation.
* High retrieval precision.

---

## Technology Stack

| Layer            | Technology             |
| ---------------- | ---------------------- |
| Backend          | FastAPI + LangChain    |
| Source Database  | MongoDB                |
| Vector Database  | ChromaDB               |
| Inference Engine | Ollama                 |
| Embeddings       | mxbai-embed-large      |
| LLM              | enggpt-2-16b-a3b       |
| Scheduler        | cron                  |
| Evaluation       | RAGAS                  |

---

## High-Level Architecture

MongoDB → Ingestion Pipeline → Embeddings → ChromaDB → Retrieval → Reranker → EngGPT → User

---

## Repository Structure

```text
/app
  main.py                  # FastAPI application with endpoints
  ingestion/               # Ingestion pipeline
    service.py             # Ingestion orchestration
    payload_builder.py     # Builds payloads from datasets
    semantic_enricher.py   # LLM-based semantic enrichment
    technical_crawler.py   # Extracts SDMX technical terms
    chunker.py             # Splits payloads into chunks
  chroma/                  # ChromaDB integration
    client.py              # Collection management
  ollama/                  # Ollama API client
    client.py              # Embedding and chat endpoints
  mongodb/                 # MongoDB integration
    client.py              # Database connection
    repositories.py        # Dataset queries
  retrieval/               # Retrieval pipeline (TODO)
  chat/                    # Chat functionality (TODO)
  monitoring/              # Metrics and logging (TODO)
/docs
  README.md
  ARCHITECTURE.md
  ADR.md
  IMPLEMENTATION_PLAN.md
```

---

## Core Principles

1. Retrieval before generation.
2. No external knowledge.
3. Tenant isolation by collection.
4. Deterministic responses.
5. Explainable architecture.

---

## Deployment Requirements

* Linux Server
* ≥150 GB RAM
* AVX2 support
* Ollama
* ChromaDB
* MongoDB

See ARCHITECTURE.md for implementation details.

---

## Local Setup with Docker

### Prerequisites

* Docker Desktop (Compose v2 enabled)
* At least 16 GB RAM for local tests (more for larger Ollama models)

### 1. Create local env file

Copy `.env.docker.example` to `.env.docker` and adjust values if needed.

### 2. Bootstrap local stack (recommended on Windows)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local\bootstrap.ps1
```

This command will:

* start MongoDB, ChromaDB, Ollama and API
* create `.env.docker` if missing
* pull Ollama embedding/LLM models configured in `.env.docker`

### 3. Manual startup (alternative)

```powershell
copy .env.docker.example .env.docker
docker compose -f docker-compose.local.yml --env-file .env.docker up -d --build
docker exec idra_ollama_local ollama pull mxbai-embed-large
docker exec idra_ollama_local ollama pull enggpt-2-16b-a3b
```

### 4. Verify services

* API health: `http://localhost:3000/health`
* Metrics: `http://localhost:3000/metrics`
* Chroma service: `http://localhost:8000`
* Ollama tags: `http://localhost:11434/api/tags`

### 5. Stop stack

```powershell
docker compose -f docker-compose.local.yml --env-file .env.docker down
```
