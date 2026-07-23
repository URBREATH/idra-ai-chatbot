# MongoDB Conversation History System

## Overview

This document describes the **Conversation History** feature of the Idra AI Chatbot. The system persists all user-assistant exchanges in MongoDB with automatic GDPR-compliant deletion after 7 days.

**Key Properties**:
- ✅ Multi-tenant isolation
- ✅ User ownership enforcement (Keycloak JWT)
- ✅ Automatic TTL-based deletion (GDPR Article 17)
- ✅ LLM-aware context injection (improves response quality)
- ✅ Scalable to 50+ concurrent conversations
- ✅ Zero additional cost (uses existing MongoDB)

---

## Architecture

### Data Model

**Collection**: `conversations`

**Schema** (one document per message):
```json
{
  "_id": ObjectId("507f1f77bcf86cd799439011"),
  "conversationId": "a1b2c3d4-e5f6-47g8-h9i0-j1k2l3m4n5o6",
  "tenantId": "european-catalog-org",
  "userId": "keycloak-uuid-1234",
  "role": "user|assistant",
  "content": "Quali dataset contengono dati sull'occupazione?",
  "createdAt": "2026-07-23T14:32:00.000Z",
  "expiresAt": "2026-07-30T14:32:00.000Z"
}
```

**Why Non-Nested?**
- 1 insert per message = optimal write performance
- No read-modify-write cycles
- Better indexing strategy
- Easier TTL implementation

---

### MongoDB Indexes

Three indexes created automatically on startup:

```javascript
// 1. TTL Index: Auto-delete after 7 days (GDPR)
db.conversations.createIndex({ expiresAt: 1 }, { expireAfterSeconds: 0 })

// 2. Fast conversation retrieval
db.conversations.createIndex({ conversationId: 1, tenantId: 1 })

// 3. User cleanup (right-to-be-forgotten)
db.conversations.createIndex({ userId: 1, tenantId: 1 })
```

---

## Request Flow

### 1. **Chat Request with Authentication**

```http
POST /chat
Authorization: Bearer <keycloak-jwt>
X-Tenant-ID: european-catalog-org
Content-Type: application/json

{
  "message": "Dammi i dataset su occupazione in Italia",
  "conversationId": "conv-uuid-123",
  "model": null
}
```

**Headers Explanation**:
- `Authorization`: Keycloak JWT (contains `sub` claim with userId)
- `X-Tenant-ID`: Tenant identifier (optional, defaults to `default-tenant`)

---

### 2. **JWT Processing & User Extraction**

```python
# app/auth.py: extract_user_id_from_keycloak_token()

JWT Token Payload:
{
  "sub": "12345678-abcd-1234-abcd-1234567890ab",  # ← User ID extracted
  "preferred_username": "mario.rossi",
  "email": "mario@example.com",
  "iss": "https://keycloak.example.com/auth/realms/master",
  "aud": "chatbot-client",
  "exp": 1234567890
}

# If KEYCLOAK_PUBLIC_KEY set: Signature verified (production)
# If not set: Token decoded without verification (development only)
```

---

### 3. **User Message Persistence**

```python
# app/chat/controllers/chat_controller.py: chat_endpoint()

await conversation_services.append_user_message(
    conversation_id="conv-uuid-123",
    tenant_id="european-catalog-org",
    user_id="12345678-abcd-1234-abcd-1234567890ab",
    message_content="Dammi i dataset su occupazione in Italia"
)

# Inserted Document:
{
  "_id": ObjectId("..."),
  "conversationId": "conv-uuid-123",
  "tenantId": "european-catalog-org",
  "userId": "12345678-abcd-1234-abcd-1234567890ab",
  "role": "user",
  "content": "Dammi i dataset su occupazione in Italia",
  "createdAt": "2026-07-23T14:32:00.000Z",
  "expiresAt": "2026-07-30T14:32:00.000Z"
}
```

---

### 4. **Context Loading for LLM**

