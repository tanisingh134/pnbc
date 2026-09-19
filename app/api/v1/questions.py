import logging
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.question import Question
from app.models.user import User
from app.schemas.question import QuestionResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/questions", tags=["Questions"])


@router.get(
    "/{question_id}",
    response_model=QuestionResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve question details by ID",
)
def get_question(
    question_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QuestionResponse:
    """Retrieve detailed question information, including matched answers and extraction warnings.
    
    Enforces ownership authorization based on the document owner.
    """
    question = (
        db.query(Question)
        .options(
            joinedload(Question.document),
            joinedload(Question.answers),
            joinedload(Question.warnings),
        )
        .filter(Question.id == question_id)
        .first()
    )

    if not question:
        raise NotFoundException("Question not found")

    if question.document.owner_id != current_user.id:
        raise ForbiddenException("You do not have permission to access this question")

    return question
