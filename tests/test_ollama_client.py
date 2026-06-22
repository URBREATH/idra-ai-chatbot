import pytest
from unittest.mock import patch, MagicMock, AsyncMock

@pytest.mark.asyncio
async def test_generate_embedding_returns_vector():
    mock_response = MagicMock()
    mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
    mock_response.raise_for_status = MagicMock()
    
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        from app.ollama.client import generate_embedding
        result = await generate_embedding("test text")
        
        assert result == [0.1, 0.2, 0.3]

@pytest.mark.asyncio
async def test_generate_embedding_uses_custom_model():
    mock_response = MagicMock()
    mock_response.json.return_value = {"embedding": [0.5] * 1024}
    mock_response.raise_for_status = MagicMock()
    
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        from app.ollama.client import generate_embedding
        await generate_embedding("test", model="custom-model")
        
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["model"] == "custom-model"

@pytest.mark.asyncio
async def test_generate_embedding_raises_on_error():
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("API Error")
    
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        from app.ollama.client import generate_embedding
        with pytest.raises(Exception):
            await generate_embedding("test")

@pytest.mark.asyncio
async def test_generate_completion_returns_text():
    mock_response = MagicMock()
    mock_response.json.return_value = {"message": {"content": "Generated response"}}
    mock_response.raise_for_status = MagicMock()
    
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        from app.ollama.client import generate_completion
        result = await generate_completion("What is this?")
        
        assert result == "Generated response"

@pytest.mark.asyncio
async def test_generate_completion_uses_default_model():
    mock_response = MagicMock()
    mock_response.json.return_value = {"message": {"content": "response"}}
    mock_response.raise_for_status = MagicMock()
    
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        from app.ollama.client import generate_completion
        await generate_completion("prompt")
        
        call_args = mock_client.post.call_args
        assert "chat" in call_args[0][0]