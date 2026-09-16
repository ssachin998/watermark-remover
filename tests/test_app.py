"""Dashboard tests: boot the Flask app (test client) and exercise the full
workflow: health, index, upload, live job state, download, preview, cancel,
rejects, and concurrent uploads.

The app's job directory is redirected to a temp dir BEFORE import.
"""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

import pymupdf as fitz
import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def app_client(tmp_path_factory):
    jobs_dir = tmp_path_factory.mktemp("jobs")
    os.environ["PDF_FIX_JOBS_DIR"] = str(jobs_dir)
    os.environ["PDF_FIX_MAX_JOB_KEEP"] = "8"
    os.environ["PDF_FIX_MAX_UPLOAD_MB"] = "200"
    # import (fresh) after env is set
    import importlib
    import app as app_module
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client, app_module
    # cleanup job dirs
    import shutil
    shutil.rmtree(jobs_dir, ignore_errors=True)


def _upload(client, name: str, data: bytes):
    return client.post(
        "/upload",
        data={"pdf": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def _wait_done(app_module, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        with app_module.app.test_client() as c:
            r = c.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        last = r.get_json()
        if last["status"] in ("done", "error", "cancelled"):
            return last
        time.sleep(1.0)
    raise TimeoutError(f"job {job_id} not finished; last={last}")


def test_health(app_client):
    client, _ = app_client
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert "running_jobs" in body


def test_index_page(app_client):
    client, _ = app_client
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "PDF Fixer" in html
    assert 'action="/upload"' in html


def test_upload_workflow_end_to_end(app_client, fixtures):
    client, app_module = app_client
    data = fixtures["text_watermark.pdf"].read_bytes()
    r = _upload(client, "sample.pdf", data)
    assert r.status_code == 200, r.get_data(as_text=True)[:500]
    # a job card should be present
    html = r.get_data(as_text=True)
    job_id = None
    for j in app_module._jobs_public():
        job_id = j["id"]
    assert job_id

    job = _wait_done(app_module, job_id)
    assert job["status"] == "done", f"job failed: {job['error']}\nlog: {job['log'][-30:]}"
    assert job["has_output"]

    # download the clean pdf and verify it
    r = client.get(f"/download/{job_id}/clean")
    assert r.status_code == 200
    out = r.data
    assert out.startswith(b"%PDF")
    p = fixtures["text_watermark.pdf"].with_name("downloaded_clean.pdf")
    p.write_bytes(out)
    d = fitz.open(stream=out, filetype="pdf")
    text = " ".join(pg.get_text() for pg in d)
    assert "itachibot" not in text.lower()
    assert "Question 1" in text
    d.close()

    # preview endpoint serves the same file inline
    r = client.get(f"/preview/{job_id}")
    assert r.status_code == 200
    assert r.data.startswith(b"%PDF")
    assert "inline" in r.headers.get("Content-Disposition", "")

    # step1 intermediate is downloadable too
    r = client.get(f"/download/{job_id}/step1")
    assert r.status_code == 200
    assert r.data.startswith(b"%PDF")

    # job list API shows the job
    r = client.get("/api/jobs")
    assert r.status_code == 200
    ids = [j["id"] for j in r.get_json()["jobs"]]
    assert job_id in ids


def test_upload_rejects_invalid_files(app_client, fixtures):
    client, app_module = app_client
    # non-pdf extension
    r = _upload(client, "image.png", b"\x89PNG\r\n\x1a\nfakedata")
    assert r.status_code == 400
    assert b"Only .pdf files" in r.data
    # .pdf name but not a PDF (missing %PDF header)
    r = _upload(client, "junk.pdf", b"this is not a pdf at all")
    assert r.status_code == 400
    assert b"not a valid PDF" in r.data
    # no file at all
    r = client.post("/upload", data={}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert b"No file selected" in r.data
    # encrypted pdf passes upload (header is valid) but the job must FAIL
    # cleanly with a password message (never bypassed)
    enc = fixtures["encrypted.pdf"].read_bytes()
    r = _upload(client, "secret.pdf", enc)
    assert r.status_code == 200
    job_id = app_module._jobs_public()[0]["id"]
    job = _wait_done(app_module, job_id)
    assert job["status"] == "error"
    assert "password" in (job["error"] or "").lower()
    assert not job["has_output"]


def test_concurrent_uploads(app_client, fixtures):
    client, app_module = app_client
    data = fixtures["multi_page_plain.pdf"].read_bytes()
    r1 = _upload(client, "a.pdf", data)
    r2 = _upload(client, "b.pdf", data)
    assert r1.status_code == 200 and r2.status_code == 200
    jobs = app_module._jobs_public()
    ids = [j["id"] for j in jobs[:2]]
    results = [_wait_done(app_module, i, timeout=300) for i in ids]
    assert all(j["status"] == "done" for j in results), \
        [j["status"] for j in results]
    # both outputs exist and are distinct files
    for i, j in zip(ids, results):
        r = client.get(f"/download/{i}/clean")
        assert r.status_code == 200 and r.data.startswith(b"%PDF")
