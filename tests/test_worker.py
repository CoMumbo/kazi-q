import json
import pytest
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.db import init_db
from app import worker, handlers
from app.models import Job, JobState
from app.jobs import enqueue


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test."""
    test_engine = create_engine(f"sqlite:///{tmp_path}/test.db", future=True)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False, future=True)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession)
    init_db()


# --- claim_next_job ---------------------------------------------------------

def test_claim_returns_none_when_empty():
    assert worker.claim_next_job() is None


def test_claim_picks_pending_job_and_marks_running():
    j = enqueue("echo", {"x": 1})
    claimed = worker.claim_next_job()

    assert claimed is not None
    assert claimed.id == j.id
    assert claimed.state == JobState.RUNNING
    assert claimed.attempts == 1


def test_claim_skips_future_jobs():
    j = enqueue("echo", {})
    # Push next_run_at 1 hour into the future
    with db_module.get_session() as s:
        row = s.get(Job, j.id)
        row.next_run_at = datetime.now(timezone.utc) + timedelta(hours=1)
        s.commit()

    assert worker.claim_next_job() is None


def test_claim_is_fifo_by_next_run_at():
    a = enqueue("echo", {"n": 1})
    b = enqueue("echo", {"n": 2})

    first = worker.claim_next_job()
    second = worker.claim_next_job()

    assert first.id == a.id
    assert second.id == b.id


# --- mark_succeeded / mark_failed_or_dead -----------------------------------

def test_mark_succeeded_sets_state():
    j = enqueue("echo", {})
    worker.claim_next_job()
    worker.mark_succeeded(j.id)

    with db_module.get_session() as s:
        row = s.get(Job, j.id)
        assert row.state == JobState.SUCCEEDED
        assert row.last_error is None


def test_failed_job_with_retries_left_goes_back_to_pending():
    """Regression test: retries must not strand jobs in FAILED state."""
    j = enqueue("fail", {}, max_retries=3)
    worker.claim_next_job()  # attempts=1
    worker.mark_failed_or_dead(j.id, "boom")

    with db_module.get_session() as s:
        row = s.get(Job, j.id)
        assert row.state == JobState.PENDING
        assert row.attempts == 1
        assert row.last_error == "boom"
        # next_run_at should be in the future (backoff).
        # SQLite returns naive datetimes, so strip tzinfo from "now" for comparison.
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        assert row.next_run_at > now_naive


def test_exhausted_job_moves_to_dead():
    j = enqueue("fail", {}, max_retries=2)
    worker.claim_next_job()  # attempts=1
    worker.mark_failed_or_dead(j.id, "boom")

    # Manually advance backoff so we can claim it again immediately
    with db_module.get_session() as s:
        row = s.get(Job, j.id)
        row.next_run_at = datetime.now(timezone.utc)
        s.commit()

    worker.claim_next_job()  # attempts=2
    worker.mark_failed_or_dead(j.id, "boom again")

    with db_module.get_session() as s:
        row = s.get(Job, j.id)
        assert row.state == JobState.DEAD
        assert row.attempts == 2
        assert "boom again" in row.last_error


# --- run_job ----------------------------------------------------------------

def test_run_job_success():
    j = enqueue("echo", {"x": 42})
    claimed = worker.claim_next_job()
    worker.run_job(claimed)

    with db_module.get_session() as s:
        row = s.get(Job, j.id)
        assert row.state == JobState.SUCCEEDED


def test_run_job_unknown_handler_marks_retry_or_dead():
    j = enqueue("nonexistent_type", {})
    claimed = worker.claim_next_job()
    worker.run_job(claimed)

    with db_module.get_session() as s:
        row = s.get(Job, j.id)
        assert "no handler registered" in row.last_error
        assert row.state == JobState.PENDING


def test_run_job_failing_handler_retries():
    j = enqueue("fail", {"message": "boom"}, max_retries=3)
    claimed = worker.claim_next_job()
    worker.run_job(claimed)

    with db_module.get_session() as s:
        row = s.get(Job, j.id)
        assert row.state == JobState.PENDING
        assert "RuntimeError: boom" in row.last_error