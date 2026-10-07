import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path / "test.sqlite3"))
    with TestClient(app) as test_client:
        yield test_client


def request_body(recipients=None):
    return {
        "course_name": "Introduction to Python",
        "issued_by": "Example Academy",
        "recipients": recipients or [
            {"name": "Ada Lovelace", "email": "ada@example.com"},
            {"name": "Grace Hopper", "email": "grace@example.com"},
        ],
    }


def test_create_job_and_track_progress(client):
    created = client.post("/jobs", json=request_body())
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    result = client.get(f"/jobs/{job_id}")
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "completed"
    assert body["total"] == body["completed"] == 2
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert all(item["status"] == "succeeded" for item in body["certificates"])


def test_validation_rejects_bad_email_and_empty_recipients(client):
    bad_email = request_body([{"name": "Person", "email": "not-an-email"}])
    assert client.post("/jobs", json=bad_email).status_code == 422

    no_recipients = request_body([])
    no_recipients["recipients"] = []
    assert client.post("/jobs", json=no_recipients).status_code == 422


def test_certificate_download_returns_pdf(client):
    job_id = client.post("/jobs", json=request_body()).json()["job_id"]
    result = client.get(f"/jobs/{job_id}").json()
    certificate_id = result["certificates"][0]["certificate_id"]

    download = client.get(f"/jobs/{job_id}/certificates/{certificate_id}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF")


def test_one_render_failure_does_not_stop_other_certificates(tmp_path):
    def sometimes_fails(name, course, issuer):
        if name == "Grace Hopper":
            raise RuntimeError("simulated renderer error")
        return b"%PDF-1.4 test"

    app = create_app(str(tmp_path / "failure.sqlite3"), sometimes_fails)
    with TestClient(app) as client:
        job_id = client.post("/jobs", json=request_body()).json()["job_id"]
        body = client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "completed"
    assert body["completed"] == 2
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    failed = next(item for item in body["certificates"] if item["recipient_name"] == "Grace Hopper")
    assert failed["error"] == "simulated renderer error"
    assert failed["download_url"] is None


def test_missing_job_and_certificate_return_404(client):
    assert client.get("/jobs/missing").status_code == 404
    job_id = client.post("/jobs", json=request_body()).json()["job_id"]
    assert client.get(f"/jobs/{job_id}/certificates/missing").status_code == 404

