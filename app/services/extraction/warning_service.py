from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)


@dataclass
class PendingWarning:
    warning_type: str
    message: str
    page_number: Optional[int] = None
    question_id: Optional[uuid.UUID] = None
    confidence: Optional[float] = None


class WarningDetector:
    """Detects extraction anomalies and generates review warnings for questions, answers, and pages."""

    # Standard warning types as required by specification
    LOW_OCR_CONFIDENCE = "LOW_OCR_CONFIDENCE"
    POSSIBLE_INCOMPLETE_QUESTION = "POSSIBLE_INCOMPLETE_QUESTION"
    MISSING_QUESTION_NUMBER = "MISSING_QUESTION_NUMBER"
    OPTION_PARSE_UNCERTAIN = "OPTION_PARSE_UNCERTAIN"
    ANSWER_UNMATCHED = "ANSWER_UNMATCHED"
    ANSWER_LOW_CONFIDENCE = "ANSWER_LOW_CONFIDENCE"
    POSSIBLE_VISUAL_CONTENT = "POSSIBLE_VISUAL_CONTENT"
    OCR_FAILURE = "OCR_FAILURE"

    @classmethod
    def inspect_page(
        cls,
        page_number: int,
        extraction_method: str,
        confidence: float,
        has_visual_content: bool,
        text: str,
    ) -> List[PendingWarning]:
        """Inspect page extraction result and generate document-level warnings."""
        warnings: List[PendingWarning] = []

        if extraction_method == "ocr":
            if not text.strip():
                warnings.append(
                    PendingWarning(
                        warning_type=cls.OCR_FAILURE,
                        message=f"Page {page_number}: OCR produced no text. Possible blank page or severe scan corruption.",
                        page_number=page_number,
                        confidence=0.0,
                    )
                )
            elif confidence < 0.60:
                warnings.append(
                    PendingWarning(
                        warning_type=cls.LOW_OCR_CONFIDENCE,
                        message=f"Page {page_number}: OCR confidence is low ({round(confidence * 100, 1)}%). Character inaccuracies possible.",
                        page_number=page_number,
                        confidence=confidence,
                    )
                )

        if has_visual_content:
            warnings.append(
                PendingWarning(
                    warning_type=cls.POSSIBLE_VISUAL_CONTENT,
                    message=f"Page {page_number}: Contains embedded visual media, figures, or diagrams that may require manual inspection.",
                    page_number=page_number,
                    confidence=confidence,
                )
            )

        return warnings

    @classmethod
    def inspect_question(
        cls,
        question_number: Optional[str],
        question_text: str,
        question_type: str,
        options: Optional[Dict[str, str]],
        confidence: float,
        source_pages: List[int],
        has_visual_content: bool = False,
    ) -> List[PendingWarning]:
        """Inspect an individual parsed question and generate question-level warnings."""
        warnings: List[PendingWarning] = []
        primary_page = source_pages[0] if source_pages else None

        # Check for missing question number
        if not question_number:
            warnings.append(
                PendingWarning(
                    warning_type=cls.MISSING_QUESTION_NUMBER,
                    message="Question boundary recognized without explicit question number.",
                    page_number=primary_page,
                    confidence=confidence,
                )
            )

        # Check for incomplete question text
        stripped_text = question_text.strip()
        if len(stripped_text) < 15 or stripped_text.endswith(("-", "...", "and", "the", "or", "of")):
            warnings.append(
                PendingWarning(
                    warning_type=cls.POSSIBLE_INCOMPLETE_QUESTION,
                    message="Question text appears truncated or ends abruptly.",
                    page_number=primary_page,
                    confidence=confidence,
                )
            )

        # Check for uncertain options in MCQs
        if question_type == "MCQ":
            if not options or len(options) < 2:
                warnings.append(
                    PendingWarning(
                        warning_type=cls.OPTION_PARSE_UNCERTAIN,
                        message=f"MCQ detected with only {len(options) if options else 0} valid option(s). Expected at least 2.",
                        page_number=primary_page,
                        confidence=confidence,
                    )
                )
            else:
                # Check for discontinuous option keys (e.g. A, C without B)
                keys = sorted(list(options.keys()))
                if keys == ["A", "C"] or keys == ["B", "D"]:
                    warnings.append(
                        PendingWarning(
                            warning_type=cls.OPTION_PARSE_UNCERTAIN,
                            message=f"Discontinuous option keys detected: {keys}.",
                            page_number=primary_page,
                            confidence=confidence,
                        )
                    )

        # Visual content within question scope
        if has_visual_content:
            warnings.append(
                PendingWarning(
                    warning_type=cls.POSSIBLE_VISUAL_CONTENT,
                    message="Question references or overlaps visual figures/tables.",
                    page_number=primary_page,
                    confidence=confidence,
                )
            )

        return warnings

    @classmethod
    def inspect_unmatched_answer(
        cls,
        question_number: str,
        answer_text: str,
        source_page: Optional[int],
    ) -> PendingWarning:
        """Generate warning when an answer from answer key cannot be matched to any question."""
        return PendingWarning(
            warning_type=cls.ANSWER_UNMATCHED,
            message=f"Answer key entry '{question_number}: {answer_text}' could not be matched to any extracted question.",
            page_number=source_page,
            confidence=0.50,
        )

    @classmethod
    def inspect_option_mismatch(
        cls,
        question_number: str,
        answer_text: str,
        available_options: List[str],
        question_id: Optional[uuid.UUID] = None,
        page_number: Optional[int] = None,
    ) -> PendingWarning:
        """Generate warning when an answer specifies an option key not in question options."""
        return PendingWarning(
            warning_type=cls.ANSWER_LOW_CONFIDENCE,
            message=(
                f"Question {question_number}: Answer key value '{answer_text}' does not match "
                f"available options {available_options}."
            ),
            question_id=question_id,
            page_number=page_number,
            confidence=0.50,
        )

    @classmethod
    def inspect_conflicting_answers(
        cls,
        question_number: str,
        conflicting_answers: List[str],
        question_id: Optional[uuid.UUID] = None,
        page_number: Optional[int] = None,
    ) -> PendingWarning:
        """Generate warning when multiple conflicting answer entries exist for the same question."""
        return PendingWarning(
            warning_type=cls.ANSWER_LOW_CONFIDENCE,
            message=(
                f"Question {question_number}: Multiple conflicting answer key entries detected "
                f"({', '.join(conflicting_answers)})."
            ),
            question_id=question_id,
            page_number=page_number,
            confidence=0.40,
        )

    @classmethod
    def inspect_cross_doc_unmatched_answer(
        cls,
        question_number: str,
        answer_text: str,
        group_name: str,
        page_number: Optional[int] = None,
    ) -> PendingWarning:
        """Generate warning when an answer cannot be matched to any question in a document group."""
        return PendingWarning(
            warning_type=cls.ANSWER_UNMATCHED,
            message=(
                f"Answer key entry '{question_number}: {answer_text}' could not be matched to any question "
                f"in document group '{group_name}'."
            ),
            page_number=page_number,
            confidence=0.50,
        )

