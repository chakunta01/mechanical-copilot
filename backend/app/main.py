"""FastAPI application factory and startup wiring."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from starlette.responses import Response

from app.core.config import settings
from app.core.db import engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.api.routes import auth, documents, inspections, misc, plans

configure_logging(settings.log_level)
logger = get_logger("main")

VERSION = "1.0.0"

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)

DESCRIPTION = """
**AI Copilot for Manufacturing Process Planning & Quality Inspection**

Grounded GenAI copilot:
- **Planning**: RAG-grounded process plans with deterministic rule validation and human approval.
- **Inspection**: image quality gate + VLM defect analysis with evidence and confidence.
- **Q&A**: knowledge-base-grounded answers with citations and refusal on low confidence.
- **Traceability**: every output carries sources, validation status and an audit trail.
"""

app = FastAPI(
    title="AI Manufacturing Copilot",
    version=VERSION,
    description=DESCRIPTION,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_error_handlers(app)

for router in (auth.router, documents.router, plans.router, inspections.router, misc.router):
    app.include_router(router, prefix="/api/v1")


@app.on_event("startup")
def startup() -> None:
    """Create tables, data dirs, and rebuild the in-memory vector index."""
    from app.core.db import SessionLocal
    from app.models import Base

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    from app.services import knowledge

    try:
        with SessionLocal() as db:
            indexed = knowledge.rebuild_index_from_db(db)
    except Exception as exc:  # noqa: BLE001 - a bad/empty API key must not kill the app
        logger.error(
            "startup re-embed failed (%s); falling back to offline hashing "
            "embeddings so the app still boots. Fix EMBEDDINGS_* settings and restart.",
            exc,
        )
        settings.embeddings_provider = "hashing"
        with SessionLocal() as db:
            indexed = knowledge.rebuild_index_from_db(db)
    logger.info("startup complete", extra={"event": "startup", "path": f"indexed={indexed}"})


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {
        "status": "ok",
        "version": VERSION,
        "llm_provider": settings.llm_provider,
        "embeddings_provider": settings.embeddings_provider,
        "vector_store": settings.vector_store,
        "database": engine.url.drivername,
    }


@app.get("/metrics", tags=["ops"])
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Serve stored images (thumbnails) for the UI in single-node mode.
uploads_path = Path(settings.upload_dir).resolve()
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(uploads_path)), name="files")