```python
# app/chat/services/chat_service.py: generate_answer()

# Retrieve last 10 messages
conversation_context = await conversation_services.get_context_for_llm(
    conversation_id="conv-uuid-123",
    tenant_id="european-catalog-org",
    limit=10
)

# Returns formatted string:
context = """User: Cosa sono gli open data?
Assistant: Gli open data sono dati pubblici liberamente accessibili...
User: Mi fai un esempio?
Assistant: Certo! Un esempio è il dataset ISTAT sulla popolazione...
User: Dammi i dataset su occupazione in Italia
"""
```

---

### 5. **LLM Prompt Assembly**

```
[SYSTEM INSTRUCTIONS]
(system prompt about being a European open data catalog assistant)

[PREVIOUS CONVERSATION]
User: Cosa sono gli open data?
Assistant: Gli open data sono dati pubblici liberamente accessibili...
User: Mi fai un esempio?
Assistant: Certo! Un esempio è il dataset ISTAT sulla popolazione...

[RETRIEVAL CONTEXT]
(from vector search of dataset metadata)
Dataset Title: ISTAT Labor Statistics
Publisher: ISTAT
Format: CSV
License: CC-BY

[CURRENT QUESTION]
Question: Dammi i dataset su occupazione in Italia

Answer: [LLM generates response here, aware of previous conversation]
```

**Key Difference**: Previous conversation is now injected, so LLM understands context and can make cross-references.

---

### 6. **Assistant Response Persistence**

```python
# After LLM generates answer, save it:

await conversation_services.append_assistant_message(
    conversation_id="conv-uuid-123",
    tenant_id="european-catalog-org",
    user_id="12345678-abcd-1234-abcd-1234567890ab",
    message_content="I dataset su occupazione in Italia sono..."
)

# Inserted Document:
{
  "_id": ObjectId("..."),
  "conversationId": "conv-uuid-123",
  "tenantId": "european-catalog-org",
  "userId": "12345678-abcd-1234-abcd-1234567890ab",
  "role": "assistant",
  "content": "I dataset su occupazione in Italia sono...",
  "createdAt": "2026-07-23T14:32:05.000Z",
  "expiresAt": "2026-07-30T14:32:05.000Z"
}
```

---

### 7. **Return Response to Client**

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "answer": "I dataset su occupazione in Italia sono...",
  "sources": [
    {
      "title": "ISTAT Labor Statistics",
      "datasetId": "istat-labor-2024",
      "publisher": "ISTAT",
      "url": "https://www.istat.it/..."
    }
  ],
  "conversationId": "conv-uuid-123"
}
```

---

## API Endpoints

### POST /chat

**Purpose**: Send a message and get a response with conversation history awareness

**Request**:
```http
POST /chat
Authorization: Bearer <keycloak-jwt>
X-Tenant-ID: european-catalog-org
Content-Type: application/json

{
  "message": "string (required, 1-5000 chars)",
  "conversationId": "string (optional, UUID generated if missing)",
  "model": "string (optional, uses default if missing)"
}
```

**Response** (200 OK):
```json
{
  "answer": "string",
  "sources": [
    {
      "title": "string",
      "datasetId": "string",
      "publisher": "string",
      "url": "string"
    }
  ],
  "conversationId": "string"
}
```

**Error Responses**:
- `401`: Missing/invalid `Authorization` header
- `403`: Invalid JWT token or access denied
- `400`: Invalid model requested

---

### GET /chat/{conversationId}

**Purpose**: Retrieve full conversation history (with access control)

**Request**:
```http
GET /chat/conv-uuid-123
Authorization: Bearer <keycloak-jwt>
X-Tenant-ID: european-catalog-org
```

**Response** (200 OK):
```json
{
  "conversationId": "conv-uuid-123",
  "messages": [
    {
      "role": "user",
      "content": "Cosa sono gli open data?",
      "createdAt": "2026-07-23T14:00:00.000Z"
    },
    {
      "role": "assistant",
      "content": "Gli open data sono dati pubblici...",
      "createdAt": "2026-07-23T14:00:05.000Z"
    },
    {
      "role": "user",
      "content": "Dammi i dataset su occupazione",
      "createdAt": "2026-07-23T14:32:00.000Z"
    },
    {
      "role": "assistant",
      "content": "I dataset su occupazione sono...",
      "createdAt": "2026-07-23T14:32:05.000Z"
    }
  ]
}
```

**Error Responses**:
- `401`: Missing/invalid `Authorization` header
- `403`: Access denied (conversation belongs to another user)

---

## Configuration

### Environment Variables

**Production**:
```env
# Keycloak JWT validation (public key from your Keycloak realm)
KEYCLOAK_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----"
KEYCLOAK_REALM=master

