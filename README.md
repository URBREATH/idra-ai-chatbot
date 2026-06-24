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
/src
    /ingestion
    /retrieval
    /generation
    /tenancy
    /api
    /monitoring

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
