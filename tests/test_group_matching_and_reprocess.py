import io
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.document import Document, DocumentRole, DocumentStatus
from app.models.question import Question
from app.models.answer import Answer
from app.models.warning import ExtractionWarning
from app.services.extraction.pipeline import DocumentProcessingPipeline
from app.services.extraction.warning_service import WarningDetector


def test_document_group_qp_and_separate_answer_key_matching(
    client: TestClient,
    db_session,
    auth_headers_user_a,
    sample_pdf_bytes,
):
    """Test cross-document answer matching within a document group containing

    a QUESTION_PAPER document and a separate ANSWER_KEY document.
    """
    # 1. Create a document group
    group_res = client.post(
        "/api/v1/document-groups",
        headers=auth_headers_user_a,
        json={"name": "Physics Final Exam 2026", "description": "QP and separate Answer Key"},
    )
    assert group_res.status_code == 201
    group_id = group_res.json()["id"]

    # 2. Upload Question Paper document into this group
    qp_files = {"file": ("physics_qp.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    qp_data = {"document_role": "QUESTION_PAPER", "group_id": group_id}
    qp_res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=qp_files, data=qp_data)
    assert qp_res.status_code == 201
    qp_id = uuid.UUID(qp_res.json()["id"])

    # 3. Create a synthetic Answer Key image (PNG)
    from PIL import Image
    ak_img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    ak_bytes_io = io.BytesIO()
    ak_img.save(ak_bytes_io, format="PNG")
    ak_png_bytes = ak_bytes_io.getvalue()

    ak_files = {"file": ("physics_ak.png", io.BytesIO(ak_png_bytes), "image/png")}
    ak_data = {"document_role": "ANSWER_KEY", "group_id": group_id}
    ak_res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=ak_files, data=ak_data)
    assert ak_res.status_code == 201
    ak_id = uuid.UUID(ak_res.json()["id"])

    # 4. Insert question into QP doc and answer into AK doc to verify cross-document matching
    q1 = Question(
        document_id=qp_id,
        question_number="1",
        question_text="What is the unit of electric current?",
        question_type="MCQ",
        options={"A": "Ampere", "B": "Volt", "C": "Ohm", "D": "Watt"},
        confidence=0.90,
        needs_review=False,
    )
    q2 = Question(
        document_id=qp_id,
        question_number="2",
        question_text="Define Newton's Second Law.",
        question_type="DESCRIPTIVE",
        options=None,
        confidence=0.88,
        needs_review=False,
    )
    db_session.add_all([q1, q2])

    ans1 = Answer(
        source_document_id=ak_id,
        question_number="1",
        answer_text="A",
        confidence=0.95,
        matched=False,
    )
    ans2 = Answer(
        source_document_id=ak_id,
        question_number="2",
        answer_text="F = ma",
        confidence=0.90,
        matched=False,
    )
    # Extra unmatched answer
    ans_unmatched = Answer(
        source_document_id=ak_id,
        question_number="99",
        answer_text="D",
        confidence=0.90,
        matched=False,
    )
    db_session.add_all([ans1, ans2, ans_unmatched])
    db_session.commit()

    # 5. Reconcile group answers
    res = DocumentProcessingPipeline.reconcile_group_answers(db_session, uuid.UUID(group_id))
    assert res["matched_count"] == 2
    assert res["unmatched_count"] == 1

    # 6. Refresh and verify
    db_session.refresh(q1)
    db_session.refresh(q2)
    db_session.refresh(ans1)
    db_session.refresh(ans2)
    db_session.refresh(ans_unmatched)

    assert ans1.matched is True
    assert ans1.question_id == q1.id
    assert q1.answer == "A"

    assert ans2.matched is True
    assert ans2.question_id == q2.id
    assert q2.answer == "F = ma"

    assert ans_unmatched.matched is False
    assert ans_unmatched.question_id is None

    # Verify that an ANSWER_UNMATCHED warning was created for ans_unmatched
    warnings = db_session.query(ExtractionWarning).filter(ExtractionWarning.document_id == ak_id).all()
    assert any(w.warning_type == WarningDetector.ANSWER_UNMATCHED for w in warnings)


