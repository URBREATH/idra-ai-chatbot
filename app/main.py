import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request, Response, status
from pydantic_settings import BaseSettings
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import datetime
import logging
import structlog

import httpx
from pymongo import MongoClient
from pymongo.errors import PyMongoError


load_dotenv()

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger(__name__)

class Settings(BaseSettings):
    port: int = int(os.getenv("PORT", 3000))
    mongo_uri: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    chroma_host: str = os.getenv("CHROMA_HOST", "localhost")
    chroma_port: int = int(os.getenv("CHROMA_PORT", 8000))
    ollama_host: str = os.getenv("OLLAMA_HOST", "localhost")
    ollama_port: int = int(os.getenv("OLLAMA_PORT", 11434))
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me")
    default_tenant_id: str = os.getenv("DEFAULT_TENANT_ID", "default-tenant")

settings = Settings()

from .ingestion.service import get_ingestion_status, ingest_tenant
from .auth import require_admin_authorization
from .chat.controllers.chat_controller import router as chat_router
from .chat.dto.models import ChatRequest, ChatResponse, SourceReference
from .conversation import repositories as conversation_repositories

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Initialize MongoDB indexes during application startup.
    logger.info("Initializing conversation history indexes...")
    await conversation_repositories.initialize_conversation_indexes()
    logger.info("Conversation indexes initialized successfully")
    yield


app = FastAPI(
    title="European Metadata RAG Platform",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(chat_router)

# ---------------------------------------------------------------------------
# In-memory metrics counters (M9 - Monitoring)
# ---------------------------------------------------------------------------
_metrics: dict[str, int] = {
    "chat_requests": 0,
    "feedback_positive": 0,
    "feedback_negative": 0,
    "ingestion_runs": 0,
}


"""@app.get("/health")
async def health():
    return {
        "status": "UP",
        "mongo": "UNKNOWN",
        "chroma": "UNKNOWN",
        "ollama": "UNKNOWN",
    }"""

@app.get("/health")
async def health(response: Response):
    chroma_url = f"http://{settings.chroma_host}:{settings.chroma_port}/api/v2/heartbeat"
    ollama_url = f"http://{settings.ollama_host}:{settings.ollama_port}/api/tags"

    def _ping_mongo():
        client = None
        try:
            client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=2000)
            client.admin.command("ping")   # no-op: verifica che il server risponda
            return "UP"
        except PyMongoError:
            return "DOWN"
        finally:
            if client is not None:
                client.close()

    async def _check(url):
        try:
            async with httpx.AsyncClient(timeout=2.0) as http:
                r = await http.get(url)
            return "UP" if r.status_code == 200 else "DOWN"
        except httpx.HTTPError:
            return "DOWN"

    mongo  = await asyncio.to_thread(_ping_mongo)
    chroma = await _check(chroma_url)
    ollama = await _check(ollama_url)

    everything_up = all(s == "UP" for s in (mongo, chroma, ollama))
    if not everything_up:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "UP" if everything_up else "UNREACHABLE",
        "mongo": mongo,
        "chroma": chroma,
        "ollama": ollama,
    }

class IngestionRunRequest(BaseModel):
    fullReindex: bool = False

class IngestionStatusResponse(BaseModel):
    running: bool
    processed: int
    remaining: int
    last_ingestion: str | None = None

@app.post("/admin/ingestion/run")
async def run_ingestion(
    request: IngestionRunRequest,
    tenant_id: str = "default-tenant",
    _: str = Depends(require_admin_authorization),
):
    _metrics["ingestion_runs"] += 1
    result = await ingest_tenant(tenant_id, full_reindex=request.fullReindex)
    return {"status": "started", "result": result}


@app.get("/admin/ingestion/status")
async def get_ingestion_status_endpoint():
    status = get_ingestion_status()
    return IngestionStatusResponse(
        running=status.running,
        processed=status.processed,
        remaining=status.remaining,
        last_ingestion=status.last_ingestion.isoformat() if status.last_ingestion else None
    )

class UserProfileResponse(BaseModel):
    id: str
    roles: list[str]
    tenantId: str

@app.get("/users/me")
async def get_user_profile():
    return UserProfileResponse(
        id="user-id",
        roles=["USER"],
        tenantId="tenant-id"
    )

class FeedbackRequest(BaseModel):
    conversationId: str
    rating: str

@app.post("/chat/feedback")
async def submit_feedback(request: FeedbackRequest):
    if request.rating == "positive":
        _metrics["feedback_positive"] += 1
    elif request.rating == "negative":
        _metrics["feedback_negative"] += 1
    logger.info("feedback_received", conversation_id=request.conversationId, rating=request.rating)
    return {"status": "received"}


@app.get("/metrics")
async def get_metrics():
    """Expose in-memory application counters (M9 - Monitoring)."""
    ingestion_status = get_ingestion_status()
    return {
        **_metrics,
        "ingestion_running": ingestion_status.running,
        "ingestion_processed": ingestion_status.processed,
        "last_ingestion": ingestion_status.last_ingestion.isoformat() if ingestion_status.last_ingestion else None,
    }