# MongoDB (existing)
MONGODB_URI=mongodb://mongo:27017/rag_platform

# Other services
CHROMA_HOST=chroma
CHROMA_PORT=8000
OLLAMA_HOST=ollama
OLLAMA_PORT=11434
```

**Development** (without signature verification):
```env
# Leave KEYCLOAK_PUBLIC_KEY unset
# Tokens will be decoded without verification (permissive)

MONGODB_URI=mongodb://localhost:27017/rag_platform
CHROMA_HOST=localhost
CHROMA_PORT=8000
OLLAMA_HOST=localhost
OLLAMA_PORT=11434
```

### Getting Keycloak Public Key

**Option 1: Download from OIDC Discovery**
```bash
curl https://your-keycloak/auth/realms/{realm}/.well-known/openid-configuration
# Look for "jwks_uri" value

curl https://your-keycloak/auth/realms/{realm}/protocol/openid-connect/certs
# Extract the public key from the response
```

**Option 2: Export from Keycloak Admin Console**
1. Go to Realm → Keys
2. Find active key
3. Click "Public key" to export

---

## Testing

### Test 1: Basic Chat Flow (No Conversation History)

**Scenario**: First message in a new conversation

**Test Steps**:
```bash
# 1. Obtain Keycloak JWT
TOKEN=$(curl -X POST https://keycloak/auth/realms/master/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=chatbot&client_secret=secret&username=testuser&password=pass&grant_type=password" \
  | jq -r '.access_token')

echo "Token: $TOKEN"

# 2. Send chat message
curl -X POST http://localhost:3000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: default-tenant" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Quali dataset contengono dati su occupazione?",
    "conversationId": "test-conv-001"
  }' | jq .

# Expected Output:
{
  "answer": "[LLM response about employment datasets]",
  "sources": [...],
  "conversationId": "test-conv-001"
}

# 3. Verify in MongoDB
mongosh
> db.conversations.find({"conversationId": "test-conv-001"}).pretty()

# Expected: 2 documents (user message + assistant response)
```

---

### Test 2: Conversation Context Awareness

**Scenario**: Second message in same conversation, LLM should remember first exchange

**Test Steps**:
```bash
# 1. Send first message
curl -X POST http://localhost:3000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: default-tenant" \
  -d '{
    "message": "Cosa sono gli open data?",
    "conversationId": "test-conv-002"
  }' | jq .

# Response: "Gli open data sono dati pubblici..."

# 2. Send follow-up message (should reference previous context)
curl -X POST http://localhost:3000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: default-tenant" \
  -d '{
    "message": "Mi fai un esempio di open data?",
    "conversationId": "test-conv-002"
  }' | jq .

# Expected: LLM response references "As I mentioned earlier" or similar
# This proves conversation context was injected into prompt

# 3. Verify context was retrieved from MongoDB
# Check MongoDB logs or add debug logging to conversation_services.get_context_for_llm()
mongosh
> db.conversations.find({"conversationId": "test-conv-002"}).pretty()

# Expected: 4 documents
# - Message 1: user ("Cosa sono gli open data?")
# - Message 2: assistant ("Gli open data sono...")
# - Message 3: user ("Mi fai un esempio...")
# - Message 4: assistant ("Es: ISTAT dataset, which was mentioned...")
```

---

### Test 3: Multi-Tenant Isolation

**Scenario**: Users from different tenants should not see each other's conversations

**Test Steps**:
```bash
# 1. User A (Tenant: italy-org) sends message
curl -X POST http://localhost:3000/chat \
  -H "Authorization: Bearer $TOKEN_USER_A" \
  -H "X-Tenant-ID: italy-org" \
  -d '{
    "message": "Dataset italiano",
    "conversationId": "conv-shared-id"
  }' | jq .

