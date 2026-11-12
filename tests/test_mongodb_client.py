import pytest
from unittest.mock import patch, MagicMock

def test_mongodb_connection_settings():
    from app.mongodb.client import MONGODB_URI, MONGODB_DB
    # URI must point at the configured database (MONGODB_DB env-driven, default rag_platform)
    assert MONGODB_DB == "rag_platform" or MONGODB_DB
    assert MONGODB_URI.startswith("mongodb://")
    assert MONGODB_URI.rstrip("/").endswith(MONGODB_DB)

def test_get_database_returns_motor_database():
    from app.mongodb.client import MONGODB_DB, get_database
    db = get_database()
    assert db is not None
    # get_default_database resolves the db path from the URI
    assert db.name == MONGODB_DB
