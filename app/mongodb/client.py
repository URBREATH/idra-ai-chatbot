import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://mongo:27047/rag_platform")

client = AsyncIOMotorClient(MONGODB_URI)

def get_database():
    return client.get_default_database()
