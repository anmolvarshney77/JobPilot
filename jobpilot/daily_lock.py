from __future__ import annotations

import os
import sys
from pathlib import Path

LOCK_FILE = Path(".daily.lock")


class DailyAlreadyRunningError(Exception):
    pass


class DailyLock:
    """Context manager that prevents overlapping daily runs."""

    def __init__(self, lock_path: Path = LOCK_FILE) -> None:
        self._path = lock_path
        self._fh = None

    def __enter__(self) -> "DailyLock":
        if sys.platform == "win32":
            self._acquire_pid_lock()
        else:
            self._acquire_fcntl_lock()
        return self

    def __exit__(self, *args: object) -> None:
        self._release()

    # ------------------------------------------------------------------ Unix
    def _acquire_fcntl_lock(self) -> None:
        import fcntl
        self._fh = open(self._path, "w")
        try:
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            raise DailyAlreadyRunningError("Another jobpilot daily run is already in progress.")
        self._fh.write(str(os.getpid()))
        self._fh.flush()

    # ------------------------------------------------------------------ Windows
    def _acquire_pid_lock(self) -> None:
        if self._path.exists():
            try:
                pid = int(self._path.read_text().strip())
                if _pid_running(pid):
                    raise DailyAlreadyRunningError(
                        f"Another jobpilot daily run is already in progress (PID {pid})."
                    )
            except (ValueError, PermissionError):
                pass
        self._path.write_text(str(os.getpid()))

    def _release(self) -> None:
        if self._fh is not None:
            try:
                if sys.platform != "win32":
                    import fcntl
                    fcntl.flock(self._fh, fcntl.LOCK_UN)
                self._fh.close()
            except Exception:
                pass
            self._fh = None
        try:
            self._path.unlink(missing_ok=True)
        except Exception:
            pass


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