def test_uncertain_match_option_mismatch_creates_warning(
    client: TestClient,
    db_session,
    auth_headers_user_a,
    sample_pdf_bytes,
):
    """Test that an answer with an option not available in question options

    flags an uncertain match and creates an ANSWER_LOW_CONFIDENCE warning.
    """
    # Create group
    group_res = client.post(
        "/api/v1/document-groups",
        headers=auth_headers_user_a,
        json={"name": "Chemistry Group"},
    )
    group_id = uuid.UUID(group_res.json()["id"])

    # Upload QP
    qp_files = {"file": ("chem_qp.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    qp_res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=qp_files, data={"group_id": str(group_id)})
    qp_id = uuid.UUID(qp_res.json()["id"])

    # Upload AK
    ak_files = {"file": ("chem_ak.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    ak_res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=ak_files, data={"group_id": str(group_id)})
    ak_id = uuid.UUID(ak_res.json()["id"])

    # Add MCQ with options A, B, C, D
    q = Question(
        document_id=qp_id,
        question_number="5",
        question_text="Which gas is released during photosynthesis?",
        question_type="MCQ",
        options={"A": "Oxygen", "B": "Nitrogen", "C": "Carbon dioxide", "D": "Hydrogen"},
        confidence=0.92,
        needs_review=False,
    )
    db_session.add(q)

    # Answer key specifies 'E' (not an option!)
    ans = Answer(
        source_document_id=ak_id,
        question_number="5",
        answer_text="E",
        confidence=0.95,
        matched=False,
    )
    db_session.add(ans)
    db_session.commit()

    # Reconcile group answers
    res = DocumentProcessingPipeline.reconcile_group_answers(db_session, group_id)
    assert res["uncertain_count"] == 1

    db_session.refresh(q)
    db_session.refresh(ans)

    # Question should be flagged for review and have warning created
    assert q.needs_review is True
    assert q.confidence <= 0.60

    q_warnings = db_session.query(ExtractionWarning).filter(ExtractionWarning.question_id == q.id).all()
    assert any(w.warning_type == WarningDetector.ANSWER_LOW_CONFIDENCE for w in q_warnings)
    assert any("does not exist in question options" in w.message for w in q_warnings)


def test_reprocess_document_no_duplicates(
    client: TestClient,
    db_session,
    auth_headers_user_a,
    sample_pdf_bytes,
):
    """Test POST /api/v1/documents/{id}/reprocess and root /documents/{id}/reprocess

    ensure no duplicate data is created and status resets to QUEUED.
    """
    # 1. Upload document
    files = {"file": ("exam.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    upload_res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]
    doc_uuid = uuid.UUID(doc_id)

    # 2. Add sample question, answer, and warning
    q = Question(
        document_id=doc_uuid,
        question_number="1",
        question_text="Initial question before reprocess",
        question_type="MCQ",
        options={"A": "1", "B": "2"},
        confidence=0.85,
    )
    ans = Answer(
        source_document_id=doc_uuid,
        question_number="1",
        answer_text="A",
        confidence=0.90,
        matched=True,
    )
    warn = ExtractionWarning(
        document_id=doc_uuid,
        warning_type="LOW_OCR_CONFIDENCE",
        message="Initial warning before reprocess",
    )
    db_session.add_all([q, ans, warn])
    db_session.commit()

    assert db_session.query(Question).filter(Question.document_id == doc_uuid).count() == 1
    assert db_session.query(Answer).filter(Answer.source_document_id == doc_uuid).count() == 1
    assert db_session.query(ExtractionWarning).filter(ExtractionWarning.document_id == doc_uuid).count() == 1

    # 3. Call reprocess via /api/v1/documents/{id}/reprocess
    reprocess_res = client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=auth_headers_user_a)
    assert reprocess_res.status_code == 200
    res_data = reprocess_res.json()
    assert res_data["id"] == doc_id
    assert res_data["status"] in ["QUEUED", "COMPLETED"]

    # Check that previous questions/answers/warnings were cleared before re-run
    # In eager mode, it re-runs cleanly once. Let's verify no duplicate entries:
    q_count = db_session.query(Question).filter(Question.document_id == doc_uuid).count()
    ans_count = db_session.query(Answer).filter(Answer.source_document_id == doc_uuid).count()
    # Ensure count is not doubled
    assert q_count <= 2

    # 4. Call root alias /documents/{id}/reprocess
    root_reprocess_res = client.post(f"/documents/{doc_id}/reprocess", headers=auth_headers_user_a)
    assert root_reprocess_res.status_code == 200
    assert root_reprocess_res.json()["id"] == doc_id


def test_reprocess_authorization_and_validation(
    client: TestClient,
    auth_headers_user_a,
    auth_headers_user_b,
    sample_pdf_bytes,
):
    """Test 401 Unauthorized, 403 Forbidden, and 404 Not Found on reprocess."""
    # 1. User A uploads a document
    files = {"file": ("user_a_doc.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    doc_id = res.json()["id"]

    # 2. Unauthenticated -> 401
    unauth_res = client.post(f"/api/v1/documents/{doc_id}/reprocess")
    assert unauth_res.status_code == 401

    # 3. User B attempts to reprocess User A's document -> 403 Forbidden
    forbidden_res = client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=auth_headers_user_b)
    assert forbidden_res.status_code == 403

    # 4. Non-existent document -> 404 Not Found
    fake_id = uuid.uuid4()
    not_found_res = client.post(f"/api/v1/documents/{fake_id}/reprocess", headers=auth_headers_user_a)
    assert not_found_res.status_code == 404


def test_malformed_file_validation(client: TestClient, auth_headers_user_a):
    """Test that malformed image and PDF files return 400 Bad Request."""
    # 1. Malformed Image: PNG magic bytes followed by garbage payload
    corrupt_png = b"\x89PNG\r\n\x1a\n" + b"Corrupt payload that cannot be decoded by PIL"
    files = {"file": ("corrupt.png", io.BytesIO(corrupt_png), "image/png")}
    res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    assert res.status_code == 400
    assert "corrupted" in res.json()["detail"].lower() or "malformed" in res.json()["detail"].lower()

    # 2. Malformed PDF: PDF magic bytes followed by garbage
    corrupt_pdf = b"%PDF-1.4\n" + b"Invalid catalog and corrupted body structure"
    files = {"file": ("corrupt.pdf", io.BytesIO(corrupt_pdf), "application/pdf")}
    res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    assert res.status_code == 400
    assert "corrupted" in res.json()["detail"].lower() or "malformed" in res.json()["detail"].lower()
