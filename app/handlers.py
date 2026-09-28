import logging
import time

log = logging.getLogger("kazi-q.handlers")


# --- Registry ---------------------------------------------------------------

HANDLERS: dict = {}


def register(job_type: str):
    """Decorator to register a handler for a job type."""
    def decorator(fn):
        HANDLERS[job_type] = fn
        return fn
    return decorator


def get_handler(job_type: str):
    """Return the handler for a type, or None if unregistered."""
    return HANDLERS.get(job_type)


# --- Built-in handlers ------------------------------------------------------

@register("echo")
def handle_echo(payload: dict) -> dict:
    """Log the payload and return it. Useful for smoke testing."""
    log.info("echo payload=%r", payload)
    return {"echoed": payload}


@register("sleep")
def handle_sleep(payload: dict) -> dict:
    """Sleep for payload['seconds'], then return. Useful for testing slow jobs."""
    seconds = float(payload.get("seconds", 1))
    log.info("sleeping for %.2fs", seconds)
    time.sleep(seconds)
    return {"slept": seconds}


@register("fail")
def handle_fail(payload: dict) -> dict:
    """Always raises. Useful for testing retry and dead-letter behavior."""
    raise RuntimeError(payload.get("message", "intentional failure"))