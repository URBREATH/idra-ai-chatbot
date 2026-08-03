import os

from dotenv import load_dotenv

from app.mongodb.client import get_database
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from bson import ObjectId
import logging

load_dotenv()
logger = logging.getLogger(__name__)

CONVERSATION_COLLECTION = "conversations"
MESSAGE_TTL_DAYS = int(os.getenv("MESSAGE_TTL_DAYS", 7))  # GDPR: auto-delete after 7 days


async def initialize_conversation_indexes():
    """
    Create TTL index for automatic conversation expiration (GDPR compliance).
    Call this during app startup.
    """
    db = get_database()
    collection = db[CONVERSATION_COLLECTION]
    
    # TTL index: automatically delete documents 7 days after expiresAt
    await collection.create_index(
        "expiresAt",
        expireAfterSeconds=0  # Delete immediately when expiresAt is reached
    )
    
    # Composite index for fast queries: (conversationId, tenantId)
    await collection.create_index([("conversationId", 1), ("tenantId", 1)])
    
    # Index for cleanup: userId + tenantId
    await collection.create_index([("userId", 1), ("tenantId", 1)])
    
    logger.info("Conversation indexes initialized (TTL + query indexes)")


async def save_message(
    conversation_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    content: str,
) -> Dict[str, Any]:
    """
    Persist a single message to MongoDB.
    Each message is a separate document for optimal insert performance.
    
    Args:
        conversation_id: UUID of the conversation
        tenant_id: Tenant identifier (multi-tenancy)
        user_id: Keycloak user ID
        role: "user" or "assistant"
        content: Message text
    
    Returns:
        Inserted document dict with _id
    """
    db = get_database()
    collection = db[CONVERSATION_COLLECTION]
    
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=MESSAGE_TTL_DAYS)
    
    doc = {
        "conversationId": conversation_id,
        "tenantId": tenant_id,
        "userId": user_id,
        "role": role,
        "content": content,
        "createdAt": now,
        "expiresAt": expires_at,
    }
    
    result = await collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def get_conversation_history(
    conversation_id: str,
    tenant_id: str,
) -> List[Dict[str, Any]]:
    """
    Retrieve all messages for a conversation (ordered by creation time).
    
    Args:
        conversation_id: UUID of the conversation
        tenant_id: Tenant identifier
    
    Returns:
        List of messages with role, content, createdAt (oldest first)
    """
    db = get_database()
    collection = db[CONVERSATION_COLLECTION]
    
    cursor = collection.find(
        {
            "conversationId": conversation_id,
            "tenantId": tenant_id,
        },
        projection={"role": 1, "content": 1, "createdAt": 1, "userId": 1, "_id": 0}
    ).sort("createdAt", 1)  # Oldest first
    
    messages = await cursor.to_list(length=None)
    return messages


async def get_recent_messages_for_context(
    conversation_id: str,
    tenant_id: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Get recent messages for LLM context (last N messages).
    
    Args:
        conversation_id: UUID of the conversation
        tenant_id: Tenant identifier
        limit: Max number of messages to return (default 10)
    
    Returns:
        Recent messages (newest first, for proper ordering in context)
    """
    db = get_database()
    collection = db[CONVERSATION_COLLECTION]
    
    cursor = collection.find(
        {
            "conversationId": conversation_id,
            "tenantId": tenant_id,
        },
        projection={"role": 1, "content": 1, "createdAt": 1, "_id": 0}
    ).sort("createdAt", -1).limit(limit)  # Newest first, limited
    
    messages = await cursor.to_list(length=limit)
    messages.reverse()  # Reverse to get oldest first for context
    return messages


async def delete_user_conversations(user_id: str, tenant_id: str) -> int:
    """
    Delete all conversations for a user (for right-to-be-forgotten compliance).
    
    Args:
        user_id: Keycloak user ID
        tenant_id: Tenant identifier
    
    Returns:
        Number of documents deleted
    """
    db = get_database()
    collection = db[CONVERSATION_COLLECTION]
    
    result = await collection.delete_many({
        "userId": user_id,
        "tenantId": tenant_id,
    })
    
    logger.info(f"Deleted {result.deleted_count} messages for user {user_id}")
    return result.deleted_count
