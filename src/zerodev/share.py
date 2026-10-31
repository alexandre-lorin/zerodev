"""V3 : `zero share` — « works on my machine » → « here is my machine state ».

Le bundle (.zeroshare.tgz) contient le code (fichiers suivis + non ignorés), zero.lock.json,
un template .env SANS valeurs secrètes et un manifeste de provenance. Les secrets
(.env, clés privées, tokens) ne sont jamais embarqués.
"""
from __future__ import annotations

import fnmatch
import io
import json
import os
import subprocess
import tarfile
import time
from pathlib import Path

from .freeze import LOCK_NAME
from .services import ENV_TEMPLATES
from .util import VERSION, die

BUNDLE_SUFFIX = ".zeroshare.tgz"
MAX_FILE = 5 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
SKIP_DIRS = {".git", "node_modules", "target", "__pycache__", ".venv", "venv", ".zero", "dist", "build"}
SECRET_GLOBS = [".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "*.p12", ".npmrc",
                ".pypirc", "credentials*", "*.keystore", ".netrc"]
TEMPLATE_NAMES = set(ENV_TEMPLATES)


def is_secret(name: str) -> bool:
    if name in TEMPLATE_NAMES:
        return False
    return any(fnmatch.fnmatch(name, g) for g in SECRET_GLOBS)


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def list_files(root: Path) -> list[Path]:
    out = _git(root, "ls-files", "-co", "--exclude-standard", "-z")
    if out is not None and (root / ".git").exists():
        names = [n for n in out.split("\0") if n]
        files = [root / n for n in names]
    else:
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            files += [Path(dirpath) / f for f in filenames]
    return [f for f in files if f.is_file() and not f.is_symlink()]


def blank_env(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            lines.append(line.split("=", 1)[0] + "=")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def create_bundle(root: Path, out_dir: Path | None = None) -> Path:
    if not (root / LOCK_NAME).is_file():
        die(f"{LOCK_NAME} absent : lancez d'abord `zero freeze`")
    out = (out_dir or Path.cwd()) / f"{root.resolve().name}{BUNDLE_SUFFIX}"
    manifest = {
        "bundle": 1, "created_by": f"zerodev {VERSION}", "name": root.resolve().name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "git": {"remote": _git(root, "remote", "get-url", "origin"), "commit": _git(root, "rev-parse", "HEAD"),
                "dirty": bool(_git(root, "status", "--porcelain"))},
    }
    total, skipped = 0, []
    with tarfile.open(out, "w:gz") as tar:
        data = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for f in list_files(root):
            rel = f.relative_to(root)
            if is_secret(f.name):
                skipped.append(str(rel))
                continue
            size = f.stat().st_size
            if size > MAX_FILE:
                skipped.append(f"{rel} (>5 Mo)")
                continue
            total += size
            if total > MAX_TOTAL:
                out.unlink(missing_ok=True)
                die("bundle > 100 Mo : le dépôt est trop gros pour `zero share` (V3)")
            tar.add(f, arcname=f"src/{rel}")
        # template .env sans valeurs, si le dépôt n'en fournit pas
        if not any((root / t).is_file() for t in ENV_TEMPLATES) and (root / ".env").is_file():
            data = blank_env((root / ".env").read_text(errors="ignore")).encode()
            info = tarfile.TarInfo("src/.env.example")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    if skipped:
        print(f"  non embarqués (secrets/gros fichiers) : {', '.join(skipped)}")
    return out


def _safe_members(tar: tarfile.TarFile, dest: Path):
    base = dest.resolve()
    for m in tar.getmembers():
        target = (dest / m.name).resolve()
        if not str(target).startswith(str(base) + os.sep) and target != base:
            die(f"bundle refusé (chemin hors destination) : {m.name}")
        if m.issym() or m.islnk() or m.isdev():
            continue
        yield m


def open_bundle(bundle: Path, parent: Path | None = None) -> Path:
    """Extrait un bundle dans ./<name>/ et retourne la racine du projet."""
    with tarfile.open(bundle, "r:gz") as tar:
        try:
            manifest = json.load(tar.extractfile("manifest.json"))  # type: ignore[arg-type]
        except KeyError:
            die("bundle invalide : manifest.json absent")
        dest = (parent or Path.cwd()) / manifest["name"]
        if dest.exists():
            die(f"{dest} existe déjà : supprimez-le ou changez de dossier")
        members = [m for m in _safe_members(tar, dest.parent) if m.name.startswith("src/")]
        for m in members:
            m.name = m.name[len("src/"):]
            if not m.name:
                continue
            try:
                tar.extract(m, dest, filter="data")
            except TypeError:  # Python < 3.11.4 : pas de paramètre filter
                tar.extract(m, dest)
    return dest
