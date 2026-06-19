# Architecture Decision Records

## ADR-001: Use ChromaDB

### Status

Accepted

### Context

A lightweight local vector database is required.

### Decision

Use ChromaDB as standalone service.

### Consequences

Positive:

* Easy deployment
* Native LangChain support
* CPU-friendly

Negative:

* Fewer enterprise features than Milvus

---

## ADR-002: Use Ollama

### Status

Accepted

### Context

Need local model serving.

### Decision

Use Ollama.

### Consequences

Positive:

* Simple deployment
* Native REST API
* GGUF support

---

## ADR-003: Use mxbai-embed-large

### Status

Accepted

### Context

Need multilingual embeddings.

### Decision

Use mxbai-embed-large.

### Consequences

Positive:

* Strong retrieval quality
* Low memory footprint

---

## ADR-004: Use EngGPT

### Status

Accepted

### Context

Need Italian-focused model.

### Decision

Use enggpt-2-16b-a3b.

### Consequences

Positive:

* Italian language optimization
* Local execution

---

## ADR-005: One Collection per Tenant

### Status

Accepted

### Context

Strong isolation requirements.

### Decision

Each tenant receives a dedicated Chroma collection.

### Consequences

Positive:

* Maximum isolation
* Simple authorization model

Negative:

* More collections to manage

---

## ADR-006: Retrieval Before Generation

### Status

Accepted

### Context

Hallucinations must be minimized.

### Decision

LLM can only use retrieved context.

### Consequences

Positive:

* Deterministic answers
* Higher trustworthiness

---

## ADR-007: Cross Encoder Reranking

### Status

Accepted

### Context

Vector search alone is insufficient.

### Decision

Use ms-marco-MiniLM-L-6-v2.

### Consequences

Positive:

* Better relevance
* Better context precision

Negative:

* Additional latency

---

## ADR-008: CPU-Only Deployment

### Status

Accepted

### Context

No GPU infrastructure available.

### Decision

Entire platform runs on CPU.

### Consequences

Positive:

* Lower infrastructure complexity
* Easier deployment

Negative:

* Higher inference latency
