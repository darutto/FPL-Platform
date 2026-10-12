"""Make sure a lineup watcher is running; start it detached if not. Idempotent.

usage: python scripts/ensure_watcher.py NAME START_UTC END_UTC [FIRST_POLL_UTC]
Log: trial-output/lineup-watch/NAME.ndjson; lock: NAME.pid; finished marker: NAME.ndjson.done (written by
``lineup_watch.py``). Does nothing when the marker exists or the recorded process is alive; otherwise it
appends a ``{"watcher_restart": true}`` line to the log (so a gap is visible) and starts the watcher detached.

Recovery recipe after a reboot (from packages/sportmonks-client, SPORTMONKS_API_TOKEN set):
  python scripts/ensure_watcher.py gw6-last 2026-10-12T00:00:00Z 2026-10-12T23:59:59Z
  python scripts/ensure_watcher.py gw7 2026-10-16T00:00:00Z 2026-10-20T23:59:59Z 2026-10-16T12:00:00Z
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
WATCH_DIR = Path("trial-output") / "lineup-watch"


def pid_alive(pid: int) -> bool:
    """Is a process with this id running? (No command-line check: a reused pid is possible, and rare.)"""
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _spawn(args: list[str], out_path: Path, root: Path) -> int:
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    with out_path.open("a") as out:
        proc = subprocess.Popen([sys.executable, *args], cwd=root, creationflags=flags,
                                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, close_fds=True,
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return proc.pid


def ensure(name: str, start: str, end: str, first: str | None = None, *, root: Path = ROOT,
           alive: Callable[[int], bool] = pid_alive,
           spawn: Callable[[list[str], Path, Path], int] = _spawn,
           settle_seconds: float = 3.0) -> str:
    """Returns ``finished``, ``running``, ``started`` or ``died_at_start`` (it exited without finishing)."""
    folder = root / WATCH_DIR
    folder.mkdir(parents=True, exist_ok=True)
    log, pid_file = folder / f"{name}.ndjson", folder / f"{name}.pid"
    if Path(f"{log}.done").exists():
        return "finished"
    if pid_file.exists():
        try:
            if alive(int(pid_file.read_text())):
                return "running"
        except ValueError:
            pass
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": now, "watcher_restart": True}) + "\n")
    watcher = str(Path(__file__).resolve().with_name("lineup_watch.py"))
    pid = spawn([watcher, start, end, str(log), *([first] if first else [])], folder / f"{name}.out", root)
    pid_file.write_text(str(pid))
    time.sleep(settle_seconds)   # a watcher that cannot start must not be reported as started
    if not alive(pid) and not Path(f"{log}.done").exists():
        return "died_at_start"
    return "started"


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(__doc__)
        return 2
    print(argv[0], ensure(argv[0], argv[1], argv[2], argv[3] if len(argv) == 4 else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
