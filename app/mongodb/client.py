import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv('.env.test')

print(os.getenv('MONGODB_URI'))

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/orion")

client = AsyncIOMotorClient(MONGODB_URI)

def get_database():
    return client.get_default_database()
