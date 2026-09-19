import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.answer import Answer
from app.models.document import Document, DocumentRole, DocumentStatus
from app.models.document_group import DocumentGroup
from app.models.question import Question
from app.models.warning import ExtractionWarning
from app.services.extraction.answer_parser import AnswerKeyParser, ParsedAnswer
from app.services.extraction.confidence import ConfidenceCalculator
from app.services.extraction.pdf_extractor import PDFExtractorService, PageExtractionResult
from app.services.extraction.question_parser import ParsedQuestion, QuestionParser
from app.services.extraction.warning_service import PendingWarning, WarningDetector
from app.services.storage.base import BaseStorageService
from app.services.storage.local import LocalStorageService

logger = logging.getLogger(__name__)


class DocumentProcessingPipeline:
    """Orchestrates end-to-end extraction, question parsing, answer key matching, scoring, and persistence."""

    @classmethod
    def process_document(
        cls,
        db: Session,
        document_id: uuid.UUID,
        storage_service: Optional[BaseStorageService] = None,
    ) -> Dict[str, Any]:
        """Execute full extraction workflow on a document record."""
        doc = db.get(Document, document_id)
        if not doc:
            raise ValueError(f"Document {document_id} not found")

        storage = storage_service or LocalStorageService(settings.UPLOAD_DIR)
        file_path = storage.get_path(doc.stored_filename)
        if not file_path.is_file():
            raise FileNotFoundError(f"Stored file '{doc.stored_filename}' does not exist on disk")

        # Step 1: Mark PROCESSING
        doc.status = DocumentStatus.PROCESSING
        doc.progress = 10
        doc.error_message = None
        db.commit()

        # Step 2: Read raw file payload
        file_bytes = storage.read(doc.stored_filename)

        # Step 3: Determine file type & extract pages (PDF vs Image)
        doc.progress = 25
        db.commit()

        page_results: List[PageExtractionResult] = []
        if doc.mime_type == "application/pdf":
            page_results = PDFExtractorService.extract_from_pdf_bytes(file_bytes)
        else:
            page_results = PDFExtractorService.extract_from_image_bytes(file_bytes)

        doc.page_count = len(page_results)
        doc.progress = 55
        db.commit()

        # Step 4: Generate document-level page warnings
        pending_warnings: List[PendingWarning] = []
        for p in page_results:
            page_warns = WarningDetector.inspect_page(
                page_number=p.page_number,
                extraction_method=p.extraction_method,
                confidence=p.confidence,
                has_visual_content=p.has_visual_content,
                text=p.text,
            )
            pending_warnings.extend(page_warns)

        # Step 5: Check if document is an Answer Key or Question Paper
        parsed_questions: List[ParsedQuestion] = []
        extracted_answers: List[ParsedAnswer] = []

        if doc.document_role == DocumentRole.ANSWER_KEY:
            # Entire document is an answer key
            full_text = "\n".join(p.text for p in page_results)
            extracted_answers = AnswerKeyParser.parse_answer_key_text(full_text)
        else:
            # Parse questions and separate any embedded answer-key section
            parsed_questions, answer_key_text = QuestionParser.parse_pages(page_results)
            if answer_key_text:
                extracted_answers = AnswerKeyParser.parse_answer_key_text(answer_key_text)

        doc.progress = 75
        db.commit()

        # Step 6: Match answers to questions
        extracted_answers, matched_map = AnswerKeyParser.match_answers_to_questions(
            extracted_answers,
            parsed_questions,
        )

        # Step 7: Calculate Confidence Scores & Question-level Warnings
        # Clear existing extractions if re-processing
        db.query(ExtractionWarning).filter(ExtractionWarning.document_id == doc.id).delete()
        db.query(Answer).filter(Answer.source_document_id == doc.id).delete()
        db.query(Question).filter(Question.document_id == doc.id).delete()
        db.flush()

        has_review_items = False
        db_questions: Dict[str, Question] = {}

        for pq in parsed_questions:
            avg_base_conf = pq.extraction_metadata.get("avg_page_confidence", 1.0)
            is_matched = pq.question_number in matched_map if pq.question_number else False

            conf_score = ConfidenceCalculator.calculate(
                question_text=pq.question_text,
                question_number=pq.question_number,
                question_type=pq.question_type,
                options=pq.options,
                base_page_confidence=avg_base_conf,
                answer_matched=is_matched,
            )

            # Inspect question warnings
            q_warnings = WarningDetector.inspect_question(
                question_number=pq.question_number,
                question_text=pq.question_text,
                question_type=pq.question_type,
                options=pq.options,
                confidence=conf_score,
                source_pages=pq.source_pages,
                has_visual_content=pq.has_visual_content,
            )

            needs_review = ConfidenceCalculator.evaluate_needs_review(
                conf_score,
                warnings_count=len(q_warnings),
            )
            if needs_review:
                has_review_items = True

            db_q = Question(
                document_id=doc.id,
                question_number=pq.question_number,
                question_text=pq.question_text,
                question_type=pq.question_type,
                options=pq.options,
                answer=matched_map.get(pq.question_number) if pq.question_number else None,
                source_pages=pq.source_pages,
                confidence=conf_score,
                needs_review=needs_review,
                extraction_metadata=pq.extraction_metadata,
            )
            db.add(db_q)
            db.flush()  # Populates db_q.id

            if pq.question_number:
                db_questions[pq.question_number] = db_q

            # Link question-level warnings
            for qw in q_warnings:
                qw.question_id = db_q.id
                pending_warnings.append(qw)

        # Step 8: Persist Answers and link matched questions
        for pa in extracted_answers:
            norm_q = AnswerKeyParser.normalize_qnum(pa.question_number)
            target_q = db_questions.get(norm_q)

            db_ans = Answer(
                question_id=target_q.id if target_q else None,
                source_document_id=doc.id,
                question_number=pa.question_number,
                answer_text=pa.answer_text,
                confidence=pa.confidence,
                source_page=pa.source_page or (target_q.source_pages[0] if target_q and target_q.source_pages else None),
                matched=pa.matched,
            )
            db.add(db_ans)

            # Check for uncertain matches (e.g., option mismatch, conflicting keys)
            if pa.match_uncertain:
                has_review_items = True
                if "option_mismatch" in (pa.uncertain_reason or ""):
                    if target_q:
                        target_q.needs_review = True
                        target_q.confidence = min(target_q.confidence, 0.55)
                        pending_warnings.append(
                            WarningDetector.inspect_option_mismatch(
                                question_number=pa.question_number,
                                answer_text=pa.answer_text,
                                available_options=list(target_q.options.keys()) if target_q.options else [],
                                question_id=target_q.id,
                                page_number=pa.source_page,
                            )
                        )
                elif "conflicting_answers" in (pa.uncertain_reason or ""):
                    pending_warnings.append(
                        PendingWarning(
                            warning_type=WarningDetector.ANSWER_LOW_CONFIDENCE,
                            message=f"Question {pa.question_number}: {pa.uncertain_reason}",
                            question_id=target_q.id if target_q else None,
                            page_number=pa.source_page,
                            confidence=0.40,
                        )
                    )

            # If unmatched answer, generate warning
            if not pa.matched and doc.document_role != DocumentRole.ANSWER_KEY:
                pending_warnings.append(
                    WarningDetector.inspect_unmatched_answer(
                        question_number=pa.question_number,
                        answer_text=pa.answer_text,
                        source_page=pa.source_page,
                    )
                )

        # Step 9: Persist Warnings
        for pw in pending_warnings:
            db_w = ExtractionWarning(
                document_id=doc.id,
                question_id=pw.question_id,
                warning_type=pw.warning_type,
                message=pw.message,
                page_number=pw.page_number,
                confidence=pw.confidence,
            )
            db.add(db_w)

        # Step 10: Determine Final Status
        doc.progress = 100
        # If there are items needing review or low confidence questions, status is PARTIAL; else COMPLETED
        if has_review_items or any(pw.warning_type in (WarningDetector.LOW_OCR_CONFIDENCE, WarningDetector.OCR_FAILURE) for pw in pending_warnings):
            doc.status = DocumentStatus.PARTIAL
        else:
            doc.status = DocumentStatus.COMPLETED

        db.commit()
        db.refresh(doc)

        # If document belongs to a group, reconcile answers across all group documents
        if doc.group_id:
            try:
                cls.reconcile_group_answers(db, doc.group_id)
            except Exception as exc:
                logger.warning(f"Group answer reconciliation error for group {doc.group_id}: {exc}")

        logger.info(
            f"Extraction completed for document {doc.id}: "
            f"questions={len(parsed_questions)}, answers={len(extracted_answers)}, "
            f"warnings={len(pending_warnings)}, status={doc.status.value}"
        )

        return {
            "status": doc.status.value,
            "document_id": str(doc.id),
            "questions_count": len(parsed_questions),
            "answers_count": len(extracted_answers),
            "warnings_count": len(pending_warnings),
        }

    @classmethod
    def reconcile_group_answers(cls, db: Session, group_id: uuid.UUID) -> Dict[str, Any]:
        """Reconcile and match answers to questions across all documents in a group.
        
        Matches questions from QUESTION_PAPER documents with answers from
        separate ANSWER_KEY documents by normalized question numbers.
        Generates warnings for uncertain matches (option mismatches, conflicting entries)
        and unmatched answers.
        """
        group = db.get(DocumentGroup, group_id)
        if not group:
            return {"status": "group_not_found", "group_id": str(group_id)}

        docs = group.documents
        if not docs:
            return {"status": "empty_group", "group_id": str(group_id)}

        qp_docs = [d for d in docs if d.document_role in (DocumentRole.QUESTION_PAPER, DocumentRole.MIXED, DocumentRole.UNKNOWN)]
        ak_docs = [d for d in docs if d.document_role in (DocumentRole.ANSWER_KEY, DocumentRole.MIXED)]

        # Fallback if roles were not explicitly specified
        if not ak_docs:
            ak_docs = docs
        if not qp_docs:
            qp_docs = docs

        questions = (
            db.query(Question)
            .filter(Question.document_id.in_([d.id for d in qp_docs]))
            .all()
        )
        answers = (
            db.query(Answer)
            .filter(Answer.source_document_id.in_([d.id for d in ak_docs]))
            .all()
        )

        q_map: Dict[str, Question] = {}
        for q in questions:
            if q.question_number:
                norm = AnswerKeyParser.normalize_qnum(q.question_number)
                q_map[norm] = q

        matched_count = 0
        uncertain_count = 0
        unmatched_count = 0

        for ans in answers:
            norm_q = AnswerKeyParser.normalize_qnum(ans.question_number)
            if norm_q in q_map:
                target_q = q_map[norm_q]
                ans.question_id = target_q.id

                # Option compatibility check for MCQs
                is_uncertain = False
                if target_q.question_type == "MCQ" and isinstance(target_q.options, dict) and target_q.options:
                    valid_keys = {str(k).strip().upper() for k in target_q.options.keys()}
                    clean_ans = ans.answer_text.strip().upper()
                    if clean_ans not in valid_keys:
                        is_uncertain = True
                        ans.matched = True  # Associated but uncertain
                        ans.confidence = min(ans.confidence, 0.50)
                        target_q.answer = ans.answer_text
                        target_q.needs_review = True
                        target_q.confidence = min(target_q.confidence, 0.55)
                        uncertain_count += 1

                        warn_msg = (
                            f"Answer key specifies '{ans.answer_text}' for Q{norm_q}, "
                            f"which does not exist in question options {sorted(list(valid_keys))}."
                        )
                        existing_w = db.query(ExtractionWarning).filter(
                            ExtractionWarning.question_id == target_q.id,
                            ExtractionWarning.warning_type == WarningDetector.ANSWER_LOW_CONFIDENCE,
                            ExtractionWarning.message == warn_msg,
                        ).first()
                        if not existing_w:
                            db.add(ExtractionWarning(
                                document_id=target_q.document_id,
                                question_id=target_q.id,
                                warning_type=WarningDetector.ANSWER_LOW_CONFIDENCE,
                                message=warn_msg,
                                confidence=0.50,
                            ))

                if not is_uncertain:
                    ans.matched = True
                    target_q.answer = ans.answer_text
                    avg_conf = (target_q.extraction_metadata or {}).get("avg_page_confidence", 1.0)
                    new_conf = ConfidenceCalculator.calculate(
                        question_text=target_q.question_text,
                        question_number=target_q.question_number,
                        question_type=target_q.question_type,
                        options=target_q.options,
                        base_page_confidence=avg_conf,
                        answer_matched=True,
                    )
                    target_q.confidence = new_conf
                    target_q.needs_review = ConfidenceCalculator.evaluate_needs_review(
                        new_conf, warnings_count=len(target_q.warnings)
                    )
                    matched_count += 1
            else:
                ans.matched = False
                ans.question_id = None
                unmatched_count += 1

                warn_msg = (
                    f"Answer key entry '{ans.question_number}: {ans.answer_text}' could not be matched "
                    f"to any question in document group '{group.name}'."
                )
                existing_w = db.query(ExtractionWarning).filter(
                    ExtractionWarning.document_id == ans.source_document_id,
                    ExtractionWarning.warning_type == WarningDetector.ANSWER_UNMATCHED,
                    ExtractionWarning.message == warn_msg,
                ).first()
                if not existing_w:
                    db.add(ExtractionWarning(
                        document_id=ans.source_document_id,
                        warning_type=WarningDetector.ANSWER_UNMATCHED,
                        message=warn_msg,
                        confidence=0.50,
                    ))

        db.commit()
        return {
            "group_id": str(group_id),
            "matched_count": matched_count,
            "uncertain_count": uncertain_count,
            "unmatched_count": unmatched_count,
        }

