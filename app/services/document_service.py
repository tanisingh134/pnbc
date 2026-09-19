import hashlib
import io
import logging
from pathlib import Path
from typing import Optional, Tuple
import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    PayloadTooLargeException,
    UnsupportedMediaTypeException,
)
from app.models.document import Document, DocumentRole, DocumentStatus
from app.models.document_group import DocumentGroup
from app.models.user import User
from app.services.storage.base import BaseStorageService

logger = logging.getLogger(__name__)

# File signatures (magic bytes)
MAGIC_SIGNATURES = {
    ".pdf": [b"%PDF-"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
}

MIME_TYPE_MAPPING = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


class DocumentService:
    @staticmethod
    def validate_file_signature(extension: str, header: bytes) -> str:
        """Validate file header against known magic bytes and return canonical MIME type."""
        ext = extension.lower()
        if ext not in MAGIC_SIGNATURES:
            raise UnsupportedMediaTypeException(
                f"Unsupported file extension '{extension}'. Allowed: {', '.join(settings.ALLOWED_EXTENSIONS)}"
            )

        signatures = MAGIC_SIGNATURES[ext]
        matches = any(header.startswith(sig) for sig in signatures)
        if not matches:
            raise BadRequestException(
                f"File content does not match declared extension '{extension}' (corrupt or invalid file signature)"
            )

        return MIME_TYPE_MAPPING[ext]

    @classmethod
    async def process_and_save_upload(
        cls,
        file: UploadFile,
        storage_service: BaseStorageService,
    ) -> Tuple[str, str, int, str]:
        """Validate, hash, and store uploaded file safely.
        
        Returns:
            (stored_filename, mime_type, file_size, file_hash)
        """
        raw_filename = file.filename or ""
        # Sanitize extension and protect against path manipulation
        ext = Path(raw_filename).suffix.lower()
        if not ext or ext not in settings.ALLOWED_EXTENSIONS:
            raise UnsupportedMediaTypeException(
                f"File type not permitted. Allowed extensions: {', '.join(settings.ALLOWED_EXTENSIONS)}"
            )

        # Read first chunk to inspect file signature and check non-empty
        header_chunk = await file.read(64)
        if not header_chunk:
            raise BadRequestException("Uploaded file is empty (0 bytes)")

        mime_type = cls.validate_file_signature(ext, header_chunk)

        # Generate non-guessable, secure server-side filename
        unique_stored_name = f"{uuid.uuid4().hex}{ext}"

        sha256 = hashlib.sha256()
        sha256.update(header_chunk)
        total_size = len(header_chunk)

        # Stream remaining chunks into memory buffer or temp file while validating size limit
        buffer = io.BytesIO()
        buffer.write(header_chunk)

        while chunk := await file.read(65536):
            total_size += len(chunk)
            if total_size > settings.max_upload_size_bytes:
                raise PayloadTooLargeException(
                    f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB"
                )
            sha256.update(chunk)
            buffer.write(chunk)

        buffer.seek(0)

        # Deep structural validation for malformed/corrupted files
        if ext in (".jpg", ".jpeg", ".png"):
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(buffer.getvalue()))
                img.verify()
            except Exception as exc:
                raise BadRequestException(f"Malformed or corrupted image file: {str(exc)}")
        elif ext == ".pdf":
            try:
                import fitz
                pdf_doc = fitz.open(stream=buffer.getvalue(), filetype="pdf")
                # Structural check: verify page count or load first page
                if pdf_doc.page_count < 1:
                    pdf_doc.close()
                    raise BadRequestException("PDF document has 0 pages or invalid catalog structure")
                pdf_doc.load_page(0)
                pdf_doc.close()
            except Exception as exc:
                raise BadRequestException(f"Malformed or corrupted PDF document: {str(exc)}")

        # Save to storage abstraction
        stored_filename = storage_service.save(buffer, unique_stored_name)
        file_hash = sha256.hexdigest()

        return stored_filename, mime_type, total_size, file_hash

    @classmethod
    def create_document_record(
        cls,
        db: Session,
        owner: User,
        original_filename: str,
        stored_filename: str,
        mime_type: str,
        file_size: int,
        file_hash: str,
        document_role: DocumentRole = DocumentRole.UNKNOWN,
        group_id: Optional[uuid.UUID] = None,
    ) -> Document:
        """Create database record for the uploaded document."""
        # Verify group ownership if group_id is supplied
        if group_id:
            group = db.get(DocumentGroup, group_id)
            if not group:
                raise NotFoundException("Specified document group not found")
            if group.owner_id != owner.id:
                raise ForbiddenException("You do not have permission to attach documents to this group")

        clean_original_filename = Path(original_filename).name

        document = Document(
            owner_id=owner.id,
            group_id=group_id,
            original_filename=clean_original_filename,
            stored_filename=stored_filename,
            mime_type=mime_type,
            file_size=file_size,
            file_hash=file_hash,
            document_role=document_role,
            status=DocumentStatus.QUEUED,
            progress=0,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document

    @staticmethod
    def get_document(
        db: Session,
        document_id: uuid.UUID,
        current_user: User,
    ) -> Document:
        """Fetch document with strict authorization check."""
        document = db.get(Document, document_id)
        if not document:
            raise NotFoundException("Document not found")
        if document.owner_id != current_user.id:
            raise ForbiddenException("You do not have permission to access this document")
        return document

    @classmethod
    def reprocess_document(
        cls,
        db: Session,
        document_id: uuid.UUID,
        current_user: User,
    ) -> Document:
        """Reprocess document without creating duplicate records.
        
        Enforces user ownership (403 if owned by another user, 404 if not found).
        Clears existing warnings, answers, and questions for this document.
        Resets status to QUEUED, progress to 0, and dispatches background Celery task.
        """
        document = cls.get_document(db, document_id, current_user)

        from app.models.answer import Answer
        from app.models.question import Question
        from app.models.warning import ExtractionWarning

        # If other answers pointed to questions in this document, unlink them
        q_ids = [q.id for q in db.query(Question.id).filter(Question.document_id == document.id).all()]
        if q_ids:
            db.query(Answer).filter(Answer.question_id.in_(q_ids)).update(
                {"question_id": None, "matched": False},
                synchronize_session=False,
            )

        # Remove prior extractions for this document to prevent duplicate data
        db.query(ExtractionWarning).filter(ExtractionWarning.document_id == document.id).delete(synchronize_session=False)
        db.query(Answer).filter(Answer.source_document_id == document.id).delete(synchronize_session=False)
        db.query(Question).filter(Question.document_id == document.id).delete(synchronize_session=False)

        document.status = DocumentStatus.QUEUED
        document.progress = 0
        document.error_message = None

        db.commit()
        db.refresh(document)

        # Dispatch background Celery task
        try:
            from app.workers.tasks import process_document_task
            process_document_task.delay(str(document.id))
        except Exception as exc:
            logger.warning(
                f"Celery queueing deferred for reprocessed document {document.id}: {exc}. "
                "Record saved with QUEUED status."
            )

        return document

    @staticmethod
    def associate_group(
        db: Session,
        document_id: uuid.UUID,
        group_id: Optional[uuid.UUID],
        current_user: User,
    ) -> Document:
        """Associate or disassociate document with a group."""
        document = DocumentService.get_document(db, document_id, current_user)

        if group_id is not None:
            group = db.get(DocumentGroup, group_id)
            if not group:
                raise NotFoundException("Target document group not found")
            if group.owner_id != current_user.id:
                raise ForbiddenException("You do not have permission to assign to this group")
            document.group_id = group.id
            db.commit()
            db.refresh(document)

            # Reconcile answers across the group
            from app.services.extraction.pipeline import DocumentProcessingPipeline
            try:
                DocumentProcessingPipeline.reconcile_group_answers(db, group.id)
            except Exception as exc:
                logger.warning(f"Failed to reconcile group answers for group {group.id}: {exc}")
        else:
            document.group_id = None
            db.commit()
            db.refresh(document)

        return document
