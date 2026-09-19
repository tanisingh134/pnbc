# Pragati Bharti – Document Processing & Question Extraction Service
## Evaluator Demo & Verification Guide

This guide provides a step-by-step walkthrough for evaluating all core features, extraction workflows, edge cases, and security controls of the **Pragati Bharti Service**.

---

### Prerequisites & Quick Setup

Ensure the service stack is up and running via Docker Compose:
```bash
docker compose up --build -d
```
Verify the health endpoint:
```bash
curl -X GET http://localhost:8000/health
```
**Expected Response (`200 OK`)**:
```json
{
  "status": "healthy",
  "app_name": "Pragati Bharti Document Processing Service",
  "environment": "production",
  "database": "connected",
  "redis": "connected"
}
```

Interactive Swagger UI is available at:
👉 **[http://localhost:8000/docs](http://localhost:8000/docs)**

---

### Demo Scenario Matrix

| Step | Scenario | Focus Area | Expected Outcome |
|:---:|---|---|---|
| **1** | User Registration & Login | JWT Auth & Multi-Tenancy | `200 OK` with Bearer access token |
| **2** | PDF Question Paper Upload | Direct Text Extraction | `201 Created` with `document_id` |
| **3** | Processing Status Polling | Async Celery & Redis | Status transitions to `COMPLETED` (100%) |
| **4** | Structured Questions Inspection | Multi-Page & Options | Structured JSON with questions & options |
| **5** | Scanned Image / OCR Upload | OpenCV & Tesseract | Image deskew, binarization, OCR fallback |
| **6** | Answer Key Group Matching | Group Reconciliation | Matches `ANSWER_KEY` to `QUESTION_PAPER` |
| **7** | Low-Confidence & Warning Trigger | Heuristic Quality Engine | Warnings generated, `needs_review=true` |
| **8** | Document Reprocessing | Safe State Cleanse | Re-runs pipeline without duplicate rows |
| **9** | Invalid File Rejections | Security & Integrity Guards | HTTP `400`, `413`, `415`, `401`, `403` |

---

### Step 1: User Registration & Authentication

#### 1.1 Register Evaluator Account
```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "evaluator@pragatibharti.org",
    "password": "SecurePassword123!"
  }'
```
**Expected Response (`201 Created`)**:
```json
{
  "id": "c1f7b0e1-4b1a-4d2a-8b1e-6c0b4e1a2b3c",
  "email": "evaluator@pragatibharti.org",
  "created_at": "2026-09-19T14:30:00.000Z"
}
```

#### 1.2 Authenticate & Obtain Bearer JWT Token
```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "evaluator@pragatibharti.org",
    "password": "SecurePassword123!"
  }'
```
**Expected Response (`200 OK`)**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "token_type": "bearer"
}
```
*Export the token for subsequent curl commands:*
```bash
# In Bash:
export TOKEN="<copied_jwt_access_token>"
# In PowerShell:
$TOKEN="<copied_jwt_access_token>"
```

---

### Step 2: PDF Question Paper Upload

Upload a multi-page examination paper containing questions with multiple options.
```bash
curl -s -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sample_documents/sample_question_paper.pdf;type=application/pdf" \
  -F "document_role=QUESTION_PAPER"
```
**Expected Response (`201 Created`)**:
```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "original_filename": "sample_question_paper.pdf",
  "stored_filename": "d3b07384d113edec49eaa6238ad5ff00.pdf",
  "mime_type": "application/pdf",
  "file_size": 467,
  "file_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "document_role": "QUESTION_PAPER",
  "status": "QUEUED",
  "progress": 0,
  "page_count": null,
  "created_at": "2026-09-19T14:30:00.000Z"
}
```

---

### Step 3: Polling Document Status & Async Progress

Poll the status endpoint while Celery processes the document:
```bash
curl -s -X GET http://localhost:8000/api/v1/documents/7c9e6679-7425-40de-944b-e07fc1f90ae7/status \
  -H "Authorization: Bearer $TOKEN"
```
**Expected Response (`200 OK`)**:
```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "status": "COMPLETED",
  "progress": 100,
  "error_message": null,
  "page_count": 2
}
```

---

### Step 4: Structured Question Output & Multi-Page Stitching

Retrieve extracted questions with normalized options and page mapping:
```bash
curl -s -X GET "http://localhost:8000/api/v1/documents/7c9e6679-7425-40de-944b-e07fc1f90ae7/questions?skip=0&limit=10" \
  -H "Authorization: Bearer $TOKEN"
```
**Key Attributes Verified**:
- **Normalized Options**: Automatically parsed as key-value pairs (`{"A": "...", "B": "...", "C": "...", "D": "..."}`).
- **Multi-Page Stitching**: `source_pages: [1, 2]` demonstrates that questions spanning across page boundaries are stitched into a coherent question item.
- **Confidence Scoring**: Heuristic scoring (e.g., `0.95`) combining boundary recognition, option consistency, and OCR confidence.

```json
{
  "total": 3,
  "skip": 0,
  "limit": 10,
  "items": [
    {
      "id": "2d9b6c11-1234-4567-890a-bcdef1234567",
      "question_number": "1",
      "question_text": "What is the primary function of chlorophyll in plant leaves?",
      "question_type": "MCQ",
      "options": {
        "A": "Absorbing light energy for photosynthesis",
        "B": "Transpiring water to the atmosphere",
        "C": "Storing carbohydrates in roots",
        "D": "Absorbing minerals from the soil"
      },
      "answer": "A",
      "source_pages": [1],
      "confidence": 0.96,
      "needs_review": false,
      "extraction_metadata": {
        "source": "pymupdf_direct",
        "ocr_fallback_used": false
      }
    }
  ]
}
```

---

### Step 5: Scanned Document Ingestion & OCR Fallback

Upload a scanned or image-based document (JPEG/PNG). The pipeline applies OpenCV preprocessing (grayscale, CLAHE contrast enhancement, Hough deskew correction, Otsu thresholding) followed by Pytesseract OCR:
```bash
curl -s -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sample_documents/sample_page.png;type=image/png" \
  -F "document_role=QUESTION_PAPER"
