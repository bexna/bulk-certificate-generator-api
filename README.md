# Bulk Certificate Generator API

A small FastAPI service that accepts one bulk request, validates recipients, generates a PDF certificate for each recipient, tracks individual results in SQLite, and exposes status and download endpoints.

## Requirements

- Python 3.9 or newer
- pip

## Setup and run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; interactive API documentation is at `/docs`. By default the database is `certificates.sqlite3` in the current directory. Set `CERTIFICATE_DB_PATH` to use another location.

## Submit a generation request

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "course_name": "Introduction to Python",
    "issued_by": "Example Academy",
    "recipients": [
      {"name": "Ada Lovelace", "email": "ada@example.com"},
      {"name": "Grace Hopper", "email": "grace@example.com"}
    ]
  }'
```

The API returns `202 Accepted` and a `job_id` with a `status_url`. Each request accepts 1–1000 recipients. Invalid request data returns `422` with field-level validation details.

## Check status and retrieve certificates

```bash
curl http://127.0.0.1:8000/jobs/JOB_ID
curl -L http://127.0.0.1:8000/jobs/JOB_ID/certificates/CERTIFICATE_ID \
  --output certificate.pdf
```

The job response includes total, completed, succeeded, and failed counts, plus each recipient's result and a download URL when generation succeeded. A failed recipient includes an error message; the remaining recipients are still processed. Downloading a missing resource returns `404`; attempting to download a certificate that is not ready returns `409`.

## Run tests

```bash
pytest
```

The tests cover request creation, validation, PDF generation and retrieval, progress/results, individual generation failures, and missing resources.

## Design decisions

- **FastAPI and Pydantic** provide a compact REST API and request validation.
- **SQLite** keeps the project self-contained and stores job state and generated PDF bytes together. A relational database is used without requiring a separate server.
- **Background processing** uses FastAPI's in-process background task mechanism. The job is acknowledged before generation, and clients can poll the job endpoint. This is appropriate for a small assignment/demo. A production deployment handling large or durable workloads should use a persistent queue/worker and shared database; in-process work does not survive a process restart.
- **Failure isolation** is per recipient: renderer exceptions are recorded for that recipient and the worker continues through the batch.
- **One fixed certificate design** is rendered as a landscape PDF with ReportLab. Certificate records use UUIDs, and filenames are sanitized before download.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/jobs` | Validate and queue a bulk request |
| `GET` | `/jobs/{job_id}` | Read progress and per-recipient results |
| `GET` | `/jobs/{job_id}/certificates/{certificate_id}` | Download a generated PDF |

