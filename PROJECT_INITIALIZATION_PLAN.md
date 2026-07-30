# Project Initialization Plan

> **Documento storico**: descrive il piano *iniziale* di avvio del progetto e non
> riflette necessariamente lo stato attuale del codice. In particolare il nome
> del database MongoDB e' realmente `orion` (non `rag_platform`) con un'unica
> collection `entities` popolata da un Orion Context Broker esterno, non collection
> separate per tipo. Per lo schema e la configurazione realmente in uso vedere
> [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md), [README.md](README.md) e
> [README_PRODUZIONE.md](README_PRODUZIONE.md).

This document outlines the steps to initialize the Local Multi-Tenant RAG Platform for European Metadata from scratch.

## Prerequisites

Ensure the following are installed on your system:

- Python (>=3.12)
- pPoetry or Poetry (we'll use pnom)
- Docker and Docker Compose
- Git
- Ollama (for local LLM serving)
- ChromaDB (will be run via Docker)
- MongoDB (will be run via Docker)

## Step 1: Repository Setup

1. Clone the repository (if not already cloned)
2. Navigate to the project root
3. Verify the presence of documentation files (README.md, ARCHITECTURE.md, etc.)

## Step 2: Initialize Python Project

1. Initialize a new Python project:
   ```bash
   Poetry init -y
   ```
   or
   ```bash
   pPoetry init
   ```

2. Install core dependencies:
   ```bash
   poetry add fastapi motor langchain chromadb
   ```

3. Install development dependencies:
   ```bash
   poetry add -D ruff mypy pytest
   ```

4. Create Python configuration:
   ```bash
   python -m venv .venv
   ```
   Adjust `tsconfig.json` as needed (set `outDir` to `./dist`, `rootDir` to `./src`, etc.)

5. Configure ESLint and Prettier:
   ```bash
   ruff init
   ```
   Choose appropriate options for Python (PEP8, etc.)

## Step 3: Create Folder Structure

Create the directory structure as specified in `FOLDER_STRUCTURE.md`:

```
app/
├── main.py
├── ingestion/
│   └── service.py
├── retrieval/
│   └── __init__.py
├── chroma/
│   ├── client.py
│   └── __init__.py
├── ollama/
│   └── client.py
├── mongodb/
│   ├── client.py
│   └── repositories.py
├── monitoring/
│   └── __init__.py
├── chat/
│   └── __init__.py
└── ... (additional packages as needed)
```

## Step 4: Configuration Files

Create the following configuration files:

### `.env`
```
# MongoDB
MONGODB_URI=mongodb://localhost:27017/rag_platform

# ChromaDB
CHROMA_HOST=localhost
CHROMA_PORT=8000

# Ollama
OLLAMA_HOST=localhost
OLLAMA_PORT=11434
OLLAMA_EMBEDDING_MODEL=mxbai-embed-large
OLLAMA_LLM_MODEL=mixtral

# Server
PORT=3000
ENV=development

# JWT
JWT_SECRET=your-secret-key
JWT_EXPIRES_IN=1h

# Tenant
DEFAULT_TENANT_ID=default-tenant
```

### `docker-compose.yml`
```yaml
version: '3.8'

services:
  mongodb:
    image: mongo:latest
    container_name: rag_mongodb
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db
    environment:
      - MONGO_INITDB_DATABASE=rag_platform

  chromadb:
    image: chromadb/chroma:latest
    container_name: rag_chromadb
    ports:
      - "8000:8000"
    volumes:
      - chromadb_data:/chroma/chroma

  # Note: Ollama is typically installed locally, not via Docker
    # but you can use the ollama/ollama image if preferred

volumes:
  mongodb_data:
  chromadb_data:
```

## Step 5: Implement Core Modules

Following the architecture and milestones from `IMPLEMENTATION_PLAN.md`, implement each module:

### Milestone 1: Infrastructure
- Create `app/main.py` as the entry point
- Set up FastAPI server
- Configure FastAPI middleware (CORS, security headers)
- Set up environment variable loading (python-dotenv)
- Create health check endpoint

### Milestone 2: Mongo Integration
- Create MongoDB connection utility in `app/mongodb/`
- Define MongoDB models using Motor (asynchronous ODM) for datasets, distributions, catalogs, organizations, services (based on `DATABASE_SCHEMA.md`)
- Create repository classes for each entity type
- Implement incremental dataset queries

### Milestone 3: Ollama Integration
- Create Ollama client service in `app/ollama/`
- Implement embedding service using `mxbai-embed-large`
- Implement chat service using `mixtral`
- Add batch embedding support

### Milestone 4: ChromaDB Integration
- Create ChromaDB client in `app/chroma/`
- Implement collection manager (one collection per tenant)
- Implement tenant collection resolver
- Create upsert and delete services for vectors

### Milestone 5: Ingestion Pipeline
- Implement dataset extractor (read from MongoDB)
- Semantic enricher (using Ollama for concept expansion)
- Technical crawler (for SDMX/DCAT-AP structure)
- Payload builder (combining semantic, technical, description blocks)
- Chunking engine (by SDMX dimension, max 512 tokens)
- Embedding generation (using Ollama embeddings)
- ChromaDB upsert service

### Milestone 6: Retrieval Pipeline
- Query embedding generation
- Metadata filtering (tenant, theme, publisher, geo)
- Vector search in ChromaDB (n_results=10)
- Reranking service (using ms-marco-MiniLM-L-6-v2)
- Context assembly (top 3-5 chunks)
- Deduplication and context formatting

### Milestone 7: LLM Generation
- Prompt templates for RAG
- Context injection into prompts
- Conversation memory (store recent interactions)
- No-result workflow (fallback responses)
- Hallucination prevention (strict adherence to retrieved context)

### Milestone 8: Multi-Tenant Support
- Tenant resolver (extract from JWT or request headers)
- Collection routing (map tenant to Chroma collection)
- Isolation tests (ensure no cross-tenant data leakage)

### Milestone 9: Monitoring
- Structured logging (structlog)
- Metrics collection (latency, counts, durations)
- Feedback collection endpoint
- Health checks for all services

### Milestone 10: Validation
- Create golden dataset for testing
- Implement RAGAS evaluation
- Performance testing (load testing with artillery or k6)
- Optimize for precision and latency targets

## Step 6: API Implementation

Implement the API endpoints as defined in `API_SPEC.md` and `OPENAPI.yaml`:

- POST `/chat` - Chat endpoint
- GET `/chat/{conversationId}` - Conversation history
- POST `/chat/feedback` - Feedback submission
- POST `/admin/ingestion/run` - Trigger ingestion
- GET `/admin/ingestion/status` - Ingestion status
- GET `/users/me` - User profile
- GET `/health` - Health check

## Step 7: Security and Authentication

- Integrate Keycloak for JWT validation
- Implement role-based access control (SUPER_ADMIN, TENANT_ADMIN, USER, READ_ONLY)
- Protect admin endpoints with appropriate roles
- Validate JWT middleware

## Step 8: Testing

1. Write unit tests for each service using Jest or Vitest
2. Write integration tests for API endpoints
3. Set up test database connections
4. Implement test fixtures and mocks

## Step 9: Documentation and Code Quality

1. Generate API docs from OAS using Swagger UI
2. Maintain ADRs for architectural decisions
3. Keep implementation plan updated
4. Enforce code quality with ESLint and Prettier
5. Add pre-commit hooks (husky, lint-staged)

## Step 10: Deployment Preparation

1. Create Dockerfile for the Python application
2. Update docker-compose.yml to include the app service
3. Create Kubernetes manifests if needed
4. Set up CI/CD pipeline (GitHub Actions, GitLab CI)
5. Create deployment scripts

## Next Steps

After completing the initialization plan:

1. Begin implementation following the milestones
2. Regularly update the IMPLEMENTATION_PLAN.md with progress
3. Conduct code reviews and architectural reviews
4. Perform validation testing against acceptance criteria
5. Prepare for production deployment

---

*This plan is based on the existing documentation in the repository and should be adjusted as the project evolves.*