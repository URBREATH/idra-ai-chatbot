import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()
MONGODB_DB=os.getenv("MONGODB_DB", "rag_platform")

MONGODB_URI = os.getenv(f"MONGODB_URI/{MONGODB_DB}", f"mongodb://mongo:27017/{MONGODB_DB}")

client = AsyncIOMotorClient(MONGODB_URI)

def get_database():
    return client.get_default_database()