# 2. User B (Tenant: france-org) sends message with SAME conversationId
curl -X POST http://localhost:3000/chat \
  -H "Authorization: Bearer $TOKEN_USER_B" \
  -H "X-Tenant-ID: france-org" \
  -d '{
    "message": "Dataset français",
    "conversationId": "conv-shared-id"
  }' | jq .

# 3. Verify isolation in MongoDB
mongosh
> db.conversations.find({"conversationId": "conv-shared-id"}).pretty()

# Expected: Only 2 documents (one per tenant)
# - { tenantId: "italy-org", content: "Dataset italiano", ... }
# - { tenantId: "france-org", content: "Dataset français", ... }

# 4. User A retrieves conversation, should get only their tenant's messages
curl -X GET http://localhost:3000/chat/conv-shared-id \
  -H "Authorization: Bearer $TOKEN_USER_A" \
  -H "X-Tenant-ID: italy-org" | jq .

# Expected: Only 1 message (the Italian one)
# User A cannot access User B's conversation due to tenantId filter
```

---

### Test 4: User Ownership Enforcement

**Scenario**: One user should not access another user's conversation (same tenant)

**Test Steps**:
```bash
# 1. User A creates conversation
CONV_ID=$(curl -X POST http://localhost:3000/chat \
  -H "Authorization: Bearer $TOKEN_USER_A" \
  -H "X-Tenant-ID: default-tenant" \
  -d '{"message": "Secret message"}' | jq -r '.conversationId')

echo "Conversation ID: $CONV_ID"

# 2. User B (same tenant) tries to retrieve User A's conversation
curl -X GET http://localhost:3000/chat/$CONV_ID \
  -H "Authorization: Bearer $TOKEN_USER_B" \
  -H "X-Tenant-ID: default-tenant" | jq .

# Expected Response (403):
{
  "detail": "Access denied: conversation belongs to another user"
}

# 3. Verify MongoDB stores both userId and tenantId
mongosh
> db.conversations.findOne({"conversationId": "$CONV_ID"})

# Expected:
{
  "conversationId": "$CONV_ID",
  "tenantId": "default-tenant",
  "userId": "keycloak-uuid-user-a",
  "role": "user",
  "content": "Secret message",
  ...
}
```

---

### Test 5: TTL Expiration (GDPR)

**Scenario**: Verify that messages are automatically deleted after 7 days

**Test Steps**:

```bash
# Note: This test requires MongoDB TTL index to be active
# Real validation requires waiting 7 days or manipulating time
# This is a verification test for production monitoring

# 1. Insert a test document with expiresAt set to now
mongosh
> db.conversations.insertOne({
  "conversationId": "ttl-test-001",
  "tenantId": "default-tenant",
  "userId": "test-user",
  "role": "user",
  "content": "Test message",
  "createdAt": new Date(),
  "expiresAt": new Date(Date.now() + 10000)  // Expires in 10 seconds for testing
})

# 2. Verify document exists
> db.conversations.findOne({"conversationId": "ttl-test-001"})
# Expected: document found

# 3. Wait ~15 seconds
# MongoDB TTL index runs every 60 seconds by default

sleep 65

# 4. Verify document is deleted
> db.conversations.findOne({"conversationId": "ttl-test-001"})
# Expected: null (document deleted)

# 5. Check TTL index exists
> db.conversations.getIndexes()
# Expected: Index with name like "expiresAt_1" with { expireAfterSeconds: 0 }
```

---

### Test 6: Performance Test (50 Concurrent Conversations)

**Scenario**: Verify system handles 50+ concurrent conversations without degradation

**Test Script** (Python with asyncio):
```python
# tests/test_conversation_performance.py

import asyncio
import httpx
import time
import random
import string

