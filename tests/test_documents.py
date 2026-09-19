import io
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


def test_upload_valid_pdf(client: TestClient, auth_headers_user_a, sample_pdf_bytes):
    """Test successful upload of valid PDF file."""
    files = {"file": ("question_paper.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    data = {"document_role": "QUESTION_PAPER"}

    response = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files, data=data)
    assert response.status_code == 201
    result = response.json()

    assert "id" in result
    assert result["original_filename"] == "question_paper.pdf"
    assert result["mime_type"] == "application/pdf"
    assert result["file_size"] == len(sample_pdf_bytes)
    assert len(result["file_hash"]) == 64  # SHA-256
    assert result["document_role"] == "QUESTION_PAPER"
    assert result["status"] in ["QUEUED", "COMPLETED"]  # With eager Celery, might transition to COMPLETED


def test_upload_valid_png(client: TestClient, auth_headers_user_a, sample_png_bytes):
    """Test successful upload of valid PNG image."""
    files = {"file": ("page1.png", io.BytesIO(sample_png_bytes), "image/png")}
    data = {"document_role": "ANSWER_KEY"}

    response = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files, data=data)
    assert response.status_code == 201
    result = response.json()

    assert result["original_filename"] == "page1.png"
    assert result["mime_type"] == "image/png"
    assert result["file_size"] == len(sample_png_bytes)


def test_upload_valid_jpg(client: TestClient, auth_headers_user_a, sample_jpg_bytes):
    """Test successful upload of valid JPG image."""
    files = {"file": ("page2.jpg", io.BytesIO(sample_jpg_bytes), "image/jpeg")}
    data = {"document_role": "MIXED"}

    response = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files, data=data)
    assert response.status_code == 201
    result = response.json()

    assert result["original_filename"] == "page2.jpg"
    assert result["mime_type"] == "image/jpeg"
    assert result["document_role"] == "MIXED"


def test_upload_unsupported_extension(client: TestClient, auth_headers_user_a):
    """Test upload is rejected for unsupported file extensions (.txt, .exe)."""
    # Text file
    files = {"file": ("malicious.txt", io.BytesIO(b"Hello world text file"), "text/plain")}
    response = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    assert response.status_code == 415

    # Executable file
    files = {"file": ("malware.exe", io.BytesIO(b"MZ\x90\x00\x03\x00"), "application/x-msdownload")}
    response = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    assert response.status_code == 415


def test_upload_corrupt_file_signature(client: TestClient, auth_headers_user_a):
    """Test upload with spoofed extension but invalid header bytes returns 400 Bad Request."""
    # Named .pdf but binary content is plain text
    files = {"file": ("fake_paper.pdf", io.BytesIO(b"This is definitely not a real PDF file"), "application/pdf")}
    response = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()


def test_upload_empty_file(client: TestClient, auth_headers_user_a):
    """Test empty file (0 bytes) is rejected with 400 Bad Request."""
    files = {"file": ("empty_file.pdf", io.BytesIO(b""), "application/pdf")}
    response = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_upload_oversized_file(client: TestClient, auth_headers_user_a, monkeypatch):
    """Test file exceeding size limit is rejected with 413 Payload Too Large."""
    # Temporarily set max size to 1KB for fast deterministic testing
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.001)  # ~1048 bytes

    # Generate 5KB fake PDF (valid header but oversized)
    oversized_data = b"%PDF-1.4\n" + b"A" * 5000
    files = {"file": ("oversized.pdf", io.BytesIO(oversized_data), "application/pdf")}

    response = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"].lower()


def test_upload_unauthorized(client: TestClient, sample_pdf_bytes):
    """Test unauthenticated upload attempt returns 401."""
    files = {"file": ("paper.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    response = client.post("/api/v1/documents", files=files)
    assert response.status_code == 401


def test_get_document_status_and_detail(client: TestClient, auth_headers_user_a, sample_pdf_bytes):
    """Test retrieving document status and full metadata."""
    # 1. Upload document
    files = {"file": ("test_doc.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    upload_res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # 2. Poll status endpoint
    status_res = client.get(f"/api/v1/documents/{doc_id}/status", headers=auth_headers_user_a)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["id"] == doc_id
    assert "status" in status_data
    assert "progress" in status_data

    # 3. Retrieve full document details
    detail_res = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers_user_a)
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["id"] == doc_id
    assert detail_data["original_filename"] == "test_doc.pdf"
    assert "questions" in detail_data
    assert "warnings" in detail_data


def test_unauthorized_document_access(
    client: TestClient, auth_headers_user_a, auth_headers_user_b, sample_pdf_bytes
):
    """Test multi-tenant isolation: User B cannot view or poll User A's document."""
    # User A uploads a document
    files = {"file": ("user_a_private.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    upload_res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    doc_id = upload_res.json()["id"]

    # User B tries to view User A's document -> 403 Forbidden
    get_res = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers_user_b)
    assert get_res.status_code == 403

    # User B tries to poll status -> 403 Forbidden
    status_res = client.get(f"/api/v1/documents/{doc_id}/status", headers=auth_headers_user_b)
    assert status_res.status_code == 403


def test_get_nonexistent_document(client: TestClient, auth_headers_user_a):
    """Test retrieving non-existent document ID returns 404 Not Found."""
    fake_id = uuid.uuid4()
    response = client.get(f"/api/v1/documents/{fake_id}", headers=auth_headers_user_a)
    assert response.status_code == 404
