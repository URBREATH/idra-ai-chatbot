# Implementation Plan

## Milestone 1 - Infrastructure

### Tasks

* [x] Initialize Python project (Poetry)
* [x] Configure Python
* [x] Configure Ruff
* [x] Configure Docker files
* [x] Configure process manager (uvicorn)
* [x] Configure environment management

### Acceptance Criteria

* Backend starts correctly
* Configuration loaded
* Health endpoint available

---

## Milestone 2 - Mongo Integration

### Tasks

* [x] Mongo connection
* [x] Dataset repository
* [x] Incremental dataset query
* [x] Deleted dataset query

### Acceptance Criteria

* Datasets retrieved successfully

---

## Milestone 3 - Ollama Integration

### Tasks

* [x] Configure Ollama client
* [x] Embedding service
* [x] Chat service
* [x] Batch embedding support

### Acceptance Criteria

* Embedding generation works
* LLM responses generated

---

## Milestone 4 - ChromaDB Integration

### Tasks

* [x] Chroma client
* [x] Collection manager
* [x] Tenant collection resolver
* [x] Upsert service
* [x] Delete service

### Acceptance Criteria

* Vectors stored and retrieved

---

## Milestone 5 - Ingestion Pipeline

### Tasks

* [x] Dataset extractor
* [x] Semantic enricher
* [x] Recursive crawler
* [x] Payload builder
* [x] Chunking engine
* [x] Embedding generation
* [x] Chroma upsert

### Acceptance Criteria

* Full ingestion completed

---

## Milestone 6 - Retrieval Pipeline

### Tasks

* [x] Query embedding generation
* [x] Metadata filtering
* [x] Similarity search
* [x] Reranking service
* [x] Context assembly

### Acceptance Criteria

* Relevant datasets returned

---

## Milestone 7 - LLM Generation

### Tasks

* [x] Prompt templates
* [x] Context injection
* [x] Conversation memory
* [x] No-result workflow

### Acceptance Criteria

* Hallucination-safe responses

---

## Milestone 8 - Multi-Tenant Support

### Tasks

* [x] Tenant resolver (`app/common/guards/tenant_guard.py`)
* [x] Collection routing
* [x] Isolation tests

### Acceptance Criteria

* No cross-tenant leakage

---

## Milestone 9 - Monitoring

### Tasks

* [x] Structured logging (structlog)
* [x] Metrics collection (`GET /metrics`)
* [x] Feedback collection (`POST /chat/feedback` con contatori)

### Acceptance Criteria

* Metrics visible
* Feedback persisted

---

## Milestone 10 - Validation

### Tasks

* [x] Golden dataset creation
* [ ] RAGAS evaluation
* [x] Performance testing
* [x] Load testing

### Acceptance Criteria

* Precision targets achieved
* Performance targets achieved

---

# Definition of Done

A release is considered complete when:

* All milestones pass acceptance criteria
* Retrieval precision validated
* Tenant isolation validated
* RAGAS evaluation completed
* Monitoring operational
