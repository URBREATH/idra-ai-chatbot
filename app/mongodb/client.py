import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()
MONGODB_DB=os.getenv("MONGODB_DB", "rag_platform")

MONGODB_URI = os.getenv("MONGODB_URI", f"mongodb://mongo:27017/{MONGODB_DB}")
_base_uri, _sep, _query = MONGODB_URI.partition("?")
if not _base_uri.rstrip("/").endswith(f"/{MONGODB_DB}"):
    MONGODB_URI = f"{_base_uri.rstrip('/')}/{MONGODB_DB}{_sep}{_query}"

client = AsyncIOMotorClient(MONGODB_URI)

def get_database():
    return client.get_default_database()
