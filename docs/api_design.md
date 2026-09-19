# Pragati Bharti – Document Processing & Question Extraction Service
## REST API Design & Specification

All API endpoints (except system health and root documentation) are prefixed with `/api/v1`.

### Standard Headers
- For authenticated routes: `Authorization: Bearer <JWT_ACCESS_TOKEN>`
- For multipart uploads: `Content-Type: multipart/form-data`
- For JSON payloads: `Content-Type: application/json`

---

### Endpoints Overview

| Method | Path | Auth Required | Description |
|---|---|---|---|
| `GET` | `/health` | No | System health check (Database, Redis, API) |
| `GET` | `/docs` | No | Interactive Swagger UI documentation |
| `GET` | `/openapi.json` | No | OpenAPI 3.1 JSON schema |
| `POST` | `/api/v1/auth/register` | No | Register new user account |
| `POST` | `/api/v1/auth/login` | No | Authenticate user and receive Bearer JWT |
| `GET` | `/api/v1/auth/me` | Yes | Get authenticated user profile |
| `POST` | `/api/v1/documents` | Yes | Upload document (PDF/PNG/JPEG) |
| `GET` | `/api/v1/documents/{document_id}` | Yes | Fetch document record, questions & warnings |
| `GET` | `/api/v1/documents/{document_id}/status` | Yes | Poll document processing state and progress |
| `POST` | `/api/v1/documents/{document_id}/reprocess` | Yes | Reprocess document (idempotent, no duplicates) |
| `GET` | `/api/v1/documents/{document_id}/questions` | Yes | List extracted questions for document (paginated) |
| `GET` | `/api/v1/questions/{question_id}` | Yes | Retrieve individual question with options, answers & warnings |
| `GET` | `/api/v1/documents/{document_id}/answers` | Yes | List extracted answer key entries for document |
| `GET` | `/api/v1/documents/{document_id}/warnings` | Yes | List extraction warnings and review flags for document |
| `PATCH` | `/api/v1/documents/{document_id}/group` | Yes | Assign or disassociate document group |
| `POST` | `/api/v1/document-groups` | Yes | Create document group |
| `GET` | `/api/v1/document-groups/{group_id}` | Yes | Get document group and associated documents |
| `POST` | `/api/v1/document-groups/{group_id}/documents` | Yes | Batch associate documents to a group |

---

### Detailed Request & Response Specifications

#### 1. System Health
- **Endpoint**: `GET /health`
- **Response `200 OK`**:
```json
{
  "status": "healthy",
  "app_name": "Pragati Bharti Document Processing Service",
  "environment": "development",
  "database": "connected",
  "redis": "connected"
}
```

#### 2. User Registration
- **Endpoint**: `POST /api/v1/auth/register`
- **Request Body**:
```json
{
  "email": "user@example.com",
  "password": "strongpassword123"
}
```
- **Response `201 Created`**:
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "email": "user@example.com",
  "created_at": "2026-09-19T12:00:00.000Z"
}
```
- **Errors**: `400 Bad Request` (invalid email or short password), `409 Conflict` (email already exists).

#### 3. User Login
- **Endpoint**: `POST /api/v1/auth/login`
- **Request Body**:
```json
{
  "email": "user@example.com",
  "password": "strongpassword123"
}
```
- **Response `200 OK`**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```
- **Errors**: `401 Unauthorized` (incorrect credentials).

#### 4. Document Upload
- **Endpoint**: `POST /api/v1/documents`
- **Headers**: `Authorization: Bearer <TOKEN>`
- **Content-Type**: `multipart/form-data`
- **Form Fields**:
  - `file`: Binary file (PDF, PNG, JPG, JPEG)
  - `document_role`: `QUESTION_PAPER` | `ANSWER_KEY` | `MIXED` | `UNKNOWN` (default: `UNKNOWN`)
  - `group_id`: UUID (optional)
- **Response `201 Created`**:
```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "original_filename": "exam_paper.pdf",
  "mime_type": "application/pdf",
  "file_size": 245120,
  "file_hash": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
  "document_role": "QUESTION_PAPER",
  "status": "QUEUED",
  "progress": 0,
  "created_at": "2026-09-19T12:05:00.000Z"
}
```
- **Errors**:
  - `400 Bad Request`: Empty file (0 bytes) or corrupted magic bytes header.
  - `413 Payload Too Large`: Exceeds `MAX_UPLOAD_SIZE_MB`.
  - `415 Unsupported Media Type`: File extension not allowed.
  - `401 Unauthorized`: Missing or invalid Bearer token.

#### 5. Poll Document Status
- **Endpoint**: `GET /api/v1/documents/{document_id}/status`
- **Headers**: `Authorization: Bearer <TOKEN>`
- **Response `200 OK`**:
```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "status": "COMPLETED",
  "progress": 100,
  "error_message": null,
  "page_count": 4,
  "updated_at": "2026-09-19T12:05:05.000Z"
}
```

