from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import time
from typing import Iterator
import uuid


class ExecutionAgentAlreadyRunningError(RuntimeError):
    pass


@contextmanager
def execution_agent_lock(db_path: str, stale_after_seconds: float = 900.0) -> Iterator[None]:
    lock_path = Path(f"{db_path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    owner_token = uuid.uuid4().hex
    fd = _acquire_lock_file(lock_path, owner_token, stale_after_seconds)
    try:
        yield
    finally:
        os.close(fd)
        _release_owned_lock(lock_path, owner_token)


def _acquire_lock_file(lock_path: Path, owner_token: str, stale_after_seconds: float) -> int:
    for attempt in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, owner_token.encode("ascii"))
            return fd
        except FileExistsError as exc:
            if attempt == 0 and _is_stale(lock_path, stale_after_seconds):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            raise ExecutionAgentAlreadyRunningError(
                f"Execution agent lock already exists: {lock_path}"
            ) from exc
    raise ExecutionAgentAlreadyRunningError(f"Unable to acquire execution agent lock: {lock_path}")


def _is_stale(lock_path: Path, stale_after_seconds: float) -> bool:
    try:
        age_seconds = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age_seconds > stale_after_seconds


def _release_owned_lock(lock_path: Path, owner_token: str) -> None:
    try:
        current_token = lock_path.read_text(encoding="ascii")
    except (FileNotFoundError, OSError):
        return
    if current_token == owner_token:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
