import logging
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_db, get_storage_service
from app.models.answer import Answer
from app.models.document import DocumentRole
from app.models.question import Question
from app.models.user import User
from app.models.warning import ExtractionWarning
from app.schemas.document import (
    DocumentGroupAssociation,
    DocumentResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from app.schemas.question import (
    AnswerResponse,
    ExtractionWarningResponse,
    PaginatedQuestionsResponse,
)
from app.services.document_service import DocumentService
from app.services.storage.base import BaseStorageService
from app.workers.tasks import process_document_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document for processing",
)
async def upload_document(
    file: UploadFile = File(...),
    document_role: DocumentRole = Form(DocumentRole.UNKNOWN),
    group_id: Optional[uuid.UUID] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage_service: BaseStorageService = Depends(get_storage_service),
) -> DocumentUploadResponse:
    """Upload PDF or Image file (multipart/form-data).
    
    Validates file signature, stores securely, writes metadata record,
    dispatches background Celery extraction task, and returns immediately.
    """
    stored_filename, mime_type, file_size, file_hash = await DocumentService.process_and_save_upload(
        file=file,
        storage_service=storage_service,
    )

    document = DocumentService.create_document_record(
        db=db,
        owner=current_user,
        original_filename=file.filename or "upload",
        stored_filename=stored_filename,
        mime_type=mime_type,
        file_size=file_size,
        file_hash=file_hash,
        document_role=document_role,
        group_id=group_id,
    )

    # Dispatch asynchronous background task to Celery
    try:
        process_document_task.delay(str(document.id))
    except Exception as exc:
        logger.warning(
            f"Celery queueing unavailable or deferred for document {document.id}: {exc}. "
            "Record saved with QUEUED status."
        )

    return document


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve document metadata and extraction results",
)
def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Retrieve full document details with questions and warnings. Enforces ownership authorization."""
    return DocumentService.get_document(db, document_id, current_user)


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll processing status and progress",
)
def get_document_status(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentStatusResponse:
    """Lightweight endpoint for polling document processing state."""
    doc = DocumentService.get_document(db, document_id, current_user)
    return doc


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Reprocess a document without creating duplicate records",
)
def reprocess_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentStatusResponse:
    """Trigger reprocessing of an existing document.
    
    Enforces user ownership, clears previously extracted questions, answers, and warnings
    without creating duplicate records, resets status to QUEUED, and dispatches background worker.
    """
    doc = DocumentService.reprocess_document(db, document_id, current_user)
    return doc



@router.patch(
    "/{document_id}/group",
    response_model=DocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Associate or change document group",
)
def update_document_group(
    document_id: uuid.UUID,
    payload: DocumentGroupAssociation,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Associate or disassociate a document with a document group."""
    return DocumentService.associate_group(db, document_id, payload.group_id, current_user)


@router.get(
    "/{document_id}/questions",
    response_model=PaginatedQuestionsResponse,
    status_code=status.HTTP_200_OK,
    summary="List extracted questions for document with pagination",
)
def get_document_questions(
    document_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="Offset items"),
    limit: int = Query(50, ge=1, le=100, description="Page size limit"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedQuestionsResponse:
    """Fetch paginated questions extracted from a document. Enforces ownership authorization."""
    # Enforce authorization
    DocumentService.get_document(db, document_id, current_user)

    total = db.query(Question).filter(Question.document_id == document_id).count()
    items = (
        db.query(Question)
        .options(
            joinedload(Question.answers),
            joinedload(Question.warnings),
        )
        .filter(Question.document_id == document_id)
        .order_by(Question.created_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return PaginatedQuestionsResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=items,
    )


@router.get(
    "/{document_id}/answers",
    response_model=List[AnswerResponse],
    status_code=status.HTTP_200_OK,
    summary="List extracted answer key entries for document",
)
def get_document_answers(
    document_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[AnswerResponse]:
    """Retrieve answer key entries extracted from a document. Enforces ownership authorization."""
    DocumentService.get_document(db, document_id, current_user)

    answers = (
        db.query(Answer)
        .filter(Answer.source_document_id == document_id)
        .order_by(Answer.question_number.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return answers


@router.get(
    "/{document_id}/warnings",
    response_model=List[ExtractionWarningResponse],
    status_code=status.HTTP_200_OK,
    summary="List extraction warnings for document",
)
def get_document_warnings(
    document_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ExtractionWarningResponse]:
    """Retrieve extraction warnings and review flags for a document. Enforces ownership authorization."""
    DocumentService.get_document(db, document_id, current_user)

    warnings = (
        db.query(ExtractionWarning)
        .filter(ExtractionWarning.document_id == document_id)
        .order_by(ExtractionWarning.created_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return warnings
