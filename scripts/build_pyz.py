#!/usr/bin/env python3
"""Construit `dist/zero.pyz` : un exécutable unique (zipapp), sans installation ni dépendance.

    python3 scripts/build_pyz.py        # → dist/zero.pyz ; puis : ./dist/zero.pyz run <dépôt>

Nécessite seulement Python ≥ 3.10 sur la machine qui l'exécute (la même exigence que `zero`)."""
from __future__ import annotations

import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(out: Path | None = None) -> Path:
    out = out or ROOT / "dist" / "zero.pyz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(ROOT / "src" / "zerodev", Path(tmp) / "zerodev",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        zipapp.create_archive(tmp, target=out, main="zerodev.cli:main", interpreter="/usr/bin/env python3", compressed=True)
    out.chmod(0o755)
    return out


if __name__ == "__main__":
    path = build(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(f"{path} ({path.stat().st_size // 1024} Ko)")
