import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, func

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