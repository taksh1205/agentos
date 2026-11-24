"""Reject multiple schedulers: durable single-worker execution is the supported mode."""

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text


@contextmanager
def worker_lock(store):
    if store.engine.dialect.name == "postgresql":
        with store.engine.connect() as connection:
            if not connection.execute(text("SELECT pg_try_advisory_lock(83421907)")).scalar():
                raise RuntimeError("Another AgentOS scheduler owns this database")
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(83421907)"))
    else:
        import fcntl

        path = Path(os.getenv("CHECKPOINT_PATH", "checkpoints.db") + ".worker.lock")
        with path.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another AgentOS scheduler owns this checkpoint store") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
