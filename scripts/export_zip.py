#!/usr/bin/env python3
"""Construit le zip de livraison depuis un export PROPRE du dépôt git (fichiers suivis + historique .git), jamais depuis le dossier de travail.

    python3 scripts/export_zip.py /chemin/zerodev.zip

Le dossier de travail contient des artefacts (__pycache__, build/, dist/, caches) qu'un zip de ce dossier embarquerait ; un `git add -A` distrait peut même les
suivre par erreur (c'est arrivé : build/ avait été commité). Le script refuse un dépôt aux modifications non validées et signale tout fichier suspect suivi."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUSPECT = re.compile(r"(^|/)(__pycache__|build|dist|node_modules|[^/]*\.egg-info)(/|$)|\.pyc$")


def export(out: Path) -> tuple[Path, int]:
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit("modifications non validées : committez d'abord (le zip est construit depuis git, pas depuis le dossier de travail)\n" + dirty)
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    bad = [f for f in tracked if SUSPECT.search(f)]
    if bad:
        raise SystemExit("fichiers suspects suivis par git : " + ", ".join(bad[:5]))
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(Path(tmp) / "zerodev")], check=True)
        out = Path(out)
        out.unlink(missing_ok=True)
        archive = shutil.make_archive(str(out.with_suffix("")), "zip", tmp, "zerodev")
    return Path(archive), len(tracked)


if __name__ == "__main__":
    path, n = export(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "zerodev.zip"))
    print(f"{path} ({path.stat().st_size // 1024} Ko, {n} fichiers suivis)")
