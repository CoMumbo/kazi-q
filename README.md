# kazi-q

A small background job queue written in Python. Producers enqueue jobs over
HTTP, workers pick them up and run them, failures are retried with
exponential backoff, and poison jobs land in a dead-letter queue.

The name is a mix of Swahili and English: *kazi* means "work", and *q*
stands for queue.

## Status

Day 1 of the build. The producer API is working:

- `POST /jobs` — enqueue a job
- `GET /jobs/{id}` — fetch a job
- `GET /jobs/stats` — counts by state
- `GET /jobs/dead` — list dead-letter jobs
- `GET /health` — liveness check

The worker process, retries, and backoff land in the next session.

## Running it

```bash
python -m venv .venv
source .venv/Scripts/activate    # Windows Git Bash
# or: source .venv/bin/activate  # macOS / Linux
pip install -r requirements.txt
python -m app.api