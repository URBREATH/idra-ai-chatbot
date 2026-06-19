# Internal API Specification

Base URL

```text
/api/v1
```

Authentication:

```text
Authorization: Bearer <jwt>
```

Provider:

```text
Keycloak
```

---

# Chat Endpoint

## POST /chat

Primary endpoint for the Angular frontend.

### Request

```json
{
  "message": "Show datasets about air quality",
  "conversationId": "uuid"
}
```

---

### Response

```json
{
  "answer": "Several datasets are available regarding air quality anomalies.",

  "sources": [
    {
      "title": "NO2 air quality anomalies",
      "datasetId": "urn:ngsi-ld:DistributionDCAT-AP:id:123",
      "publisher": "BEOPEN",
      "url": "https://..."
    }
  ],

  "conversationId": "uuid"
}
```

---

# Conversation History

## GET /chat/{conversationId}

Returns recent messages.

---

# Feedback

## POST /chat/feedback

Request

```json
{
  "conversationId": "uuid",

  "rating": "positive"
}
```

---

# Ingestion

## POST /admin/ingestion/run

Roles:

```text
SUPER_ADMIN
TENANT_ADMIN
```

Request:

```json
{
  "fullReindex": false
}
```

Response:

```json
{
  "status": "started"
}
```

---

# Collection Status

## GET /admin/ingestion/status

Response

```json
{
  "running": true,

  "processed": 534,

  "remaining": 231
}
```

---

# User Profile

## GET /users/me

Response

```json
{
  "id": "user-id",

  "roles": [
    "USER"
  ],

  "tenantId": "tenant-id"
}
```

---

# Health

## GET /health

Response

```json
{
  "status": "UP",

  "mongo": "UP",

  "chroma": "UP",

  "ollama": "UP"
}
```
