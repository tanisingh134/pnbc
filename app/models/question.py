import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from sqlalchemy import Boolean, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PortableJSON, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.answer import Answer
    from app.models.document import Document
    from app.models.warning import ExtractionWarning


class Question(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "questions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. MCQ, DESCRIPTIVE, TRUE_FALSE
    options: Mapped[Optional[Any]] = mapped_column(PortableJSON, nullable=True)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_pages: Mapped[Optional[Any]] = mapped_column(PortableJSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extraction_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(PortableJSON, nullable=True)

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="questions")
    answers: Mapped[List["Answer"]] = relationship(
        "Answer",
        back_populates="question",
    )
    warnings: Mapped[List["ExtractionWarning"]] = relationship(
        "ExtractionWarning",
        back_populates="question",
    )
