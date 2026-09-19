# Pragati Bharti – Document Processing & Question Extraction Service

An enterprise-grade, asynchronous backend service engineered for ingesting multi-page examination documents (question papers, answer keys, mixed formats), performing hybrid text extraction and computer vision OCR preprocessing, stitching multi-page questions, evaluating extraction confidence heuristics, matching answer keys across document groups, and serving structured data via a multi-tenant RESTful API.

---

## Table of Contents
1. [System Architecture](#system-architecture)
2. [Technology Stack](#technology-stack)
3. [Key Features](#key-features)
4. [Quick Start with Docker Compose](#quick-start-with-docker-compose)
5. [Local Native Setup](#local-native-setup)
6. [Configuration & Environment Variables](#configuration--environment-variables)
7. [Database Architecture & Migrations](#database-architecture--migrations)
8. [Asynchronous Processing: Celery & Redis](#asynchronous-processing-celery--redis)
9. [Hybrid Text Extraction & Computer Vision Pipeline](#hybrid-text-extraction--computer-vision-pipeline)
10. [Confidence Scoring & Quality Heuristics](#confidence-scoring--quality-heuristics)
11. [REST API Endpoints Specification](#rest-api-endpoints-specification)
12. [Authentication & Multi-Tenant Security](#authentication--multi-tenant-security)
13. [Testing & Quality Assurance](#testing--quality-assurance)
14. [Sample Files & Postman Collection](#sample-files--postman-collection)
15. [Known Limitations & Production Roadmap](#known-limitations--production-roadmap)

---

## 1. System Architecture

The Pragati Bharti system is architected as an asynchronous, event-driven pipeline where file uploads are quickly validated, hashed, and persisted, while heavy OCR and natural language extraction tasks are delegated to background Celery workers.

```mermaid
graph TD
    subgraph ClientLayer["Client & Evaluator"]
        Client["Client / Postman / Swagger UI"]
    end

    subgraph APILayer["FastAPI Gateway (Port 8000)"]
        Router["API Gateway (/api/v1)"]
        AuthGuard["JWT Security & Multi-Tenant Guard"]
        UploadGuard["File Sniffing Guard (Magic Bytes, Size, Hash)"]
    end

    subgraph StorageLayer["Storage Abstraction Layer"]
        StorageContract["BaseStorageService"]
        LocalStorage["LocalStorageService (storage/uploads)"]
        S3Storage["S3StorageService (boto3 ready)"]
    end

    subgraph WorkerFleet["Asynchronous Execution Fleet"]
        RedisBroker[("Redis 7 (Broker & Backend)")]
        CeleryWorker["Celery Worker Engine"]
        Pipeline["DocumentProcessingPipeline"]
    end

    subgraph DatabaseLayer["Relational Engine"]
        Postgres[("PostgreSQL 16 Engine")]
    end

    Client -->|HTTP / Multipart / Bearer JWT| Router
    Router --> AuthGuard
    Router --> UploadGuard
    UploadGuard -->|Chunked Stream| StorageContract
    StorageContract --> LocalStorage
    StorageContract -.-> S3Storage
    UploadGuard -->|Dispatch Task| RedisBroker
    RedisBroker -->|Consume Task| CeleryWorker
    CeleryWorker --> Pipeline
    Pipeline -->|Read Binary Asset| StorageContract
    Pipeline -->|Save Questions, Answers, Warnings| Postgres
    Router -->|Query Status & Results| Postgres
```

---

## 2. Technology Stack

| Layer | Technology | Version | Purpose & Rationale |
|---|---|---|---|
| **API Framework** | FastAPI | 0.115+ | High-performance async ASGI web framework with automatic OpenAPI/Swagger generation and Pydantic validation. |
| **Language Runtime** | Python | 3.11+ / 3.12+ | Robust typing, performance optimizations, and broad computer vision library support. |
| **Relational Database** | PostgreSQL | 16 | ACID-compliant relational persistence, JSONB support for flexible question options and metadata. |
| **ORM & Migrations** | SQLAlchemy & Alembic | 2.0+ & 1.14+ | Modern 2.0-style ORM with type annotations, connection pooling, and versioned database schema migrations. |
| **Message Broker & Cache** | Redis | 7-alpine | In-memory key-value store powering Celery task brokering and distributed state caching. |
| **Task Queue** | Celery | 5.4+ | Asynchronous distributed worker execution for CPU-intensive document parsing and OCR tasks. |
| **PDF Processing** | PyMuPDF (Fitz) | 1.25+ | High-speed PDF text sniffing, font structure extraction, and high-fidelity 200 DPI page rendering. |
| **Computer Vision** | OpenCV (cv2) | 4.10+ | Grayscale conversion, CLAHE contrast enhancement, Hough deskew correction, and Otsu binarization. |
| **OCR Engine** | Tesseract OCR (pytesseract) | 5.x | Industry-standard optical character recognition with per-word confidence metrics. |
| **Containerization** | Docker & Compose | 3.8 spec | Multi-container orchestration guaranteeing identical development and evaluation environments. |
| **Testing Framework** | Pytest & pytest-asyncio | 8.x | Comprehensive unit and integration test suite with SQLite in-memory testing and Celery eager execution. |

---

## 3. Key Features

- **Hybrid Extraction**: Inspects PDF vector streams first for clean digital text; automatically activates OpenCV + Tesseract OCR fallback for scanned or degraded pages.
- **Computer Vision Deskewing**: Automatically estimates document skew angles using `cv2.minAreaRect` and rotates pages when $|angle| > 0.5^\circ$.
- **Multi-Page Question Stitching**: Seamlessly stitches questions that span page boundaries into coherent items with recorded `source_pages: [N, N+1]`.
- **Heuristic Confidence Scoring**: Combines 5 distinct deterministic signals (OCR word quality, boundary strength, option sequentiality, sequence progression, and answer key match) into a 0.0–1.0 confidence score.
- **Answer Key Reconciliation**: Supports separate `QUESTION_PAPER` and `ANSWER_KEY` uploads within unified `DocumentGroup` entities, automatically matching answers by normalized question number (`1`, `Q1`, `Question 1:`).
- **Automated Warning Generation**: Detects incomplete questions, low OCR confidence pages, missing question numbers, option ambiguities, and unmatched keys.
- **Idempotent Reprocessing**: `POST /documents/{id}/reprocess` purges stale child records and re-runs the pipeline safely with zero duplicated questions.
- **Security & Integrity**: Magic byte sniffing (PDF, JPEG, PNG), streaming chunk size enforcement, zero-byte file rejection, SHA-256 deduplication, path traversal defenses, and multi-tenant JWT scoping.

---

## 4. Quick Start with Docker Compose

The simplest and recommended method to launch the entire stack (API, PostgreSQL, Redis, Celery Worker) is using Docker Compose.

### 4.1 Launch Services
```bash
# Clone and enter directory
cd Pnbc_round2

# Start all containers in detached mode
docker compose up --build -d
```

### 4.2 Verify Container Health
```bash
docker compose ps
```
All four services (`pragati_postgres`, `pragati_redis`, `pragati_api`, `pragati_celery_worker`) will report `healthy` or `running`.

### 4.3 Check System Health Endpoint
```bash
curl -s http://localhost:8000/health
```
**Expected Response**:
```json
{
  "status": "healthy",
  "app_name": "Pragati Bharti Document Processing Service",
  "environment": "production",
  "database": "connected",
  "redis": "connected"
}
```

### 4.4 Interactive API Documentation
Open your browser and navigate to:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI Schema**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

### 4.5 Teardown
```bash
docker compose down -v
```

---

## 5. Local Native Setup

For local development and running unit tests without Docker:

### 5.1 Prerequisites
- Python 3.11+
- Tesseract OCR (optional for direct PDF tests, required for native OCR)
- PostgreSQL and Redis (or run with SQLite / `CELERY_TASK_ALWAYS_EAGER=true`)

### 5.2 Environment Preparation
```bash
# Windows PowerShell
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 5.3 Configure Environment
```bash
# Windows PowerShell
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

### 5.4 Run Migrations
```bash
alembic upgrade head
```

### 5.5 Start Application
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 6. Configuration & Environment Variables

The application is configured using Pydantic `BaseSettings` reading from `.env`:

| Variable | Default Value | Description |
|---|---|---|
| `APP_NAME` | `Pragati Bharti Document Processing Service` | Application title reported in metadata |
| `ENVIRONMENT` | `development` | Runtime environment (`development` / `production` / `test`) |
| `DEBUG` | `true` | Enables verbose debug logging |
| `API_V1_STR` | `/api/v1` | URL routing prefix for V1 API routes |
| `SECRET_KEY` | *(Set in .env)* | 32+ character HMAC key for signing JWT tokens |
| `ALGORITHM` | `HS256` | JWT signature algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | JWT token lifetime (24 hours) |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/pragati_bharti` | SQLAlchemy connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis caching & state backend |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker URL |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Celery result backend |
| `CELERY_TASK_ALWAYS_EAGER`| `false` | When `true`, executes Celery tasks synchronously in-process (ideal for tests) |
| `STORAGE_BACKEND` | `local` | Storage provider (`local` or `s3`) |
| `UPLOAD_DIR` | `storage/uploads` | Path to store uploaded binary assets |
| `MAX_UPLOAD_SIZE_MB` | `25` | Maximum upload size threshold (MB) |
| `TESSERACT_CMD` | `null` | Optional override for `tesseract` binary path |

---

## 7. Database Architecture & Migrations

The database is managed with SQLAlchemy 2.x and versioned with Alembic migrations (`alembic/versions/001_initial_schema.py`).

### 7.1 Entity-Relationship Diagram

```mermaid
erDiagram
    users ||--o{ document_groups : "owns"
    users ||--o{ documents : "owns"
    document_groups ||--o{ documents : "groups"
    documents ||--o{ questions : "extracts"
    documents ||--o{ answers : "contains"
    documents ||--o{ extraction_warnings : "generates"
    questions ||--o{ answers : "matches"
    questions ||--o{ extraction_warnings : "flags"

    users {
        uuid id PK
        string email UK
        string password_hash
        datetime created_at
    }

    document_groups {
        uuid id PK
        uuid owner_id FK
        string name
        text description
        datetime created_at
    }

    documents {
        uuid id PK
        uuid owner_id FK
        uuid group_id FK
        string original_filename
        string stored_filename UK
        string mime_type
        bigint file_size
        string file_hash
        string document_role
        string status
        integer progress
        string error_message
        integer page_count
        datetime created_at
        datetime updated_at
    }

    questions {
        uuid id PK
        uuid document_id FK
        string question_number
        text question_text
        string question_type
        jsonb options
        string answer
        jsonb source_pages
        float confidence
        boolean needs_review
        jsonb extraction_metadata
        datetime created_at
    }

    answers {
        uuid id PK
        uuid question_id FK
        uuid source_document_id FK
        string question_number
        text answer_text
        float confidence
        integer source_page
        boolean matched
    }

    extraction_warnings {
        uuid id PK
        uuid document_id FK
        uuid question_id FK
        string warning_type
        text message
        integer page_number
        float confidence
        datetime created_at
    }
```

### 7.2 Running Migrations
```bash
# Apply all pending migrations to the latest revision
alembic upgrade head

# Roll back by one migration
alembic downgrade -1
```

---

## 8. Asynchronous Processing: Celery & Redis

Document ingestion decoupled from extraction processing:
1. **Immediate Ingestion**: The API validates binary magic headers, generates a UUID-based file path, saves the payload via `LocalStorageService`, inserts a `QUEUED` document record into PostgreSQL, and enqueues task `process_document_task` to Redis. The API immediately returns HTTP `201 Created` with the document ID.
2. **Worker Execution**: Celery workers pull tasks from Redis:
   - Sets document status to `PROCESSING` with `progress = 10%`.
   - Initializes `DocumentProcessingPipeline`.
   - Sniffs PDF text; renders pages at 200 DPI if scanned; applies OpenCV deskew and Tesseract OCR.
   - Parses questions, extracts options, matches answer keys.
   - Calculates confidence scores and records warnings.
   - Atomically updates document status to `COMPLETED` (`progress = 100%`) or `PARTIAL`.
3. **Resilient Failure Handling**: Any pipeline exception is trapped by an outer handler, recording an explicit `error_message` and marking the document `FAILED`, preventing permanently hung tasks.

---

## 9. Hybrid Text Extraction & Computer Vision Pipeline

```mermaid
flowchart TD
    Asset["Uploaded File (.pdf / .png / .jpg)"] --> TypeRouter{"File Type?"}

    subgraph PDFBranch["Direct PDF Ingestion"]
        TypeRouter -->|PDF| Sniff["PyMuPDF Fitz Text Sniffing"]
        Sniff --> DensityCheck{"Alphanumeric Density >= 0.20?"}
        DensityCheck -->|Direct Text| NativePages["PageExtractionResult (direct)"]
        DensityCheck -->|Scanned / Sparse| RenderPixmap["Render 200 DPI Pixmap"]
    end

    subgraph OpenCVBranch["Computer Vision Preprocessing"]
        TypeRouter -->|Image: PNG/JPEG| LoadImg["cv2.imdecode"]
        RenderPixmap --> LoadImg
        LoadImg --> Gray["Grayscale Conversion"]
        Gray --> CLAHE["CLAHE Contrast Enhancement"]
        CLAHE --> Denoise["Bilateral & Gaussian Filtering"]
        Denoise --> Deskew["Hough Deskew (|angle| > 0.5 deg)"]
        Deskew --> Otsu["Otsu Adaptive Binarization"]
    end

    subgraph OCRBranch["Tesseract OCR Engine"]
        Otsu --> Tesseract["Pytesseract Layout & Word Recognition"]
        Tesseract --> WordConf["Extract Word Confidences & Mean"]
        WordConf --> OCRPages["PageExtractionResult (ocr)"]
    end

    subgraph ParserBranch["State-Machine & Regex Parser"]
        NativePages --> QParser["Question Parser"]
        OCRPages --> QParser
        QParser --> Stitcher["Multi-Page Question Stitching"]
        QParser --> KeyParser["Answer Key Extractor"]
    end

    subgraph QualityBranch["Quality & Persistence"]
        Stitcher --> Heuristics["Confidence & Warnings Engine"]
        KeyParser --> Heuristics
        Heuristics --> Persistence[("PostgreSQL 16 Persistence")]
    end
```

---

## 10. Confidence Scoring & Quality Heuristics

The service computes a deterministic, multi-factor confidence score ($0.0 \le c \le 1.0$) for every extracted question:

$$\text{Confidence} = 0.25 \cdot Q_{\text{ocr}} + 0.25 \cdot Q_{\text{boundary}} + 0.20 \cdot Q_{\text{options}} + 0.15 \cdot Q_{\text{sequence}} + 0.15 \cdot Q_{\text{answer\_match}}$$

| Factor | Weight | Evaluation Criteria |
|---|---|---|
| **$Q_{\text{ocr}}$** (Direct / OCR Quality) | 25% | `1.0` for vector-extracted text; mean word confidence ratio for OCR. |
| **$Q_{\text{boundary}}$** (Question Boundary) | 25% | Clean delimiter recognition (`1.`, `Q1.`, `Question 1:`). |
| **$Q_{\text{options}}$** (Option Consistency) | 20% | Sequentiality of options (e.g. A, B, C, D) and minimum text length. |
| **$Q_{\text{sequence}}$** (Numerical Sequence) | 15% | Monotonically increasing question numbers. |
| **$Q_{\text{answer\_match}}$** (Answer Match) | 15% | Confirmed match with answer key entry. |

**Thresholds**:
- $c \ge 0.80$: **High Confidence** (`needs_review = false`).
- $0.60 \le c < 0.80$: **Medium Confidence** (`needs_review = true` if options or boundaries are ambiguous).
- $c < 0.60$: **Low Confidence** (`needs_review = true`, triggers `LOW_CONFIDENCE` warning).

---

## 11. REST API Endpoints Specification

All routes (except `/health` and root documentation) reside under `/api/v1`.

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | No | System health check (PostgreSQL, Redis, App) |
| `GET` | `/docs` | No | Interactive Swagger UI |
| `GET` | `/openapi.json` | No | OpenAPI 3.1 JSON schema |
| `POST` | `/api/v1/auth/register` | No | Create new user account |
| `POST` | `/api/v1/auth/login` | No | Authenticate user and receive Bearer JWT |
| `GET` | `/api/v1/auth/me` | Yes | Retrieve current user profile |
| `POST` | `/api/v1/documents` | Yes | Upload examination document (PDF/PNG/JPEG) |
| `GET` | `/api/v1/documents/{id}` | Yes | Fetch document details, questions, and warnings |
| `GET` | `/api/v1/documents/{id}/status` | Yes | Poll document processing state and progress |
| `POST` | `/api/v1/documents/{id}/reprocess` | Yes | Re-run extraction pipeline idempotently |
| `GET` | `/api/v1/documents/{id}/questions` | Yes | Paginated list of questions with options & answers |
| `GET` | `/api/v1/questions/{id}` | Yes | Detailed view of a single question |
| `GET` | `/api/v1/documents/{id}/answers` | Yes | List extracted answer key entries |
| `GET` | `/api/v1/documents/{id}/warnings` | Yes | List extraction warnings and review flags |
| `PATCH`| `/api/v1/documents/{id}/group` | Yes | Assign or dissociate document from a group |
| `POST` | `/api/v1/document-groups` | Yes | Create a new document group |
| `GET` | `/api/v1/document-groups/{id}` | Yes | Retrieve document group and member documents |
| `POST` | `/api/v1/document-groups/{id}/documents` | Yes | Batch associate documents to a group |

---

## 12. Authentication & Multi-Tenant Security

- **JWT Tokens**: Signed using `HS256` HMAC with configurable expiration (`ACCESS_TOKEN_EXPIRE_MINUTES`).
- **Multi-Tenant Scoping**: All database queries for documents, groups, questions, and answers filter strictly by `owner_id = current_user.id`.
- **Cross-Tenant Guard**: User B attempting to access User A's document receives `403 Forbidden` or `404 Not Found`.
- **Upload Hardening**:
  - Empty files (0 bytes) $\rightarrow$ `400 Bad Request`.
  - Extension not in whitelist (`.pdf`, `.jpg`, `.jpeg`, `.png`) $\rightarrow$ `415 Unsupported Media Type`.
  - Magic byte mismatch (e.g. an `.exe` renamed to `.pdf`) $\rightarrow$ `400 Bad Request`.
  - Upload exceeding `MAX_UPLOAD_SIZE_MB` $\rightarrow$ `413 Payload Too Large`.
  - Path traversal injection $\rightarrow$ Blocked via `Path.resolve().relative_to()`.

---

## 13. Testing & Quality Assurance

The codebase includes **55 comprehensive automated tests** across 8 test suites:

| Test Suite | File | Focus Areas |
|---|---|---|
| **Authentication** | `tests/test_auth.py` | Registration, login, duplicate email handling, JWT validation, unauthenticated route rejection. |
| **Document Ingestion** | `tests/test_documents.py` | Magic byte sniffing, extension whitelisting, size limits, 0-byte rejections, status polling, multi-tenant isolation. |
| **Extraction Pipeline** | `tests/test_extraction.py` | Regex question parsing, numbering formats (1., Q1., Question 1:), option extraction, multi-page stitching, confidence calculator, deskewing. |
| **Document Groups** | `tests/test_document_groups.py` | Group creation, batch assignment, multi-tenant ownership guards. |
| **Group Matching & Reprocess**| `tests/test_group_matching_and_reprocess.py` | Cross-document answer matching, option inconsistency warnings, conflicting key warnings, reprocessing idempotency (zero duplicates). |
| **Question Endpoints** | `tests/test_question_endpoints.py` | Pagination (`skip`, `limit`), filtering, individual question retrieval, answers list, warnings list. |
| **System Health** | `tests/test_health.py` | Root redirects, Swagger availability, DB and Redis ping assertions. |

### Running the Test Suite
```bash
# Activate virtual environment
.venv\Scripts\activate   # Windows
# source .venv/bin/activate # Linux/macOS

# Run all 55 tests
pytest
```
*Expected Result: 55 passed in ~28 seconds (100% success rate).*

---

## 14. Sample Files & Postman Collection

- **Sample Documents** (`sample_documents/`):
  - `sample_question_paper.pdf`: Multi-page exam PDF containing MCQs and True/False questions.
  - `sample_page.png`: High-resolution scanned question paper image.
  - `sample_key.jpg`: Scanned answer key image.
- **Sample JSON Outputs** (`sample_outputs/`):
  - `auth_response.json`: Register and login token responses.
  - `upload_response.json`: Ingestion acknowledgment with file hash.
  - `document_status_response.json`: Asynchronous processing progress.
  - `document_detail_response.json`: Complete document payload with embedded questions.
  - `questions_paginated_response.json`: Paginated questions with options and confidence metrics.
  - `answers_response.json`: Parsed answer key items.
  - `warnings_response.json`: Flagged review warnings with severity metrics.
- **Postman Collection** (`postman/pragati_bharti.postman_collection.json`):
  - Ready-to-import Postman v2.1 collection containing all 18 endpoints with pre-configured environment variables and test scripts that automatically capture and propagate `access_token` and `document_id`.

---

## 15. Known Limitations & Production Roadmap

1. **Complex Mathematical Equations & LaTeX**: The current regex and OCR parser extracts UTF-8 Unicode mathematical symbols, but complex nested LaTeX fractions and matrices are treated as raw text. Future iterations will integrate a MathPix or Nougat transformer sub-model.
2. **Handwritten Exam Submissions**: The OCR pipeline is optimized for typed and printed examination papers. Free-form cursive handwriting produces lower confidence scores and will trigger `LOW_OCR_CONFIDENCE` review warnings as designed.
3. **Multi-Column Magazine Layouts**: Dual-column question papers without distinct vertical separators may experience line interleaving. A layout-detection CNN (e.g. YOLO / LayoutLM) can be incorporated in the next release.
4. **Cloud Object Storage**: Production deployments should toggle `STORAGE_BACKEND=s3` and configure AWS S3 / MinIO buckets for horizontal scaling across worker nodes.
