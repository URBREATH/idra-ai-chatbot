import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic_settings import BaseSettings
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import logging
import structlog

import httpx
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from starlette.middleware.cors import CORSMiddleware
from app.mongodb.client import get_database
from app.chat.dto.models import ChatRequest, ChatResponse, SourceReference

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
from .ingestion.sources import uses_mysql
from .auth import require_admin_authorization
from .chat.controllers.chat_controller import router as chat_router
from .conversation import repositories as conversation_repositories
from .observability import tracing

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Initialize MongoDB indexes during application startup.
    logger.info("Initializing conversation history indexes...")
    await conversation_repositories.initialize_conversation_indexes()
    logger.info("Conversation indexes initialized successfully")

    # TTL index for chat_feedback collection (90-day retention, GDPR).
    try:
        db = get_database()
        await db["chat_feedback"].create_index("expiresAt", expireAfterSeconds=0)
        logger.info("chat_feedback TTL index initialized")
    except Exception as exc:
        logger.warning("chat_feedback index init failed", error=str(exc))

    logger.info("tracing", langfuse_enabled=tracing.enabled())

    yield

    # Export the spans still buffered before the process exits.
    tracing.shutdown()


app = FastAPI(
    title="European Metadata RAG Platform",
    version="1.0.0",
    lifespan=lifespan,
)

cors_origins_env = os.getenv("CORS_ORIGINS", "*")
allow_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],      # necessario per far passare Authorization e X-Tenant-Id
)
app.include_router(chat_router)

_FRONTEND_PATH = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
async def frontend():
    return FileResponse(_FRONTEND_PATH)

# ---------------------------------------------------------------------------
# In-memory metrics counters (M9 - Monitoring)
# ---------------------------------------------------------------------------
_metrics: dict[str, int] = {
    "chat_requests": 0,
    "feedback_positive": 0,
    "feedback_negative": 0,
    "ingestion_runs": 0,
}

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

    async def _check(url, headers=None):
        try:
            async with httpx.AsyncClient(timeout=3.0) as http:
                r = await http.get(url, headers=headers)
            return "UP" if r.status_code == 200 else "DOWN"
        except httpx.HTTPError:
            return "DOWN"

    from app.ollama.client import is_external_api_enabled, get_api_base, _auth_headers
    if is_external_api_enabled():
        ollama_url = f"{get_api_base()}/models"
        ollama_headers = _auth_headers()
    else:
        ollama_url = f"http://{settings.ollama_host}:{settings.ollama_port}/api/tags"
        ollama_headers = None

    mongo  = await asyncio.to_thread(_ping_mongo)
    chroma = await _check(chroma_url)
    ollama = await _check(ollama_url, headers=ollama_headers)

    checks = {"mongo": mongo, "chroma": chroma, "ollama": ollama}
    if uses_mysql():
        from app.mysql.client import ping_sync as _ping_mysql
        checks["mysql"] = "UP" if await asyncio.to_thread(_ping_mysql) else "DOWN"

    everything_up = all(s == "UP" for s in checks.values())
    if not everything_up:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    # Observability is reported but never makes the service unhealthy.
    if tracing.enabled():
        lf_url = os.getenv("LANGFUSE_BASE_URL", "").rstrip("/") + "/api/public/health"
        checks["langfuse"] = await _check(lf_url)
    else:
        checks["langfuse"] = "DISABLED"

    return {
        "status": "UP" if everything_up else "UNREACHABLE",
        **checks,
    }

class IngestionRunRequest(BaseModel):
    fullReindex: bool = False
    # False (default): start in background and return immediately; poll
    # /admin/ingestion/status. True: wait for the end and return the result.
    wait: bool = False

class IngestionStatusResponse(BaseModel):
    running: bool
    processed: int
    remaining: int
    last_ingestion: str | None = None
    start_time: str | None = None
    sources: list[str] = []
    last_result: dict | None = None
    last_error: str | None = None

_ingestion_tasks: set = set()