#### 5b. Reprocess Document
- **Endpoint**: `POST /api/v1/documents/{document_id}/reprocess` (also aliased at `POST /documents/{document_id}/reprocess`)
- **Headers**: `Authorization: Bearer <TOKEN>`
- **Description**: Re-runs document extraction and parsing without creating duplicate records. Atomically cleans up existing questions, answers, and warnings, resets status to `QUEUED`, and re-triggers background worker.
- **Response `200 OK`**:
```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "status": "QUEUED",
  "progress": 0,
  "error_message": null,
  "page_count": 4,
  "updated_at": "2026-09-19T12:10:00.000Z"
}
```
- **Errors**: `401 Unauthorized`, `403 Forbidden` (if not document owner), `404 Not Found`.

#### 6. Retrieve Document Record
- **Endpoint**: `GET /api/v1/documents/{document_id}`
- **Headers**: `Authorization: Bearer <TOKEN>`
- **Response `200 OK`**: Full document record including `questions` and `warnings` lists.
- **Errors**: `403 Forbidden` (if owned by another user), `404 Not Found`.

#### 7. Document Group Management
- **Create Group**: `POST /api/v1/document-groups`
  ```json
  { "name": "Mid-Term Physics Exam", "description": "QP + Answer key set" }
  ```
- **Get Group**: `GET /api/v1/document-groups/{group_id}`
- **Batch Add Documents**: `POST /api/v1/document-groups/{group_id}/documents`
  ```json
  { "document_ids": ["7c9e6679-7425-40de-944b-e07fc1f90ae7"] }
  ```

#### 8. Paginated Questions Retrieval
- **Endpoint**: `GET /api/v1/documents/{document_id}/questions`
- **Headers**: `Authorization: Bearer <TOKEN>`
- **Query Parameters**:
  - `skip`: Offset count (integer, default `0`, min `0`)
  - `limit`: Page limit (integer, default `50`, min `1`, max `100`)
- **Response `200 OK`**:
```json
{
  "total": 25,
  "skip": 0,
  "limit": 50,
  "items": [
    {
      "id": "2d9b6c11-1234-4567-890a-bcdef1234567",
      "document_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "question_number": "1",
      "question_text": "What is the speed of light in vacuum?",
      "question_type": "MCQ",
      "options": {
        "A": "300,000 km/s",
        "B": "150,000 km/s",
        "C": "1,000 km/s",
        "D": "300 km/s"
      },
      "answer": "A",
      "source_pages": [1],
      "confidence": 0.96,
      "needs_review": false,
      "extraction_metadata": { "source": "pymupdf_direct", "line_count": 5 },
      "created_at": "2026-09-19T12:05:02.000Z",
      "answers": [],
      "warnings": []
    }
  ]
}
```
- **Errors**: `403 Forbidden` (non-owner access), `404 Not Found`.

#### 9. Single Question Retrieval
- **Endpoint**: `GET /api/v1/questions/{question_id}`
- **Headers**: `Authorization: Bearer <TOKEN>`
- **Response `200 OK`**: Question object with options, attached answers, and extraction warnings.
- **Errors**: `403 Forbidden` (document belongs to another user), `404 Not Found`.

#### 10. Document Answer Key Entries
- **Endpoint**: `GET /api/v1/documents/{document_id}/answers`
- **Headers**: `Authorization: Bearer <TOKEN>`
- **Query Parameters**:
  - `skip`: Offset count (default `0`)
  - `limit`: Page limit (default `100`, max `500`)
- **Response `200 OK`**:
```json
[
  {
    "id": "4e1a8d22-5678-4321-987b-fedcba765432",
    "question_id": "2d9b6c11-1234-4567-890a-bcdef1234567",
    "source_document_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "question_number": "1",
    "answer_text": "A",
    "confidence": 0.98,
    "source_page": 1,
    "matched": true
  }
]
```
- **Errors**: `403 Forbidden`, `404 Not Found`.

#### 11. Document Extraction Warnings
- **Endpoint**: `GET /api/v1/documents/{document_id}/warnings`
- **Headers**: `Authorization: Bearer <TOKEN>`
- **Query Parameters**:
  - `skip`: Offset count (default `0`)
  - `limit`: Page limit (default `100`, max `500`)
- **Response `200 OK`**:
```json
[
  {
    "id": "8a7b6c55-4444-5555-6666-777788889999",
    "document_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "question_id": null,
    "warning_type": "LOW_OCR_CONFIDENCE",
    "message": "Page 2 OCR average confidence 58.2% is below threshold 60.0%.",
    "page_number": 2,
    "confidence": 0.58,
    "created_at": "2026-09-19T12:05:01.000Z"
  }
]
```
- **Errors**: `403 Forbidden`, `404 Not Found`.

