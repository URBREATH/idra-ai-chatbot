import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/rag_platform")

client = AsyncIOMotorClient(MONGODB_URI)

def get_database():
    return client.get_default_database()
