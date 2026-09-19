import uuid
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.user import User
from app.schemas.document_group import (
    DocumentGroupAssociateDocuments,
    DocumentGroupCreate,
    DocumentGroupDetailResponse,
    DocumentGroupResponse,
)

router = APIRouter(prefix="/document-groups", tags=["Document Groups"])


@router.post(
    "",
    response_model=DocumentGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new document group",
)
def create_document_group(
    group_in: DocumentGroupCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentGroupResponse:
    """Create a new group to organize related documents (e.g., question paper + answer key)."""
    group = DocumentGroup(
        owner_id=current_user.id,
        name=group_in.name,
        description=group_in.description,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get(
    "/{group_id}",
    response_model=DocumentGroupDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get document group details and its documents",
)
def get_document_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentGroupDetailResponse:
    """Retrieve document group details including its associated documents. Enforces ownership authorization."""
    group = db.get(DocumentGroup, group_id)
    if not group:
        raise NotFoundException("Document group not found")
    if group.owner_id != current_user.id:
        raise ForbiddenException("You do not have permission to view this document group")
    return group


@router.post(
    "/{group_id}/documents",
    response_model=DocumentGroupDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Associate documents with a group",
)
def associate_documents_to_group(
    group_id: uuid.UUID,
    payload: DocumentGroupAssociateDocuments,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentGroupDetailResponse:
    """Associate one or more documents owned by the user to the specified group."""
    group = db.get(DocumentGroup, group_id)
    if not group:
        raise NotFoundException("Document group not found")
    if group.owner_id != current_user.id:
        raise ForbiddenException("You do not have permission to modify this document group")

    # Fetch and verify ownership for all requested documents
    for doc_id in payload.document_ids:
        doc = db.get(Document, doc_id)
        if not doc:
            raise NotFoundException(f"Document {doc_id} not found")
        if doc.owner_id != current_user.id:
            raise ForbiddenException(f"You do not own document {doc_id}")
        doc.group_id = group.id

    db.commit()
    db.refresh(group)

    # Reconcile answers across the updated group
    from app.services.extraction.pipeline import DocumentProcessingPipeline
    try:
        DocumentProcessingPipeline.reconcile_group_answers(db, group.id)
        db.refresh(group)
    except Exception as exc:
        pass

    return group
