"""V2 : `zero freeze` — définition reproductible de l'environnement (zero.lock.json)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .plan import Plan, venv_dir
from .services import ENV_TEMPLATES, Service
from .util import VERSION, platform_tag, read

LOCK_NAME = "zero.lock.json"
FINGERPRINT_FILES = [
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", ".nvmrc", ".node-version",
    "pyproject.toml", "requirements.txt", "uv.lock", "poetry.lock", "Pipfile.lock", ".python-version",
    "setup.py", "Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml",
    ".tool-versions", "Procfile", "Dockerfile", "docker-compose.yml", "compose.yml",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_hashes(root: Path) -> dict[str, str]:
    out = {n: _sha(root / n) for n in FINGERPRINT_FILES if (root / n).is_file()}
    req = root / "requirements"
    if req.is_dir():                    # requirements/**/*.txt (toutes les variantes : l'empreinte ne dépend pas du matériel)
        for f in sorted(req.rglob("*.txt")):
            if f.is_file():
                out[str(f.relative_to(root))] = _sha(f)
    if not out:                         # aucun manifeste : les scripts racine tiennent lieu de manifeste (dépendances déduites des import)
        for f in sorted(root.glob("*.py")):
            if f.is_file() and f.stat().st_size < 400_000:
                out[f.name] = _sha(f)
    return out


def fingerprint(root: Path) -> str:
    """Empreinte stable du dépôt : manifestes + lockfiles (pas le code source)."""
    h = hashlib.sha256()
    for name, digest in sorted(file_hashes(root).items()):
        h.update(f"{name}:{digest}\n".encode())
    return h.hexdigest()[:24]


def system_libs(root: Path) -> dict[str, list[str]]:
    """Paquets système apt/brew cités dans Dockerfile, CI et README."""
    sources = [read(root, "Dockerfile") or ""]
    for p in list(root.glob(".github/workflows/*.y*ml")) + [root / ".gitlab-ci.yml"]:
        if p.is_file():
            sources.append(p.read_text(errors="ignore"))
    sources.append(read(root, "README.md") or "")
    text = "\n".join(sources).replace("\\\n", " ")
    out: dict[str, set[str]] = {"apt": set(), "brew": set()}
    for key, pattern in (("apt", r"apt(?:-get)?\s+install\s+([^\n&|;]+)"), ("brew", r"brew\s+install\s+([^\n&|;]+)")):
        for m in re.finditer(pattern, text):
            for tok in m.group(1).split():
                if re.fullmatch(r"[a-z0-9][a-z0-9+.\-]*", tok) and not tok.startswith("-"):
                    out[key].add(tok)
    return {k: sorted(v) for k, v in out.items() if v}


def exposed_ports(root: Path, services: list[Service]) -> list[int]:
    ports = {s.default_port for s in services}
    for m in re.finditer(r"^\s*EXPOSE\s+(\d+)", read(root, "Dockerfile") or "", re.M):
        ports.add(int(m.group(1)))
    return sorted(ports)


def env_keys(root: Path) -> list[str]:
    for t in ENV_TEMPLATES:
        text = read(root, t)
        if text:
            return sorted(set(re.findall(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=", text, re.M)))
    return []


def build_lock(root: Path, plan: Plan, services: list[Service], gpu: dict, resolved: str | None) -> dict:
    venv = str(venv_dir(root))
    return {
        "zero_lock": 1,
        "created_by": f"zerodev {VERSION}",
        "fingerprint": fingerprint(root),
        "platform": platform_tag(),
        "runtime": {
            "lang": plan.lang, "spec": plan.version, "resolved": resolved or plan.pinned,
            "source": plan.source, "package_manager": plan.pm,
        },
        "install": [c.replace(venv, "{venv}") for c in plan.install],
        "run": plan.run,
        "processes": plan.processes,
        "services": [
            {"kind": s.kind, "image": s.image, "port": s.default_port, "detected_from": s.sources}
            for s in services
        ],
        "env": {"keys": env_keys(root)},   # jamais les valeurs
        "ports": exposed_ports(root, services),
        "system_libs": system_libs(root),
        "gpu": {"libs": plan.ai_libs, "required": bool(plan.ai_libs), "freeze_host": gpu},
        "files": file_hashes(root),
    }


def write_lock(root: Path, lock: dict) -> Path:
    p = root / LOCK_NAME
    p.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
    return p


def load_lock(root: Path) -> dict | None:
    p = root / LOCK_NAME
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
    return data if data.get("zero_lock") == 1 else None


def apply_lock(plan: Plan, lock: dict, origin: str = LOCK_NAME) -> bool:
    """Épingle la version exacte. Les commandes restent TOUJOURS recalculées depuis le dépôt :
    un lock (ou une entrée de registre) ne peut donc pas injecter de commande arbitraire."""
    rt = lock.get("runtime") or {}
    if rt.get("lang") != plan.lang or not rt.get("resolved"):
        return False
    plan.pinned = rt["resolved"]
    plan.source = f"{origin} ({rt['resolved']})"
    return True


def lock_drift(root: Path, lock: dict) -> list[str]:
    """Fichiers modifiés depuis le freeze."""
    now = file_hashes(root)
    old = lock.get("files", {})
    return sorted(n for n in set(now) | set(old) if now.get(n) != old.get(n))
