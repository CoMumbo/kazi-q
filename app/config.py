import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    HOST = os.getenv("KAZI_HOST", "127.0.0.1")
    PORT = int(os.getenv("KAZI_PORT", "8000"))
    DB_URL = os.getenv("KAZI_DB_URL", "sqlite:///./data/kazi.db")
    WORKER_POLL_INTERVAL = float(os.getenv("KAZI_WORKER_POLL_INTERVAL", "1.0"))
    WORKER_MAX_RETRIES = int(os.getenv("KAZI_WORKER_MAX_RETRIES", "3"))
    WORKER_BACKOFF_BASE = float(os.getenv("KAZI_WORKER_BACKOFF_BASE", "2.0"))