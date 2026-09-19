# Pragati Bharti – Document Processing & Question Extraction Service
## Setup and Operational Guide

### 1. Quick Start via Docker Compose (Evaluator Recommended)

The repository provides a multi-container Docker Compose definition bundling:
- **`api`**: FastAPI service exposed on port `8000`.
- **`postgres`**: PostgreSQL 16 server on port `5432`.
- **`redis`**: Redis 7 cache & Celery broker on port `6379`.
- **`celery_worker`**: Background worker consumer executing document processing tasks.

```bash
# 1. Clone or navigate to the repository
cd Pnbc_round2

# 2. Launch the full stack
docker compose up --build -d

# 3. Verify health
curl -f http://localhost:8000/health

# 4. View interactive API documentation
# Open http://localhost:8000/docs in your browser
```

To stop the services:
```bash
docker compose down
```

---

### 2. Local Native Setup (Development & Unit Testing)

#### Prerequisites
- Python 3.11+
- Virtual environment (`venv`)

#### Step-by-Step Instructions

1. **Create and Activate Virtual Environment**:
   ```bash
   # Windows PowerShell
   python -m venv .venv
   .venv\Scripts\activate

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Copy `.env.example` to `.env`:
   ```bash
   # Windows PowerShell
   Copy-Item .env.example .env

   # Linux / macOS
   cp .env.example .env
   ```

4. **Run Database Migrations (Alembic)**:
   ```bash
   alembic upgrade head
   ```

5. **Run the API Server**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

6. **Start Celery Worker (In a separate terminal)**:
   ```bash
   # Linux / macOS
   celery -A app.workers.celery_app.celery_app worker --loglevel=info

   # Windows
   celery -A app.workers.celery_app.celery_app worker --loglevel=info -P solo
   ```

---

### 3. Running Automated Tests

Run the complete test suite with `pytest`:
```bash
pytest tests/ -v
```

The test suite runs against an isolated SQLite test database with eager Celery execution, verifying:
- Health checks
- Authentication & JWT issuance
- Supported uploads (PDF, PNG, JPG)
- Rejection of unsupported extensions (.txt, .exe)
- Rejection of corrupt or spoofed MIME headers
- Rejection of empty files (0 bytes)
- Multi-tenant ownership and cross-user data isolation
- Document group associations
