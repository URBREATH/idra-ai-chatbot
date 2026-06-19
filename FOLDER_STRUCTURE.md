# Recommended Project Structure

```text
app/

├── app.module.ts

├── common/
│   ├── constants/
│   ├── exceptions/
│   ├── interceptors/
│   ├── guards/
│   ├── decorators/
│   └── utils/

├── auth/
│   ├── keycloak/
│   ├── guards/
│   ├── dto/
│   └── auth.module.ts

├── chat/
│   ├── controllers/
│   ├── services/
│   ├── dto/
│   └── chat.module.ts

├── retrieval/
│   ├── embeddings/
│   ├── reranker/
│   ├── vector-search/
│   └── retrieval.module.ts

├── ingestion/
│   ├── extractors/
│   ├── enrichers/
│   ├── chunking/
│   ├── embeddings/
│   ├── chroma/
│   └── ingestion.module.ts

├── chroma/
│   ├── collections/
│   ├── repositories/
│   └── chroma.module.ts

├── ollama/
│   ├── embeddings/
│   ├── llm/
│   └── ollama.module.ts

├── mongodb/
│   ├── repositories/
│   ├── entities/
│   └── mongodb.module.ts

├── monitoring/
│   ├── metrics/
│   ├── logging/
│   └── monitoring.module.ts

├── users/
│   ├── controllers/
│   ├── services/
│   └── users.module.ts

└── admin/
    ├── controllers/
    ├── services/
    └── admin.module.ts
```

---

# Security Roles

```text
SUPER_ADMIN
TENANT_ADMIN
USER
READ_ONLY
```

---

# Architectural Rules

1. No business logic in controllers.
2. All Chroma access through repositories.
3. All Ollama access through dedicated services.
4. DTO validation required.
5. Structured logging only.
6. No direct Mongo queries from controllers.
7. Tenant resolution performed before retrieval.