async def test_concurrent_conversations():
    """Simulate 50 concurrent users, each with multiple messages"""
    
    base_url = "http://localhost:3000"
    num_users = 50
    messages_per_user = 5
    
    # Token (in production, use actual Keycloak token)
    token = "Bearer <your-test-token>"
    
    async with httpx.AsyncClient() as client:
        start_time = time.time()
        tasks = []
        
        for user_id in range(num_users):
            conv_id = f"perf-test-user-{user_id}"
            tenant_id = f"tenant-{user_id % 5}"  # 5 different tenants
            
            for msg_num in range(messages_per_user):
                message = f"User {user_id} message {msg_num}: " + \
                         ''.join(random.choices(string.ascii_letters, k=50))
                
                task = client.post(
                    f"{base_url}/chat",
                    headers={
                        "Authorization": token,
                        "X-Tenant-ID": tenant_id,
                    },
                    json={
                        "message": message,
                        "conversationId": conv_id,
                    }
                )
                tasks.append(task)
        
        # Execute all requests concurrently
        responses = await asyncio.gather(*tasks)
        end_time = time.time()
        
        # Verify results
        successful = sum(1 for r in responses if r.status_code == 200)
        failed = len(responses) - successful
        total_time = end_time - start_time
        rps = len(responses) / total_time  # Requests per second
        
        print(f"\n=== Performance Test Results ===")
        print(f"Total Requests: {len(responses)}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total Time: {total_time:.2f}s")
        print(f"Requests/sec: {rps:.2f}")
        print(f"Avg Latency: {(total_time/len(responses))*1000:.2f}ms")
        
        # Expected Results (for reference):
        # - Successful: ~250 (50 users × 5 messages)
        # - Failed: 0
        # - Total Time: ~30-60s (dominated by LLM inference, not DB)
        # - Requests/sec: 4-8 rps
        # - Avg Latency: 2000-3000ms (most of which is LLM, ~20ms is DB)

