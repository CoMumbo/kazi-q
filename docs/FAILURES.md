# Failure modes

This document walks through how kazi-q behaves when things go wrong. It
covers the failure cases that were tested, the ones that were reasoned
about without testing, and the ones that are known gaps.

## Worker crashes mid-job

**Scenario.** A worker claims a job, sets `state=running`, and then the
process is killed before the handler finishes.

**What happens.** The job stays in `running` forever. No other worker will
claim it, because the claim query filters on `state=pending`. The job is
stranded.

**What this project does about it.** Nothing, currently.

**What a real system does.** Two common approaches:

1. **Leases.** When a worker claims a job, it also sets a `lease_expires_at`
   timestamp. A reaper process (or the next worker) treats any `running`
   job with an expired lease as abandoned and returns it to `pending`.
2. **Heartbeats.** The worker pings the database periodically while
   running. Jobs without recent heartbeats are considered abandoned.

Both solve the same problem. The lease approach is simpler to implement and
is the natural next feature for kazi-q.

**Why it wasn't implemented here.** Scope. The mechanism is understood and
documented, which is more honest than shipping a half-working reaper.

## Worker crashes between state transitions

**Scenario.** The worker writes `state=running` and commits, then crashes
before running the handler. Same as above.

**Scenario.** The handler succeeds, then the worker crashes before writing
`state=succeeded`. The job is stuck in `running`, but the side effect
already happened.

**What this project does about it.** Nothing.

**What a real system does.** This is the **at-least-once delivery**
problem. The correct fix is to make handlers **idempotent**: running them
twice must produce the same result as running them once. The system can
then freely retry without worrying about duplicates.

Idempotency is a property of the handler, not the queue. The queue's job is
to guarantee at-least-once; the handler's job is to tolerate it. Examples:

- `send_email` should record a `sent_at` timestamp per recipient, and skip
  if already sent.
- `charge_card` should use an idempotency key that the payment provider
  deduplicates on.
- `increment_counter` needs a value that isn't a counter — or the caller
  must accept the possibility of a double increment.

kazi-q doesn't enforce idempotency, but the design leaves room for it:
handlers receive a payload dict, and the job id is available if needed.

## Poison jobs

**Scenario.** A job whose handler always raises. Retries never succeed.

**What happens.** The worker retries it `max_retries` times with
exponential backoff, then moves it to `state=dead`.

**What this project does about it.** Dead-letter queue. Dead jobs stay in
the `jobs` table with `state=dead` and the last error message captured.
`GET /jobs/dead` lists them for human inspection.

**What's missing.** There's no automatic alert on dead jobs, no manual
retry endpoint, and no dead-letter retention policy. In a real system,
dead jobs would trigger an alert, and operators would have a way to
inspect, fix, and re-enqueue them.

## Backlog growth

**Scenario.** Producers enqueue jobs faster than workers can process them.

**What happens.** The `pending` count grows unbounded. Nothing caps it.

**What this project does about it.** Nothing.

**What a real system does.**

- **Admission control.** Reject new jobs when the queue is over a threshold.
- **Backpressure.** Slow down producers, or block until the queue drains.
- **Horizontal scaling.** Add workers. Since workers claim jobs
  independently, this works out of the box (subject to the SQLite
  limitation).

The cleanest fix here is a small queue-depth check in `POST /jobs` that
returns `429 Too Many Requests` above a configurable threshold.

## SQLite write contention

**Scenario.** High enqueue or completion rate. Multiple writers hit SQLite
at the same time.

**What happens.** SQLite allows one writer at a time. Writes serialize,
latency increases, and under enough pressure, `database is locked` errors
appear.

**What this project does about it.** Nothing.

**What a real system does.** Postgres or another concurrent-write database.
The code is written to make this a configuration change, not a rewrite.

## Timezone and date handling

**Scenario.** Code compares two `datetime` objects, one from the database
and one from `datetime.now(timezone.utc)`.

**What happens.** SQLite returns naive datetimes. Comparing naive to aware
raises `TypeError`.

**What this project does about it.** Tests strip `tzinfo` when comparing
against database values. Application code uses aware UTC everywhere and
never compares across the boundary.

**Why it matters.** This is a real bug that will bite anyone who stores
datetimes in SQLite. It's called out here so future contributors know.

## Duplicate job ids

**Scenario.** Two jobs are created with the same id.

**What happens.** The `id` column is the primary key. The second insert
raises an `IntegrityError`.

**What this project does about it.** Job ids are 12-character hex strings
derived from UUIDv4. Collision probability is negligible (about 1 in 2^48
per pair). The error path isn't handled because it doesn't happen in
practice.

## Configuration errors

**Scenario.** `KAZI_WORKER_MAX_RETRIES` is set to `-1`. Or
`KAZI_WORKER_POLL_INTERVAL` to `0`.

**What happens.** With `max_retries=-1`: a job becomes `dead` immediately
on first failure (since `attempts >= max_retries` is true). With
`poll_interval=0`: the worker busy-loops, pegging a CPU.

**What this project does about it.** Nothing. Config values are trusted.

**What a real system does.** Validate config at startup. Reject negative
values, require positive poll intervals, refuse to start with a clear error
message.

This is a small fix and would be a good next contribution.

## What is not a failure mode

Things that are sometimes assumed to be problems but aren't:

- **Jobs running twice.** At-least-once delivery is the model. See the
  idempotency discussion above.
- **Non-FIFO ordering across different job types.** kazi-q processes jobs
  in `next_run_at` order, regardless of type. A `sleep` job will block an
  `echo` job behind it if the worker is single-threaded. This is expected;
  it's what "queue" means.
- **Dead jobs sticking around.** The dead-letter queue is a feature, not a
  bug. Jobs stay until someone acts on them.