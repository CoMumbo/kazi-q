import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.api import create_app
from app.db import init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_engine = create_engine(f"sqlite:///{tmp_path}/api.db", future=True)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False, future=True)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession)
    init_db()

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_post_job_creates(client):
    r = client.post("/jobs", json={"type": "send_email", "payload": {"to": "a@b.com"}})
    assert r.status_code == 201
    body = r.get_json()
    assert body["type"] == "send_email"
    assert body["state"] == "pending"
    assert body["payload"] == {"to": "a@b.com"}


def test_post_job_rejects_empty_type(client):
    r = client.post("/jobs", json={"type": ""})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_post_job_rejects_non_json(client):
    r = client.post("/jobs", data="not json", content_type="text/plain")
    assert r.status_code == 400


def test_get_job(client):
    r = client.post("/jobs", json={"type": "x", "payload": {}})
    job_id = r.get_json()["id"]

    r2 = client.get(f"/jobs/{job_id}")
    assert r2.status_code == 200
    assert r2.get_json()["id"] == job_id


def test_get_missing_job_404(client):
    r = client.get("/jobs/nope")
    assert r.status_code == 404


def test_stats(client):
    client.post("/jobs", json={"type": "x", "payload": {}})
    client.post("/jobs", json={"type": "y", "payload": {}})

    r = client.get("/jobs/stats")
    assert r.status_code == 200
    body = r.get_json()
    assert body["pending"] == 2
    assert body["total"] == 2


def test_dead_empty(client):
    r = client.get("/jobs/dead")
    assert r.status_code == 200
    assert r.get_json() == []