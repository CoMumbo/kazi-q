import json
import pytest

from app.db import init_db, engine
from app import jobs
from app.models import JobState


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Point the engine at a fresh temp DB for every test."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import app.db as db_module

    test_engine = create_engine(f"sqlite:///{tmp_path}/test.db", future=True)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False, future=True)

    # Monkeypatch the module-level session factory
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession)
    init_db()


def test_enqueue_creates_pending_job():
    job = jobs.enqueue("send_email", {"to": "alice@example.com"})
    assert job.id
    assert job.type == "send_email"
    assert job.state == JobState.PENDING
    assert job.attempts == 0
    assert json.loads(job.payload) == {"to": "alice@example.com"}


def test_enqueue_rejects_bad_type():
    with pytest.raises(ValueError):
        jobs.enqueue("", {})


def test_enqueue_rejects_bad_payload():
    with pytest.raises(ValueError):
        jobs.enqueue("send_email", "not a dict")


def test_get_returns_none_for_missing():
    assert jobs.get("doesnotexist") is None


def test_stats_counts_by_state():
    jobs.enqueue("a", {})
    jobs.enqueue("b", {})
    jobs.enqueue("c", {})
    s = jobs.stats()
    assert s["pending"] == 3
    assert s["total"] == 3
    assert s["dead"] == 0


def test_to_dict_serializes():
    job = jobs.enqueue("send_email", {"to": "x@y.com"})
    d = jobs.to_dict(job)
    assert d["id"] == job.id
    assert d["type"] == "send_email"
    assert d["state"] == "pending"
    assert d["payload"] == {"to": "x@y.com"}
    assert isinstance(d["created_at"], str)