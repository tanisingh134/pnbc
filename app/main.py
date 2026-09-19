import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.models.user import User
from app.schemas.document import DocumentStatusResponse
from app.services.document_service import DocumentService



@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager to ensure storage directory exists."""
    upload_path = Path(settings.UPLOAD_DIR)
    upload_path.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Pragati Bharti – Document Processing & Question Extraction Service.\n\n"
        "Secure document ingestion, background Celery extraction, and ownership-isolated REST API."
    ),
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register custom exception handlers
register_exception_handlers(app)

# Include routers
app.include_router(health_router)
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.post(
    "/documents/{document_id}/reprocess",
    response_model=DocumentStatusResponse,
    status_code=status.HTTP_200_OK,
    tags=["Documents"],
    include_in_schema=False,
)
def root_reprocess_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentStatusResponse:
    """Direct alias for POST /documents/{id}/reprocess without /api/v1 prefix."""
    return DocumentService.reprocess_document(db, document_id, current_user)


@app.get("/", include_in_schema=False)
def root_redirect():
    return {
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }

