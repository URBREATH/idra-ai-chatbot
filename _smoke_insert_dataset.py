"""Script temporaneo di smoke test: inserisce un dataset NGSI-LD sintetico
nella collection 'entities' di Mongo (db 'orion'), cosi' come farebbe
Orion Context Broker, per validare la pipeline di ingestion end-to-end
senza dipendere da un vero import di Orion.

Da eliminare al termine del test manuale.
"""
import time
from pymongo import MongoClient

MONGODB_URI = "mongodb://localhost:27017/orion"
DATASET_ID = "urn:ngsi-ld:Dataset:smoke-test-001"

now = time.time()


def prop(value):
    return {"type": "Property", "value": value, "creDate": now, "modDate": now, "mdNames": []}


doc = {
    "_id": {"id": DATASET_ID, "type": "Dataset", "servicePath": "/"},
    "attrNames": ["title", "description", "downloadURL", "format", "license", "publisher"],
    "attrs": {
        "title": prop("Air Quality Monitoring Turin"),
        "description": prop(
            "Hourly NO2 and PM10 measurements collected across air quality "
            "monitoring stations in the city of Turin, Italy."
        ),
        "downloadURL": prop("https://opendata.example.org/datasets/air-quality-turin.csv"),
        "format": prop("CSV"),
        "license": prop("CC-BY-4.0"),
        "publisher": prop("Comune di Torino"),
    },
    "publisher": "Comune di Torino",
    "creDate": now,
    "modDate": now,
}

client = MongoClient(MONGODB_URI)
db = client.get_default_database()

db["entities"].delete_many({"_id.id": DATASET_ID})
db["entities"].insert_one(doc)

count = db["entities"].count_documents({"_id.servicePath": "/"})
print(f"Inserted synthetic dataset '{DATASET_ID}'. entities count (servicePath=/): {count}")
client.close()
