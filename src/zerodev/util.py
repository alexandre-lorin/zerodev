"""Utilitaires communs : logs, shell, réseau, lecture de manifestes."""
from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

try:
    import tomllib  # Python >= 3.11
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

q = shlex.quote
HAS_TOML = tomllib is not None
VERSION = "0.26.1"


class ZeroError(Exception):
    """Erreur attendue (affichée proprement par le CLI)."""


def zero_home() -> Path:
    return Path(os.environ.get("ZERO_HOME", Path.home() / ".zero"))


def log(msg: str) -> None:
    print(f"\033[1;36m[zero]\033[0m {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"\033[1;33m[zero] attention :\033[0m {msg}", flush=True)


def die(msg: str):
    raise ZeroError(msg)


def sh(cmd: str, cwd: Path, env: dict, check: bool = True) -> int:
    print(f"  \033[2m$ {cmd}\033[0m", flush=True)
    code = subprocess.run(cmd, shell=True, cwd=cwd, env=env).returncode
    if code and check:
        die(f"commande échouée ({code}) : {cmd}")
    return code


def run_tee(cmd: str, cwd: Path, env: dict) -> tuple[int, str]:
    """Exécute une commande en affichant sa sortie en direct ET en la gardant (pour le diagnostic)."""
    from collections import deque
    print(f"  \033[2m$ {cmd}\033[0m", flush=True)
    head: list[str] = []                    # début de la sortie : l'erreur utile (ex. « pg_config.h: No such file »)
    tail: deque[str] = deque(maxlen=200)    # peut précéder des centaines de lignes de compilation
    from . import sandbox
    p = subprocess.Popen(sandbox.maybe_wrap(cmd), shell=True, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, errors="replace")
    assert p.stdout
    for line in p.stdout:
        line = line.rstrip("\n")
        if len(head) < 150:
            head.append(line)
        else:
            tail.append(line)
        print(line, flush=True)
    return p.wait(), "\n".join(head + list(tail))


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"zerodev/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, OSError) as e:   # HTTPError hérite de URLError
        die(f"téléchargement impossible : {url} ({e}) — vérifiez le réseau ou le proxy")


def read(root: Path, name: str) -> str | None:
    p = root / name
    return p.read_text(errors="ignore").strip() if p.is_file() else None


def tool_versions(root: Path, tool: str) -> str | None:
    """Lit .tool-versions (asdf/mise)."""
    aliases = {"node": ("node", "nodejs"), "python": ("python",), "rust": ("rust",)}
    for line in (read(root, ".tool-versions") or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in aliases.get(tool, (tool,)):
            return parts[1]
    return None


def with_path(env: dict, *dirs: Path) -> dict:
    env = dict(env)
    env["PATH"] = os.pathsep.join([str(d) for d in dirs] + [env.get("PATH", "")])
    return env


def toml(root: Path, name: str) -> dict:
    p = root / name
    if not p.is_file() or not tomllib:
        return {}
    try:
        return tomllib.loads(p.read_text())
    except Exception:
        return {}


MANIFESTS = [
    "package.json", "pyproject.toml", "requirements.txt", "setup.py", "Pipfile",
    "Cargo.toml", "go.mod", "Gemfile",
]


REQ_DIR_NAMES = ("base", "common", "main", "prod", "production", "requirements", "default")


def requirements_file(root: Path) -> str | None:
    """Chemin relatif du fichier de dépendances principal : requirements.txt, sinon requirements/<base|common|…>.txt.
    Pas de choix entre variantes (cpu/gpu/dev) : on ne devine que les noms usuels du jeu « de base »."""
    if (root / "requirements.txt").is_file():
        return "requirements.txt"
    d = root / "requirements"
    if d.is_dir():
        for name in REQ_DIR_NAMES:
            if (d / f"{name}.txt").is_file():
                return f"requirements/{name}.txt"
    return None


def dep_text(root: Path) -> str:
    """Concatène (en minuscules) les manifestes de dépendances du dépôt."""
    chunks = []
    for name in MANIFESTS:
        t = read(root, name)
        if t:
            chunks.append(t.lower())
    for p in sorted(root.glob("requirements*.txt")) + sorted(root.glob("requirements/*.txt")):
        if p.name != "requirements.txt" or p.parent != root:
            chunks.append(p.read_text(errors="ignore").lower())
    return "\n".join(chunks)


def has_dep(text: str, *names: str) -> bool:
    return any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text) for n in names)


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def free_port(preferred: int) -> int:
    if not port_open(preferred):
        return preferred
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def platform_tag() -> dict:
    import platform
    return {"os": platform.system().lower(), "arch": platform.machine().lower()}


