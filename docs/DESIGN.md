# Design decisions

This document records the significant design choices behind kazi-q and the
trade-offs behind each. It's meant to be read alongside the code, not as a
tutorial.

## Storage: SQLite

The queue state lives in a single SQLite file (`data/kazi.db`). All job
state transitions are SQLite transactions.

Why SQLite:

- Zero operational overhead. No external service to run or deploy.
- ACID guarantees on writes, which the worker relies on for atomic claims.
- Fine for the scale kazi-q is built for (tens of thousands of jobs).

When SQLite is not enough:

- **Write contention.** SQLite allows one writer at a time. Under heavy
  enqueue or worker activity, writes serialize. Postgres or MySQL would
  allow concurrent writers.
- **Distributed workers.** Workers on different machines can't share a
  SQLite file. A network-accessible database is required.

The code is written against SQLAlchemy, so swapping SQLite for Postgres is
mostly a `DATABASE_URL` change plus a real migration story (Alembic or
similar). The `Job` model uses no SQLite-specific features.

## Atomic job claiming

`claim_next_job()` selects the oldest pending job whose `next_run_at` is in
the past, then updates its state to `running` and commits, all inside one
session.

This is safe because:

- SQLite (with SQLAlchemy's default isolation) takes a write lock on the
  UPDATE, so two workers can't both claim the same row.

This is not safe beyond one process or one database:

- Two workers on different hosts against different databases would each
  claim their own copy. In practice you'd want `SELECT ... FOR UPDATE SKIP
  LOCKED` on Postgres, or a conditional `UPDATE ... WHERE state='pending'`
  with the affected-row count checked.

For the scope of this project, the current approach is sufficient. It is
called out here so the limitation is explicit rather than hidden.

## Retries as pending jobs, not a separate state

A failed job with retries remaining goes back to `state=pending` with a
future `next_run_at`. Only exhausted jobs become `state=dead`.

An earlier version used a `failed` state for this case. It caused a bug: the
worker's claim query filtered on `pending`, so failed jobs were never
claimed again. They sat in `failed` forever.

The fix and the lesson:

- A job scheduled for retry is conceptually *pending*, just not due yet.
- The `JobState` enum still defines `FAILED`, but nothing sets it. It could
  be removed, but leaving it documents that it was considered and rejected.

There is a regression test for this: `test_failed_job_with_retries_left_goes_back_to_pending`.

## Exponential backoff

Backoff is `base ** attempts` seconds. With the default `base=2.0`:

- After attempt 1: 2 seconds
- After attempt 2: 4 seconds
- After attempt 3: 8 seconds

Why exponential rather than fixed:

- A fixed delay hammers a failing downstream service at a constant rate.
- Exponential backoff gives the downstream time to recover while still
  making progress on transient failures.

Why not jitter:

- Jitter (randomizing the delay) prevents thundering herds when many jobs
  fail at the same moment. It's a good addition and is left as future work.
- With a single worker and small job counts, jitter adds complexity without
  benefit here.

## Worker polling

The worker polls the database every `KAZI_WORKER_POLL_INTERVAL` seconds
(default 1.0).

Alternatives considered:

- **Blocking dequeue.** A `NOTIFY`/`LISTEN` channel would eliminate polling
  latency. Postgres supports this; SQLite does not.
- **Long polling.** A pending job wakes the worker. More complex than the
  problem justifies here.

Polling is the simplest thing that works. The latency cost is bounded by
the poll interval, which is configurable.

## Process model

The API and worker are separate processes. They share nothing except the
database.

Why not threads in one process:

- The worker can be scaled independently of the API. Under load you'd run
  ten workers and one API.
- A crashed worker shouldn't take down the API.
- Deployment stories differ: API scales with request volume, workers scale
  with job backlog.

Why not separate machines in this project:

- SQLite prevents it. That's the storage limitation above.
- The architecture is set up so that a database change would enable this
  without code restructuring.

## Timezone handling

All timestamps are generated as timezone-aware UTC (`datetime.now(timezone.utc)`).

SQLite drops timezone info on `DateTime` columns. When a value is read
back it's naive, though it represents UTC. Comparisons in application code
must normalize, which is why some tests strip tzinfo before comparing.

Postgres preserves timezone info. The code is written for the more correct
behavior; only the tests need the SQLite workaround.

## What this project deliberately does not do

Things that were considered and left out:

- **Priority queues.** Jobs run in `next_run_at` order. Adding priority is a
  column and an `ORDER BY`.
- **Scheduled jobs.** `next_run_at` in the future handles this; an API
  endpoint for setting it would make it a feature.
- **Job cancellation.** Would need a `CANCELLED` state and worker check.
- **Progress reporting.** Handlers return a dict; there's no streaming.
- **Authentication.** The API is open. Real deployments need keys or OAuth.
- **Metrics.** Stats are exposed over HTTP; Prometheus counters are future
  work.