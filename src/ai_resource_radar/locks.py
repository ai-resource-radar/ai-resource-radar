from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import errno
import fcntl
import json
import os
from pathlib import Path
from typing import Iterator, TextIO


VALID_OPERATIONS = frozenset({"refresh", "poster", "tips"})


class OperationLockedError(RuntimeError):
    """Raised when another process owns a radar operation lock."""

    def __init__(self, operation: str, path: Path) -> None:
        super().__init__(f"ai_radar_{operation}_locked")
        self.operation = operation
        self.path = path


def operation_lock_path(database: Path, operation: str) -> Path:
    if operation not in VALID_OPERATIONS:
        raise ValueError("invalid_ai_radar_operation")
    return database.with_name(f"{database.name}.{operation}.lock")


@dataclass
class OperationLock:
    database: Path
    operation: str
    blocking: bool = False
    _stream: TextIO | None = None

    @property
    def path(self) -> Path:
        return operation_lock_path(self.database, self.operation)

    @property
    def acquired(self) -> bool:
        return self._stream is not None

    def acquire(self) -> "OperationLock":
        if self.acquired:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        os.chmod(self.path, 0o600)
        stream = os.fdopen(descriptor, "r+", encoding="utf-8")
        flags = fcntl.LOCK_EX
        if not self.blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(stream.fileno(), flags)
        except OSError as exc:
            stream.close()
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise OperationLockedError(self.operation, self.path) from exc
            raise
        metadata = {
            "operation": self.operation,
            "pid": os.getpid(),
            "acquired_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        stream.seek(0)
        stream.truncate()
        json.dump(metadata, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
        self._stream = stream
        return self

    def release(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    def __enter__(self) -> "OperationLock":
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.release()


@contextmanager
def operation_lock(
    database: Path,
    operation: str,
    *,
    blocking: bool = False,
) -> Iterator[OperationLock]:
    lock = OperationLock(database, operation, blocking=blocking)
    with lock:
        yield lock


def operation_lock_status(database: Path, operation: str) -> dict[str, object]:
    """Return lock state without waiting or disturbing the current owner."""

    path = operation_lock_path(database, operation)
    if not path.exists():
        return {"operation": operation, "locked": False, "path": str(path)}
    metadata: dict[str, object] = {}
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            metadata = parsed
    except (OSError, ValueError):
        pass
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDWR)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        if exc.errno not in {errno.EACCES, errno.EAGAIN}:
            return {
                "operation": operation,
                "locked": False,
                "path": str(path),
                "probe_error": type(exc).__name__,
            }
        return {"operation": operation, "locked": True, "path": str(path), **metadata}
    else:
        assert descriptor is not None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
        return {"operation": operation, "locked": False, "path": str(path)}
