import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, func, delete as sa_delete

from app.db import get_session
from app.models import Job, JobState

log = logging.getLogger("kazi-q.jobs")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(job_type: str, payload: dict, max_retries: int = 3) -> Job:
    """Create a new pending job. Returns the persisted Job."""
    if not job_type or not isinstance(job_type, str):
        raise ValueError("job_type is required and must be a string")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    with get_session() as session:
        job = Job(
            type=job_type,
            payload=json.dumps(payload),
            state=JobState.PENDING,
            max_retries=max_retries,
            next_run_at=_utcnow(),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        log.info("enqueued job %s type=%s", job.id, job.type)
        return job


def get(job_id: str) -> Job | None:
    """Fetch a job by id. Returns None if missing."""
    with get_session() as session:
        return session.get(Job, job_id)


def stats() -> dict:
    """Count jobs grouped by state."""
    with get_session() as session:
        rows = session.execute(
            select(Job.state, func.count()).group_by(Job.state)
        ).all()

    counts = {state.value: 0 for state in JobState}
    for state, count in rows:
        counts[state.value] = count
    counts["total"] = sum(counts.values())
    return counts


def list_dead(limit: int = 100) -> list[Job]:
    """List dead-letter jobs, most recent first."""
    with get_session() as session:
        rows = session.execute(
            select(Job)
            .where(Job.state == JobState.DEAD)
            .order_by(Job.updated_at.desc())
            .limit(limit)
        ).scalars().all()
        return list(rows)


def list_jobs(state: str | None = None, job_type: str | None = None, limit: int = 100) -> list[Job]:
    """List jobs with optional filters, most recent first.

    `state` should be a JobState value (e.g. "pending"), or None for all.
    `job_type` filters by the type field, or None for all.
    """
    with get_session() as session:
        stmt = select(Job)
        if state is not None:
            stmt = stmt.where(Job.state == JobState(state))
        if job_type is not None:
            stmt = stmt.where(Job.type == job_type)
        stmt = stmt.order_by(Job.created_at.desc()).limit(limit)
        rows = session.execute(stmt).scalars().all()
        return list(rows)


def retry(job_id: str) -> Job | None:
    """Reset a job to pending so a worker will pick it up again.

    Only meaningful for dead or failed jobs. Returns the updated job, or
    None if the job doesn't exist.
    """
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return None
        job.state = JobState.PENDING
        job.attempts = 0
        job.next_run_at = _utcnow()
        job.last_error = None
        job.updated_at = _utcnow()
        session.commit()
        session.refresh(job)
        log.info("retried job %s", job.id)
        return job


def delete(job_id: str) -> bool:
    """Delete a job. Returns True if it existed and was deleted."""
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return False
        session.delete(job)
        session.commit()
        log.info("deleted job %s", job_id)
        return True


def to_dict(job: Job) -> dict:
    """Serialize a Job for JSON responses."""
    return {
        "id": job.id,
        "type": job.type,
        "payload": json.loads(job.payload),
        "state": job.state.value,
        "attempts": job.attempts,
        "max_retries": job.max_retries,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "next_run_at": job.next_run_at.isoformat(),
        "last_error": job.last_error,
    }