```
Check extraction metadata to verify OCR fallback activation:
```json
{
  "extraction_metadata": {
    "source": "tesseract_ocr",
    "ocr_fallback_used": true,
    "ocr_mean_confidence": 0.88,
    "deskew_angle_deg": 1.2
  }
}
```

---

### Step 6: Separate Answer Key Upload & Cross-Document Matching

#### 6.1 Create a Document Group
```bash
curl -s -X POST http://localhost:8000/api/v1/document-groups \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Science Exam 2026",
    "description": "Batch containing Question Paper and Official Answer Key"
  }'
```
*Returns `group_id`: `a5c2e140-5555-4444-3333-222211110000`.*

#### 6.2 Upload Answer Key & Assign to Group
```bash
curl -s -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sample_documents/sample_key.jpg;type=image/jpeg" \
  -F "document_role=ANSWER_KEY"
```
Attach both documents to the group:
```bash
curl -s -X POST "http://localhost:8000/api/v1/document-groups/a5c2e140-5555-4444-3333-222211110000/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "document_ids": [
      "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "<answer_key_document_id>"
    ]
  }'
```
**Automatic Reconciliation**:
The pipeline reconciles answer entries from `sample_key.jpg` with questions in `sample_question_paper.pdf` matching on normalized question numbers (`1` $\leftrightarrow$ `Q1`). The questions' `answer` field is automatically populated.

---

### Step 7: Low-Confidence Warning & Review Flagging

When OCR quality degrades or answer entries exhibit anomalies (such as conflicting duplicate keys or MCQ options out-of-range), the system flags them:
```bash
curl -s -X GET "http://localhost:8000/api/v1/documents/7c9e6679-7425-40de-944b-e07fc1f90ae7/warnings" \
  -H "Authorization: Bearer $TOKEN"
```
**Expected Response (`200 OK`)**:
```json
[
  {
    "id": "8a7b6c55-4444-5555-6666-777788889999",
    "warning_type": "ANSWER_LOW_CONFIDENCE",
    "message": "Answer key specified option 'E', but question only has options A through D.",
    "page_number": 2,
    "confidence": 0.45,
    "created_at": "2026-09-19T14:30:02.000Z"
  },
  {
    "id": "9f8e7d6c-3333-4444-5555-666677778888",
    "warning_type": "LOW_OCR_CONFIDENCE",
    "message": "Page 2 OCR average confidence 58.2% is below threshold 60.0%. Some characters may require review.",
    "page_number": 2,
    "confidence": 0.58,
    "created_at": "2026-09-19T14:30:01.000Z"
  }
]
```

---

### Step 8: Document Reprocessing (`POST /documents/{id}/reprocess`)

To safely re-trigger the extraction pipeline (e.g., after updating OCR models or assigning an answer key) without generating duplicate database records:
```bash
curl -s -X POST "http://localhost:8000/api/v1/documents/7c9e6679-7425-40de-944b-e07fc1f90ae7/reprocess" \
  -H "Authorization: Bearer $TOKEN"
```
**Behavior**:
1. Atomically purges prior `questions`, `answers`, and `extraction_warnings` linked to the document.
2. Resets status to `QUEUED` and progress to `0`.
3. Dispatches a clean Celery processing task.
4. Guaranteed zero duplicate questions upon completion.

---

### Step 9: Edge Case & Security Validation

#### 9.1 Empty File Rejection (0 Bytes)
```bash
touch empty.pdf
curl -s -w "\nHTTP: %{http_code}\n" -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@empty.pdf;type=application/pdf"
```
**Expected Outcome**: `HTTP 400 Bad Request` with message: `"Uploaded file is empty (0 bytes)."`

#### 9.2 Spoofed File Extension (Fake PDF / Executable)
```bash
echo "MALICIOUS_EXE_PAYLOAD" > fake.pdf
curl -s -w "\nHTTP: %{http_code}\n" -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@fake.pdf;type=application/pdf"
```
**Expected Outcome**: `HTTP 400 Bad Request` with message: `"File content does not match genuine PDF structure or magic bytes."`

#### 9.3 Disallowed Extension (.exe, .sh, .txt)
```bash
echo "script content" > test.sh
curl -s -w "\nHTTP: %{http_code}\n" -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test.sh;type=application/x-sh"
```
**Expected Outcome**: `HTTP 415 Unsupported Media Type` with allowed extensions `.pdf`, `.jpg`, `.jpeg`, `.png`.

#### 9.4 Missing / Invalid Authentication
```bash
curl -s -w "\nHTTP: %{http_code}\n" -X GET http://localhost:8000/api/v1/auth/me
```
**Expected Outcome**: `HTTP 401 Unauthorized` with detail `"Not authenticated"`.

#### 9.5 Multi-Tenant Isolation Protection
When User B attempts to access a document created by User A:
```bash
# Authenticate as User B and request User A's document:
curl -s -w "\nHTTP: %{http_code}\n" -X GET "http://localhost:8000/api/v1/documents/7c9e6679-7425-40de-944b-e07fc1f90ae7" \
  -H "Authorization: Bearer $USER_B_TOKEN"
```
**Expected Outcome**: `HTTP 403 Forbidden` or `HTTP 404 Not Found`. Documents are strictly isolated by `owner_id`.
