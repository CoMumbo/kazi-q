"""
End-to-end demo for kazi-q.

Runs the API and worker in-process, enqueues a few jobs, waits for them to
finish, and prints the final state. Designed to be run with:

    python -m scripts.demo

Requires the API and worker packages. Does NOT require any servers to be
running beforehand.
"""

import logging
import sys
import threading
import time

from app import jobs
from app.api import create_app
from app.config import Config
from app.db import init_db
from app.handlers import HANDLERS
from app.worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kazi-q.demo")


# Silence the noisy Flask/Werkzeug request logger so the demo output is clean.
logging.getLogger("werkzeug").setLevel(logging.WARNING)


def start_api_in_background():
    app = create_app()
    t = threading.Thread(
        target=lambda: app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=False,
            use_reloader=False,
            threaded=True,
        ),
        name="demo-api",
        daemon=True,
    )
    t.start()
    # give Flask a moment to bind the port
    time.sleep(1.0)
    return t


def start_worker_in_background():
    worker = Worker(poll_interval=0.5)
    t = threading.Thread(target=worker.run_forever, name="demo-worker", daemon=True)
    t.start()
    return worker, t


def wait_for_all_jobs_to_settle(timeout: float = 20.0):
    """Poll stats until no jobs are pending or running (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = jobs.stats()
        if s["pending"] == 0 and s["running"] == 0:
            return True
        time.sleep(0.5)
    return False


def main():
    print()
    print("=" * 60)
    print("kazi-q demo")
    print("=" * 60)

    init_db()

    # Fresh DB for a clean demo
    print("\n[1/5] starting API and worker in-process...")
    start_api_in_background()
    worker, worker_thread = start_worker_in_background()
    time.sleep(0.5)

    print(f"      registered handlers: {sorted(HANDLERS.keys())}")

    # Enqueue jobs
    print("\n[2/5] enqueueing jobs...")
    echo_job = jobs.enqueue("echo", {"message": "hello from kazi-q"})
    print(f"      echo   -> {echo_job.id}")

    sleep_job = jobs.enqueue("sleep", {"seconds": 2})
    print(f"      sleep  -> {sleep_job.id}  (2 seconds)")

    fail_job = jobs.enqueue("fail", {"message": "demonstration failure"}, max_retries=3)
    print(f"      fail   -> {fail_job.id}  (will retry 3x then go dead)")

    # Let them run
    print("\n[3/5] waiting for jobs to settle...")
    settled = wait_for_all_jobs_to_settle(timeout=30.0)
    if not settled:
        print("      WARNING: jobs did not settle within 30s")
    else:
        print("      all jobs settled")

    # Show final state
    print("\n[4/5] final stats:")
    s = jobs.stats()
    for key in ("pending", "running", "succeeded", "dead", "total"):
        print(f"      {key:10s} {s[key]}")

    print("\n      dead-letter jobs:")
    dead = jobs.list_dead()
    if not dead:
        print("      (none)")
    for j in dead:
        print(f"      {j.id}  type={j.type}  attempts={j.attempts}")
        print(f"        last_error: {j.last_error}")

    # Shut down
    print("\n[5/5] shutting down...")
    worker.stop()
    worker_thread.join(timeout=3.0)
    print("      done")

    print()
    print("=" * 60)
    print("demo complete")
    print("=" * 60)
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(1)