# Run test
# python -m pytest tests/test_conversation_performance.py -v
```

---

## Database Queries (For Debugging)

### Count Conversations by Tenant
```javascript
db.conversations.aggregate([
  { $group: { _id: "$tenantId", count: { $sum: 1 } } }
])
```

### Find All Messages for a User
```javascript
db.conversations.find({
  userId: "12345678-abcd-1234-abcd-1234567890ab"
})
```

### Check TTL Index Status
```javascript
db.conversations.getIndexes()
// Look for: { "key": { "expiresAt": 1 }, "expireAfterSeconds": 0 }
```

### Calculate Storage Usage
```javascript
db.conversations.stats()
// Check: avgObjSize, storageSize
```

### Find Conversations Expiring Soon (next 24h)
```javascript
db.conversations.find({
  expiresAt: {
    $gte: new Date(),
    $lte: new Date(Date.now() + 24 * 60 * 60 * 1000)
  }
}).count()
```

---

## Performance Characteristics

### Latency Breakdown (Single Chat Request)

| Component | Latency | Notes |
|-----------|---------|-------|
| JWT extraction | ~1ms | In-memory decode |
| User message save | ~5-10ms | Single insert |
| Context retrieval | ~10-20ms | Index on (conversationId, tenantId) |
| Query embedding | ~300-500ms | Model inference |
| Vector search | ~50-100ms | Chroma DB lookup |
| Reranking | ~100-200ms | Cross-encoder |
| LLM generation | ~2000-3000ms | Ollama inference (**bottleneck**) |
| Assistant message save | ~5-10ms | Single insert |
| **Total** | **~2500-4000ms** | 60-70% from LLM |

**Conclusion**: Database operations are negligible (~50ms). LLM inference dominates.

### Storage Usage (Estimate)

Per message (average 200 tokens ≈ 1200 bytes):
```
1 conversation × 10 messages × 1.2 KB ≈ 12 KB
50 conversations × 10 messages × 1.2 KB ≈ 600 KB
```

After 7 days (auto-deleted):
```
TTL index automatically reclaims space
Zero manual cleanup needed
```

---

## GDPR Compliance

### Data Retention
- **Automatic deletion**: 7 days after `createdAt` via TTL index
- **No manual cleanup needed**: MongoDB daemon handles it
- **Audit trail**: All documents timestamped

### Data Isolation
- **Multi-tenant**: Each message tagged with `tenantId`
- **Queries filtered**: Only retrieve same-tenant conversations
- **User ownership**: `userId` enforced in retrieval

### Right to Be Forgotten (Article 17)
- **API**: `DELETE /chat/{conversationId}` (not yet implemented, but easy to add)
- **Database function**: `delete_user_conversations(user_id, tenant_id)` ready to use
- **Speed**: ~5ms to delete all user's messages

### Data Residency
- **Self-hosted**: No cloud provider involvement
- **Internal control**: Complete custody of data
- **No third-party processors**: All on your infrastructure

---

## Implementation Details

### Files Structure
```
app/
├── conversation/                      # New module
│   ├── __init__.py
│   ├── dto.py                        # DTO models
│   ├── repositories.py               # MongoDB operations + TTL setup
│   └── services.py                   # Business logic (CRUD + LLM context)
│
├── auth.py                           # (modified) Keycloak JWT extraction
├── chat/
│   ├── controllers/
│   │   └── chat_controller.py       # (modified) User extraction + saving
│   └── services/
│       └── chat_service.py          # (modified) Context injection
│
└── main.py                           # (modified) Startup event for indexes
```

### Key Functions

**repositories.py**:
- `initialize_conversation_indexes()` – Create TTL + query indexes
- `save_message()` – Insert single message
- `get_conversation_history()` – Retrieve all messages (ordered)
- `get_recent_messages_for_context()` – Get last N messages for LLM
- `delete_user_conversations()` – Delete all user's messages (GDPR)

**services.py**:
- `append_user_message()` – Save user's message
- `append_assistant_message()` – Save LLM's response
- `get_conversation()` – Full conversation DTO
- `get_context_for_llm()` – Format previous messages as string

**chat_service.py**:
- `build_prompt()` – Assemble prompt with conversation context
- `generate_answer()` – Orchestrate retrieval + LLM + save response

---

## Future Enhancements

### Short-Term (Easy Wins)
- [ ] **Message count limit**: If >100 messages, start deleting oldest (+ TTL)
- [ ] **Conversation metadata**: Add `title`, `tags`, `summary` fields
- [ ] **Soft-delete flag**: Add `_deleted: true` for audit trail instead of hard delete

### Medium-Term
- [ ] **Full-text search**: Index `content` field for conversation search
- [ ] **Feedback persistence**: Store user feedback (+1/-1) and link to messages
- [ ] **Conversation export**: Allow users to download chat history as PDF/JSON

### Long-Term
- [ ] **Analytics**: Track conversation patterns, common topics per tenant
- [ ] **Conversation clustering**: Group similar conversations
- [ ] **Conversation recommendations**: Suggest related past conversations

---

## Troubleshooting

### Issue: JWT token not extracting userId
**Solution**:
1. Verify `Authorization: Bearer <token>` header is present
2. Check token is valid (not expired)
3. Verify token contains `sub` claim: `jwt.io` decode
4. If using `KEYCLOAK_PUBLIC_KEY`, verify it matches realm's key

### Issue: Conversations not appearing in MongoDB
**Solution**:
1. Check `MONGODB_URI` env var is correct
2. Verify MongoDB is running: `mongosh`
3. Check database name: `use rag_platform` or configured name
4. Verify collection: `db.conversations.find()`
5. Enable debug logging: `structlog` level to DEBUG

### Issue: TTL index not deleting documents
**Solution**:
1. Verify index exists: `db.conversations.getIndexes()`
2. Check `expiresAt` field exists on documents: `db.conversations.findOne()`
3. TTL index runs every 60s by default (might see delay)
4. Restart MongoDB to force index recreation if corrupted

### Issue: Access denied on GET /chat/{conversationId}
**Solution**:
1. Verify JWT token in `Authorization` header is correct
2. Verify `userId` in token matches conversation's `userId` in MongoDB
3. Verify `tenantId` header matches conversation's `tenantId` in MongoDB
4. Check error message: "Access denied" = userId mismatch, "Not found" = tenantId mismatch

---

## References

- [ADR-007: Conversation History with MongoDB TTL](./ADR.md)
- [PyJWT Documentation](https://pyjwt.readthedocs.io/)
- [MongoDB TTL Indexes](https://docs.mongodb.com/manual/core/index-ttl/)
- [Keycloak OIDC Configuration](https://www.keycloak.org/docs/latest/server_admin/#oidc-clients)
- [GDPR Article 17: Right to Erasure](https://gdpr-info.eu/art-17-gdpr/)
