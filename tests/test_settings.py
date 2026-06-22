import os
import pytest
from unittest.mock import patch

def test_settings_loads_from_env():
    with patch.dict(os.environ, {
        "PORT": "8080",
        "MONGODB_URI": "mongodb://custom:27017/test",
        "CHROMA_HOST": "chroma.custom.com",
        "JWT_SECRET": "test-secret"
    }):
        import importlib
        import app.main as main_module
        importlib.reload(main_module)
        
        assert main_module.settings.port == 8080
        assert main_module.settings.mongo_uri == "mongodb://custom:27017/test"
        assert main_module.settings.chroma_host == "chroma.custom.com"
        assert main_module.settings.jwt_secret == "test-secret"

def test_settings_defaults():
    with patch.dict(os.environ, {}, clear=True):
        import importlib
        import app.main as main_module
        importlib.reload(main_module)
        
        assert main_module.settings.port == 3000
        assert main_module.settings.chroma_host == "localhost"
        assert main_module.settings.chroma_port == 8000

def test_settings_ollama_defaults():
    with patch.dict(os.environ, {}, clear=True):
        import importlib
        import app.ollama.client as ollama_client
        importlib.reload(ollama_client)
        
        assert ollama_client.BASE_URL == "http://localhost:11434"