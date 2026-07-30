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

Superseded by ADR-009

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

---

## ADR-009: Replace EngGPT with Mixtral

### Status

Accepted

### Context

`enggpt-2-16b-a3b` (ADR-004) risultava non coerente con i requisiti effettivi del
progetto (qualità/coerenza delle risposte non adeguata all'uso previsto).

### Decision

Sostituire il modello LLM configurato in `OLLAMA_LLM_MODEL` con `mixtral` in tutti
i punti di codice, configurazione e documentazione che referenziavano
`enggpt-2-16b-a3b`.

### Consequences

Positive:

* Modello ampiamente supportato da Ollama, community più ampia
* Migliore qualità generale di generazione rispetto a EngGPT

Negative:

* Richiede un nuovo `ollama pull mixtral` su ogni ambiente (locale, docker, produzione)
* Footprint di memoria/CPU da rivalidare (Mixtral è un modello Mixture-of-Experts,
  il consumo di RAM effettivo va verificato rispetto ai requisiti in ARCHITECTURE.md)
