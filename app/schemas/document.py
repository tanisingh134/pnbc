import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from app.models.document import DocumentRole, DocumentStatus
from app.schemas.question import ExtractionWarningResponse, QuestionResponse


class DocumentUploadResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    mime_type: str
    file_size: int
    file_hash: str
    document_role: DocumentRole
    status: DocumentStatus
    progress: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentStatusResponse(BaseModel):
    id: uuid.UUID
    status: DocumentStatus
    progress: int
    error_message: Optional[str] = None
    page_count: Optional[int] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    group_id: Optional[uuid.UUID] = None
    original_filename: str
    stored_filename: str
    mime_type: str
    file_size: int
    file_hash: str
    document_role: DocumentRole
    status: DocumentStatus
    progress: int
    error_message: Optional[str] = None
    page_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    questions: List[QuestionResponse] = []
    warnings: List[ExtractionWarningResponse] = []

    model_config = ConfigDict(from_attributes=True)


class DocumentGroupAssociation(BaseModel):
    group_id: Optional[uuid.UUID] = None
