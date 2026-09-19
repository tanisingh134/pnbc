import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.document import DocumentResponse


class DocumentGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class DocumentGroupResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentGroupDetailResponse(DocumentGroupResponse):
    documents: List[DocumentResponse] = []

    model_config = ConfigDict(from_attributes=True)


class DocumentGroupAssociateDocuments(BaseModel):
    document_ids: List[uuid.UUID] = Field(..., min_length=1)
