import pytest
from unittest.mock import patch, MagicMock

def test_mongodb_connection_settings():
    from app.mongodb.client import MONGODB_URI
    assert MONGODB_URI == "mongodb://localhost:27017/orion"

def test_get_database_returns_motor_database():
    from app.mongodb.client import get_database
    db = get_database()
    assert db is not None
    assert db.name == "orion"