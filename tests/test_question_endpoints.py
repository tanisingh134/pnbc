import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.document import Document, DocumentRole, DocumentStatus
from app.models.question import Question
from app.models.user import User
from app.models.warning import ExtractionWarning


def create_sample_document_with_data(
    db_session: Session,
    owner: User,
) -> Document:
    """Helper to populate a complete document with questions, answers, and warnings."""
    doc = Document(
        owner_id=owner.id,
        original_filename="exam.pdf",
        stored_filename=f"{uuid.uuid4().hex}.pdf",
        mime_type="application/pdf",
        file_size=1024,
        file_hash="dummyhash123",
        document_role=DocumentRole.QUESTION_PAPER,
        status=DocumentStatus.COMPLETED,
        progress=100,
        page_count=2,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    # Add questions
    for i in range(1, 6):
        q = Question(
            document_id=doc.id,
            question_number=str(i),
            question_text=f"What is question number {i}?",
            question_type="MCQ",
            options={"A": f"Opt A{i}", "B": f"Opt B{i}"},
            answer="A" if i % 2 == 1 else "B",
            source_pages=[1] if i <= 3 else [1, 2],
            confidence=0.95 if i != 5 else 0.55,
            needs_review=(i == 5),
            extraction_metadata={"index": i},
        )
        db_session.add(q)
        db_session.commit()
        db_session.refresh(q)

        # Add answer entry
        ans = Answer(
            question_id=q.id,
            source_document_id=doc.id,
            question_number=str(i),
            answer_text="A" if i % 2 == 1 else "B",
            confidence=0.98,
            source_page=1,
            matched=True,
        )
        db_session.add(ans)

        if i == 5:
            warn = ExtractionWarning(
                document_id=doc.id,
                question_id=q.id,
                warning_type="OPTION_PARSE_UNCERTAIN",
                message="Only 2 options found for MCQ",
                page_number=2,
                confidence=0.55,
            )
            db_session.add(warn)

    db_session.commit()
    db_session.refresh(doc)
    return doc


def test_get_document_questions_paginated(
    client: TestClient,
    db_session: Session,
    test_user_a: User,
    auth_headers_user_a: dict,
):
    doc = create_sample_document_with_data(db_session, test_user_a)

    # Page 1: limit 2
    res = client.get(
        f"/api/v1/documents/{doc.id}/questions?skip=0&limit=2",
        headers=auth_headers_user_a,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    assert data["skip"] == 0
    assert data["limit"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["question_number"] == "1"
    assert data["items"][1]["question_number"] == "2"

    # Page 2: skip 2, limit 3
    res2 = client.get(
        f"/api/v1/documents/{doc.id}/questions?skip=2&limit=3",
        headers=auth_headers_user_a,
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert len(data2["items"]) == 3
    assert data2["items"][0]["question_number"] == "3"


def test_get_single_question_by_id(
    client: TestClient,
    db_session: Session,
    test_user_a: User,
    auth_headers_user_a: dict,
):
    doc = create_sample_document_with_data(db_session, test_user_a)
    first_q = doc.questions[0]

    res = client.get(f"/api/v1/questions/{first_q.id}", headers=auth_headers_user_a)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(first_q.id)
    assert data["question_number"] == "1"
    assert data["question_text"] == first_q.question_text
    assert len(data["answers"]) >= 1


def test_get_document_answers(
    client: TestClient,
    db_session: Session,
    test_user_a: User,
    auth_headers_user_a: dict,
):
    doc = create_sample_document_with_data(db_session, test_user_a)

    res = client.get(f"/api/v1/documents/{doc.id}/answers", headers=auth_headers_user_a)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 5
    assert data[0]["matched"] is True


def test_get_document_warnings(
    client: TestClient,
    db_session: Session,
    test_user_a: User,
    auth_headers_user_a: dict,
):
    doc = create_sample_document_with_data(db_session, test_user_a)

    res = client.get(f"/api/v1/documents/{doc.id}/warnings", headers=auth_headers_user_a)
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert data[0]["warning_type"] == "OPTION_PARSE_UNCERTAIN"


def test_question_endpoints_multi_tenant_authorization(
    client: TestClient,
    db_session: Session,
    test_user_a: User,
    test_user_b: User,
    auth_headers_user_b: dict,
):
    """Ensure User B cannot access User A's questions, answers, or warnings."""
    doc_user_a = create_sample_document_with_data(db_session, test_user_a)
    q_user_a = doc_user_a.questions[0]

    # User B tries to get questions of User A's document -> 403
    res1 = client.get(
        f"/api/v1/documents/{doc_user_a.id}/questions",
        headers=auth_headers_user_b,
    )
    assert res1.status_code == 403

    # User B tries to get answers of User A's document -> 403
    res2 = client.get(
        f"/api/v1/documents/{doc_user_a.id}/answers",
        headers=auth_headers_user_b,
    )
    assert res2.status_code == 403

    # User B tries to get warnings of User A's document -> 403
    res3 = client.get(
        f"/api/v1/documents/{doc_user_a.id}/warnings",
        headers=auth_headers_user_b,
    )
    assert res3.status_code == 403

    # User B tries to get individual question of User A -> 403
    res4 = client.get(
        f"/api/v1/questions/{q_user_a.id}",
        headers=auth_headers_user_b,
    )
    assert res4.status_code == 403


def test_end_to_end_document_processing_pipeline(
    client: TestClient,
    db_session: Session,
    temp_storage_dir: str,
    test_user_a: User,
    auth_headers_user_a: dict,
):
    """End-to-end test: process a multi-page PDF with questions and answer key, verify extraction & API."""
    import io
    import fitz
    from app.services.extraction.pipeline import DocumentProcessingPipeline
    from app.services.storage.local import LocalStorageService

    # 1. Dynamically generate a valid 2-page test PDF with PyMuPDF
    pdf_doc = fitz.open()
    
    p1 = pdf_doc.new_page()
    p1_text = (
        "Pragati Bharti Examination\n\n"
        "1. What is the speed of light in vacuum?\n"
        "A. 300,000 km/s\n"
        "B. 150,000 km/s\n"
        "C. 1,000 km/s\n"
        "D. 300 km/s\n\n"
        "2. Which gas is absorbed by plants during photosynthesis?\n"
        "(A) Nitrogen\n"
        "(B) Carbon Dioxide\n"
        "(C) Oxygen\n"
        "(D) Argon\n"
    )
    p1.insert_text((50, 72), p1_text)

    p2 = pdf_doc.new_page()
    p2_text = (
        "3. Explain Newton's first law of motion in your own words.\n\n"
        "ANSWER KEY\n"
        "1. A\n"
        "2. B\n"
    )
    p2.insert_text((50, 72), p2_text)

    pdf_bytes = pdf_doc.tobytes()
    pdf_doc.close()

    # 2. Save file via local storage service
    storage = LocalStorageService(temp_storage_dir)
    stored_name = f"{uuid.uuid4().hex}.pdf"
    storage.save(io.BytesIO(pdf_bytes), stored_name)

    # 3. Create document record
    doc = Document(
        owner_id=test_user_a.id,
        original_filename="physics_exam.pdf",
        stored_filename=stored_name,
        mime_type="application/pdf",
        file_size=len(pdf_bytes),
        file_hash="dummy_hash_for_test",
        document_role=DocumentRole.QUESTION_PAPER,
        status=DocumentStatus.QUEUED,
        progress=0,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    # 4. Run end-to-end extraction pipeline
    result = DocumentProcessingPipeline.process_document(
        db=db_session,
        document_id=doc.id,
        storage_service=storage,
    )

    assert result["status"] in ("COMPLETED", "PARTIAL")
    assert result["questions_count"] >= 3
    assert result["answers_count"] == 2

    # 5. Check document status endpoint
    status_res = client.get(f"/api/v1/documents/{doc.id}/status", headers=auth_headers_user_a)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["status"] in ("COMPLETED", "PARTIAL")
    assert status_data["progress"] == 100
    assert status_data["page_count"] == 2

    # 6. Retrieve paginated questions
    q_res = client.get(f"/api/v1/documents/{doc.id}/questions", headers=auth_headers_user_a)
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert q_data["total"] >= 3
    questions = q_data["items"]
    
    q1 = next((q for q in questions if q["question_number"] == "1"), None)
    assert q1 is not None
    assert "speed of light" in q1["question_text"].lower()
    assert q1["question_type"] == "MCQ"
    assert q1["options"] is not None
    assert "300,000 km/s" in q1["options"].get("A", "")
    assert q1["answer"] == "A"
    assert q1["confidence"] >= 0.80

    # 7. Check individual question endpoint
    single_res = client.get(f"/api/v1/questions/{q1['id']}", headers=auth_headers_user_a)
    assert single_res.status_code == 200
    single_data = single_res.json()
    assert single_data["id"] == q1["id"]
    assert len(single_data["answers"]) == 1
    assert single_data["answers"][0]["answer_text"] == "A"

    # 8. Retrieve answers
    ans_res = client.get(f"/api/v1/documents/{doc.id}/answers", headers=auth_headers_user_a)
    assert ans_res.status_code == 200
    ans_data = ans_res.json()
    assert len(ans_data) == 2
    ans_map = {a["question_number"]: a for a in ans_data}
    assert ans_map["1"]["answer_text"] == "A"
    assert ans_map["1"]["matched"] is True
    assert ans_map["2"]["answer_text"] == "B"
    assert ans_map["2"]["matched"] is True
