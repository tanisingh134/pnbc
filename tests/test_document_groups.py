import io
import uuid
from fastapi.testclient import TestClient


def test_create_and_get_document_group(client: TestClient, auth_headers_user_a):
    """Test creating a document group and retrieving its details."""
    payload = {
        "name": "Mid-Term Examination 2026",
        "description": "Question papers and answer keys for class 10",
    }
    create_res = client.post("/api/v1/document-groups", headers=auth_headers_user_a, json=payload)
    assert create_res.status_code == 201
    group_data = create_res.json()
    assert "id" in group_data
    assert group_data["name"] == payload["name"]
    assert group_data["description"] == payload["description"]
    group_id = group_data["id"]

    # Get group details
    get_res = client.get(f"/api/v1/document-groups/{group_id}", headers=auth_headers_user_a)
    assert get_res.status_code == 200
    detail = get_res.json()
    assert detail["id"] == group_id
    assert detail["documents"] == []


def test_assign_document_to_group_via_patch(
    client: TestClient, auth_headers_user_a, sample_pdf_bytes
):
    """Test assigning a document to a group via PATCH /documents/{id}/group."""
    # 1. Create group
    group_res = client.post(
        "/api/v1/document-groups",
        headers=auth_headers_user_a,
        json={"name": "Science Group"},
    )
    group_id = group_res.json()["id"]

    # 2. Upload document without group
    files = {"file": ("paper.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    doc_res = client.post("/api/v1/documents", headers=auth_headers_user_a, files=files)
    doc_id = doc_res.json()["id"]

    # 3. Associate document with group
    patch_res = client.patch(
        f"/api/v1/documents/{doc_id}/group",
        headers=auth_headers_user_a,
        json={"group_id": group_id},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["group_id"] == group_id

    # 4. Check that group now lists the document
    group_detail_res = client.get(f"/api/v1/document-groups/{group_id}", headers=auth_headers_user_a)
    assert group_detail_res.status_code == 200
    docs = group_detail_res.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["id"] == doc_id


def test_batch_associate_documents(
    client: TestClient, auth_headers_user_a, sample_pdf_bytes, sample_png_bytes
):
    """Test batch associating multiple documents to a group."""
    # 1. Create group
    group_res = client.post(
        "/api/v1/document-groups",
        headers=auth_headers_user_a,
        json={"name": "Batch Group"},
    )
    group_id = group_res.json()["id"]

    # 2. Upload two documents
    file1 = {"file": ("doc1.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    res1 = client.post("/api/v1/documents", headers=auth_headers_user_a, files=file1)
    doc1_id = res1.json()["id"]

    file2 = {"file": ("doc2.png", io.BytesIO(sample_png_bytes), "image/png")}
    res2 = client.post("/api/v1/documents", headers=auth_headers_user_a, files=file2)
    doc2_id = res2.json()["id"]

    # 3. Batch associate
    batch_res = client.post(
        f"/api/v1/document-groups/{group_id}/documents",
        headers=auth_headers_user_a,
        json={"document_ids": [doc1_id, doc2_id]},
    )
    assert batch_res.status_code == 200
    batch_detail = batch_res.json()
    assert len(batch_detail["documents"]) == 2


def test_document_group_authorization_isolation(
    client: TestClient, auth_headers_user_a, auth_headers_user_b
):
    """Test User B cannot access User A's document group."""
    # User A creates group
    group_res = client.post(
        "/api/v1/document-groups",
        headers=auth_headers_user_a,
        json={"name": "User A Private Group"},
    )
    group_id = group_res.json()["id"]

    # User B tries to get User A's group -> 403 Forbidden
    get_res = client.get(f"/api/v1/document-groups/{group_id}", headers=auth_headers_user_b)
    assert get_res.status_code == 403


def test_get_nonexistent_group(client: TestClient, auth_headers_user_a):
    """Test retrieving non-existent group returns 404 Not Found."""
    fake_id = uuid.uuid4()
    response = client.get(f"/api/v1/document-groups/{fake_id}", headers=auth_headers_user_a)
    assert response.status_code == 404
