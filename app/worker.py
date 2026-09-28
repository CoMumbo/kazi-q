import json
import logging
import signal
import time
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.config import Config
from app.db import get_session, init_db
from app.models import Job, JobState
from app import handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kazi-q.worker")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_next_job() -> Job | None:
    """Claim the next pending job that's ready to run.

    Retries are represented as PENDING jobs with a future next_run_at, so a
    single filter on state + due time is all we need.
    """
    with get_session() as session:
        now = _utcnow()
        stmt = (
            select(Job)
            .where(Job.state == JobState.PENDING)
            .where(Job.next_run_at <= now)
            .order_by(Job.next_run_at)
            .limit(1)
        )
        job = session.execute(stmt).scalar_one_or_none()
        if job is None:
            return None

        job.state = JobState.RUNNING
        job.attempts += 1
        job.updated_at = now
        session.commit()
        session.refresh(job)
        return job


def mark_succeeded(job_id: str) -> None:
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.SUCCEEDED
        job.last_error = None
        job.updated_at = _utcnow()
        session.commit()


def mark_failed_or_dead(job_id: str, error: str) -> None:
    """Retry if attempts remain, otherwise move to dead-letter.

    A job with retries remaining goes back to PENDING with a future
    next_run_at (exponential backoff). Only when attempts are exhausted
    does it become DEAD.
    """
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return

        job.last_error = error[:2000]
        job.updated_at = _utcnow()

        if job.attempts >= job.max_retries:
            job.state = JobState.DEAD
            log.warning("job %s moved to dead-letter after %d attempts",
                        job.id, job.attempts)
        else:
            backoff = Config.WORKER_BACKOFF_BASE ** job.attempts
            job.state = JobState.PENDING
            job.next_run_at = _utcnow() + timedelta(seconds=backoff)
            log.info("job %s failed (attempt %d/%d), retrying in %.1fs",
                     job.id, job.attempts, job.max_retries, backoff)

        session.commit()


def run_job(job: Job) -> None:
    """Execute one job. Updates the DB based on outcome."""
    log.info("running job %s type=%s attempt=%d",
             job.id, job.type, job.attempts)

    handler = handlers.get_handler(job.type)
    if handler is None:
        mark_failed_or_dead(job.id, f"no handler registered for type {job.type!r}")
        return

    try:
        payload = json.loads(job.payload) if job.payload else {}
        result = handler(payload)
        mark_succeeded(job.id)
        log.info("job %s succeeded result=%r", job.id, result)
    except Exception as e:
        log.exception("job %s raised", job.id)
        mark_failed_or_dead(job.id, f"{type(e).__name__}: {e}")


class Worker:
    """Polling worker. Runs until stopped."""

    def __init__(self, poll_interval: float):
        self.poll_interval = poll_interval
        self._stop = False

    def stop(self, *_args) -> None:
        log.info("shutdown requested, finishing current job...")
        self._stop = True

    def run_forever(self) -> None:
        log.info("worker started, poll_interval=%.2fs", self.poll_interval)
        while not self._stop:
            job = claim_next_job()
            if job is None:
                time.sleep(self.poll_interval)
                continue
            run_job(job)

        log.info("worker stopped cleanly")


def main():
    init_db()

    worker = Worker(poll_interval=Config.WORKER_POLL_INTERVAL)
    signal.signal(signal.SIGINT, worker.stop)
    signal.signal(signal.SIGTERM, worker.stop)

    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()