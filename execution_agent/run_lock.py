from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import BinaryIO, Iterator


class ExecutionAgentAlreadyRunningError(RuntimeError):
    pass


@contextmanager
def execution_agent_lock(db_path: str) -> Iterator[None]:
    lock_path = Path(f"{db_path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+b")
    try:
        try:
            _acquire_os_lock(lock_file)
        except OSError as exc:
            raise ExecutionAgentAlreadyRunningError(
                f"Execution agent lock is already held: {lock_path}"
            ) from exc
        try:
            yield
        finally:
            _release_os_lock(lock_file)
    finally:
        lock_file.close()


def _acquire_os_lock(lock_file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_os_lock(lock_file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
