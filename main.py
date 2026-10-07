"""FastAPI service for bulk certificate generation."""

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, field_validator

from .certificates import render_certificate


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RecipientInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr

    @field_validator("name")
    def name_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class GenerationRequest(BaseModel):
    course_name: str = Field(..., min_length=1, max_length=160)
    issued_by: str = Field(..., min_length=1, max_length=120)
    recipients: List[RecipientInput] = Field(..., min_length=1, max_length=1000)

    @field_validator("course_name", "issued_by")
    def required_text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned


def create_app(
    db_path: Optional[str] = None,
    certificate_renderer: Callable[[str, str, str], bytes] = render_certificate,
) -> FastAPI:
    """Create an app instance; injectable DB and renderer keep tests isolated."""
    database = db_path or os.environ.get("CERTIFICATE_DB_PATH", "certificates.sqlite3")
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    lock = threading.RLock()

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                course_name TEXT NOT NULL,
                issued_by TEXT NOT NULL,
                status TEXT NOT NULL,
                total INTEGER NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                succeeded INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS certificates (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                recipient_name TEXT NOT NULL,
                recipient_email TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                pdf BLOB
            );
            CREATE INDEX IF NOT EXISTS idx_certificates_job ON certificates(job_id);
            """
        )

    app = FastAPI(title="Bulk Certificate Generator", version="1.0.0")
    app.state.database = database
    app.state.lock = lock
    app.state.renderer = certificate_renderer
    app.state.connect = connect

    def run_job(job_id: str) -> None:
        with connect() as connection:
            job = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            recipients = connection.execute(
                "SELECT * FROM certificates WHERE job_id = ? ORDER BY rowid", (job_id,)
            ).fetchall()
        for recipient in recipients:
            cert_id = recipient["id"]
            try:
                pdf_bytes = certificate_renderer(
                    recipient["recipient_name"], job["course_name"], job["issued_by"]
                )
                with lock, connect() as connection:
                    connection.execute(
                        "UPDATE certificates SET status='succeeded', pdf=? WHERE id=?",
                        (pdf_bytes, cert_id),
                    )
                    connection.execute(
                        "UPDATE jobs SET completed=completed+1, succeeded=succeeded+1 WHERE id=?",
                        (job_id,),
                    )
            except Exception as exc:  # Isolate a failure to the individual recipient.
                message = str(exc).strip()[:500] or exc.__class__.__name__
                with lock, connect() as connection:
                    connection.execute(
                        "UPDATE certificates SET status='failed', error=? WHERE id=?",
                        (message, cert_id),
                    )
                    connection.execute(
                        "UPDATE jobs SET completed=completed+1, failed=failed+1 WHERE id=?",
                        (job_id,),
                    )
        with lock, connect() as connection:
            connection.execute(
                "UPDATE jobs SET status='completed', finished_at=? WHERE id=?",
                (utc_now(), job_id),
            )

    @app.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
    def create_job(payload: GenerationRequest, background_tasks: BackgroundTasks):
        job_id = str(uuid.uuid4())
        with lock, connect() as connection:
            connection.execute(
                "INSERT INTO jobs(id, course_name, issued_by, status, total, created_at) "
                "VALUES (?, ?, ?, 'queued', ?, ?)",
                (job_id, payload.course_name, payload.issued_by, len(payload.recipients), utc_now()),
            )
            for recipient in payload.recipients:
                connection.execute(
                    "INSERT INTO certificates(id, job_id, recipient_name, recipient_email, status) "
                    "VALUES (?, ?, ?, ?, 'queued')",
                    (str(uuid.uuid4()), job_id, recipient.name, recipient.email),
                )
            connection.execute("UPDATE jobs SET status='processing' WHERE id=?", (job_id,))
        background_tasks.add_task(run_job, job_id)
        return {"job_id": job_id, "status": "processing", "status_url": f"/jobs/{job_id}"}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        with connect() as connection:
            job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            rows = connection.execute(
                "SELECT id, recipient_name, recipient_email, status, error FROM certificates "
                "WHERE job_id=? ORDER BY rowid", (job_id,)
            ).fetchall()
        return {
            "job_id": job["id"], "status": job["status"], "course_name": job["course_name"],
            "issued_by": job["issued_by"], "total": job["total"],
            "completed": job["completed"], "succeeded": job["succeeded"],
            "failed": job["failed"], "created_at": job["created_at"],
            "finished_at": job["finished_at"],
            "certificates": [
                {"certificate_id": row["id"], "recipient_name": row["recipient_name"],
                 "recipient_email": row["recipient_email"], "status": row["status"],
                 "error": row["error"],
                 "download_url": f"/jobs/{job_id}/certificates/{row['id']}"
                 if row["status"] == "succeeded" else None}
                for row in rows
            ],
        }

    @app.get("/jobs/{job_id}/certificates/{certificate_id}")
    def get_certificate(job_id: str, certificate_id: str):
        with connect() as connection:
            row = connection.execute(
                "SELECT recipient_name, status, pdf FROM certificates WHERE id=? AND job_id=?",
                (certificate_id, job_id),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Certificate not found")
        if row["status"] != "succeeded" or row["pdf"] is None:
            raise HTTPException(status_code=409, detail="Certificate is not available")
        safe_name = "".join(ch for ch in row["recipient_name"] if ch.isalnum() or ch in " -_").strip()
        filename = (safe_name or "certificate").replace(" ", "_") + ".pdf"
        return Response(
            content=row["pdf"], media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app


app = create_app()