async def _ingest_in_background(tenant_id: str, full_reindex: bool) -> None:
    try:
        await ingest_tenant(tenant_id, full_reindex=full_reindex)
    except Exception:
        logger.exception("ingestion_failed", tenant_id=tenant_id)

async def _missing_models() -> list[str]:
    """Models required by the ingestion that Ollama does not have. Without this
    check a missing enrichment model fails silently (404 on every entity) and
    the whole catalogue gets indexed without synonyms."""
    from app.ollama.client import list_models
    required = [os.getenv("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large")]
    if os.getenv("ENABLE_ENRICHMENT", "true").strip().lower() in ("1", "true", "yes", "on"):
        required.append(os.getenv("OLLAMA_ENRICHMENT_MODEL", "mistral:7b"))
    try:
        available = set(await list_models())
    except Exception as exc:
        return [f"ollama unreachable ({exc})"]
    available |= {m.removesuffix(":latest") for m in available}
    return [m for m in required if m not in available and m.removesuffix(":latest") not in available]

@app.post("/admin/ingestion/run")
async def run_ingestion(
    request: IngestionRunRequest,
    tenant_id: str = "default-tenant",
    _: str = Depends(require_admin_authorization),
):
    if get_ingestion_status().running:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ingestion already running")
    missing = await _missing_models()
    if missing:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Ollama models not available: {', '.join(missing)}")
    _metrics["ingestion_runs"] += 1
    if request.wait:
        result = await ingest_tenant(tenant_id, full_reindex=request.fullReindex)
        return {"status": "completed", "result": result}
    task = asyncio.create_task(_ingest_in_background(tenant_id, request.fullReindex))
    _ingestion_tasks.add(task)
    task.add_done_callback(_ingestion_tasks.discard)
    return {"status": "started", "tenant_id": tenant_id, "fullReindex": request.fullReindex,
            "sources": get_ingestion_status().sources}


@app.get("/admin/ingestion/status")
async def get_ingestion_status_endpoint():
    status = get_ingestion_status()
    return IngestionStatusResponse(
        running=status.running,
        processed=status.processed,
        remaining=status.remaining,
        last_ingestion=status.last_ingestion.isoformat() if status.last_ingestion else None,
        start_time=status.start_time.isoformat() if status.start_time else None,
        sources=status.sources,
        last_result=status.last_result,
        last_error=status.last_error,
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
    # Langfuse trace of the rated answer (ChatResponse.traceId). Without it the
    # feedback is attached to the whole conversation (Langfuse session).
    traceId: str | None = None
    comment: str | None = None

@app.post("/chat/feedback")
async def submit_feedback(request: FeedbackRequest):
    """
    Record user feedback on a chat answer.
    Increments in-memory counters (exposed via /metrics), persists the rating
    to MongoDB with a 90-day TTL for GDPR compliance, and sends it to Langfuse
    as the `user_feedback` score (1 = positive, 0 = negative).
    """
    if request.rating not in ("positive", "negative"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="rating must be 'positive' or 'negative'")
    if request.rating == "positive":
        _metrics["feedback_positive"] += 1
    else:
        _metrics["feedback_negative"] += 1
    logger.info("feedback_received", conversation_id=request.conversationId, rating=request.rating,
                trace_id=request.traceId)

    # Persist to MongoDB (collection: chat_feedback, TTL: 90 days)
    try:
        db = get_database()
        now = datetime.now(timezone.utc)
        await db["chat_feedback"].insert_one({
            "conversationId": request.conversationId,
            "traceId": request.traceId,
            "rating": request.rating,
            "comment": request.comment,
            "createdAt": now,
            "expiresAt": now + timedelta(days=90),
        })
    except Exception as exc:
        # Non-blocking: in-memory counter already updated; just log the failure.
        logger.warning("feedback_persist_failed", error=str(exc))

    sent = tracing.create_score(
        "user_feedback", request.rating == "positive",
        trace_id=request.traceId or None,
        session_id=None if request.traceId else request.conversationId,
        comment=(request.comment or None) and request.comment[:1000],
    )
    return {"status": "received", "langfuse": sent}


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
