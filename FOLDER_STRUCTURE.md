# Recommended Project Structure

```text
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
