"""Arbre de processus (Linux, via /proc) : sous-reaper pour adopter les démons, descendants, arrêt propre."""
from __future__ import annotations

import ctypes
import os
import signal
import sys
import time
from pathlib import Path

PR_SET_CHILD_SUBREAPER = 36


def become_subreaper(enable: bool = True) -> bool:
    """Les processus orphelins de nos descendants (serveurs lancés avec `--daemon`, double fork…) sont
    rattachés à zero au lieu d'init : on peut alors les voir et les arrêter. Sans effet hors Linux."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(PR_SET_CHILD_SUBREAPER, 1 if enable else 0, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


def _ppid_map() -> dict[int, list[int]]:
    kids: dict[int, list[int]] = {}
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return kids
    for d in entries:
        if d.name.isdigit():
            try:
                ppid = int((d / "stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            kids.setdefault(ppid, []).append(int(d.name))
    return kids


def children(pid: int) -> set[int]:
    """Enfants directs de `pid`."""
    return set(_ppid_map().get(pid, []))


def descendants(pid: int) -> set[int]:
    """`pid` et tous ses descendants."""
    kids = _ppid_map()
    out, todo = {pid}, [pid]
    while todo:
        for k in kids.get(todo.pop(), []):
            if k not in out:
                out.add(k)
                todo.append(k)
    return out


def is_alive(pid: int) -> bool:
    """Vivant et pas zombie."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state != "Z"


def kill_tree(pids: set[int], grace: float = 5.0) -> None:
    """SIGTERM puis, après `grace` s, SIGKILL ; récolte les zombies adoptés."""
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 2.0)):
        live = [p for p in pids if is_alive(p)]
        for p in live:
            try:
                os.kill(p, sig)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.time() + wait
        while time.time() < deadline and any(is_alive(p) for p in live):
            time.sleep(0.1)
    for p in pids:
        try:
            os.waitpid(p, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass
