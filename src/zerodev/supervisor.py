"""Process Supervisor : lance un ou plusieurs processus, préfixe les logs, capture la fin."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from . import procs, sandbox


@dataclass
class RunResult:
    code: int
    tail: str            # dernières lignes de sortie (pour le diagnostic)
    uptime: float
    interrupted: bool    # Ctrl-C de l'utilisateur
    failed: str | None   # nom du processus qui a terminé en premier


# Erreurs sans ambiguïté d'un serveur qui reste vivant mais inutilisable (ex. gunicorn relance ses workers en boucle) :
# on les traite comme un échec pour déclencher la récupération au lieu d'attendre une sortie qui ne vient pas.
FATAL_WHILE_RUNNING = re.compile(r"Address family not supported by protocol|Can't connect to \('")


class Supervisor:
    def __init__(self, root: Path, env: dict):
        self._known_children = procs.children(os.getpid())      # services déjà lancés : à ne pas toucher
        self.root, self.env = root, env
        self.procs: dict[str, subprocess.Popen] = {}
        self.tail: deque[str] = deque(maxlen=300)
        self._threads: list[threading.Thread] = []
        self._multi = False
        self._fatal: str | None = None

    def spawn(self, name: str, cmd: str, cwd: Path | None = None, env: dict | None = None) -> None:
        p = subprocess.Popen(
            sandbox.maybe_wrap(cmd), shell=True, cwd=cwd or self.root, env=env or self.env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True,
            errors="replace",
        )
        self.procs[name] = p
        t = threading.Thread(target=self._pump, args=(name, p), daemon=True)
        t.start()
        self._threads.append(t)

    def _pump(self, name: str, p: subprocess.Popen) -> None:
        assert p.stdout
        try:
            for line in p.stdout:
                line = line.rstrip("\n")
                self.tail.append(line)
                print(f"{name:<8}| {line}" if self._multi else line, flush=True)
                if self._fatal is None and FATAL_WHILE_RUNNING.search(line):
                    self._fatal = name
        except (ValueError, OSError):
            pass                       # flux fermé par l'arrêt pendant la lecture : normal, pas une erreur

    def adopted(self) -> set[int]:
        """Processus détachés (démons) adoptés par zero depuis le lancement, avec leurs descendants."""
        own = {p.pid for p in self.procs.values()}
        out: set[int] = set()
        for c in procs.children(os.getpid()) - self._known_children - own:
            out |= procs.descendants(c)
        return out

    def stop_all(self) -> None:
        orphans = self.adopted()
        for p in self.procs.values():
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.time() + 5
        for p in self.procs.values():
            while p.poll() is None and time.time() < deadline:
                time.sleep(0.1)
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        orphans |= self.adopted()
        if orphans:
            procs.kill_tree(orphans)

    def run(self, commands: dict[str, str | tuple[str, Path, dict]]) -> RunResult:
        """commands : nom → "cmd" ou nom → (cmd, cwd, env) pour un processus dans son propre dossier/environnement."""
        self._multi = len(commands) > 1
        start = time.time()
        for name, spec in commands.items():
            if isinstance(spec, tuple):
                self.spawn(name, *spec)
            else:
                self.spawn(name, spec)
        interrupted, first, code = False, None, 0
        try:
            while first is None:
                if self._fatal:                      # serveur vivant mais en erreur fatale : échec
                    first, code = self._fatal, 1
                    break
                for name, p in self.procs.items():
                    if p.poll() is not None:
                        first, code = name, p.returncode
                        break
                time.sleep(0.2)
        except KeyboardInterrupt:
            interrupted, code = True, 130
        finally:
            self.stop_all()
            for t in self._threads:
                t.join(timeout=2)
            for p in self.procs.values():
                if p.stdout:
                    p.stdout.close()
        return RunResult(code, "\n".join(self.tail), time.time() - start, interrupted, first)
