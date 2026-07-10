from app.ollama import client as ollama_client


async def embed_query(query: str) -> list[float]:
    """Generate an embedding vector for a user query using the local Ollama service."""
    if not query:
        return []
    return await ollama_client.generate_embedding(query)
