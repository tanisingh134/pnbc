import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class ExtractionWarningResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    question_id: Optional[uuid.UUID] = None
    warning_type: str
    message: str
    page_number: Optional[int] = None
    confidence: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnswerResponse(BaseModel):
    id: uuid.UUID
    question_id: Optional[uuid.UUID] = None
    source_document_id: uuid.UUID
    question_number: str
    answer_text: str
    confidence: float
    source_page: Optional[int] = None
    matched: bool

    model_config = ConfigDict(from_attributes=True)


class QuestionResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    question_number: Optional[str] = None
    question_text: str
    question_type: str
    options: Optional[Any] = None
    answer: Optional[str] = None
    source_pages: Optional[Any] = None
    confidence: float
    needs_review: bool
    extraction_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    answers: List[AnswerResponse] = []
    warnings: List[ExtractionWarningResponse] = []

    model_config = ConfigDict(from_attributes=True)


class PaginatedQuestionsResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[QuestionResponse]

    model_config = ConfigDict(from_attributes=True)
