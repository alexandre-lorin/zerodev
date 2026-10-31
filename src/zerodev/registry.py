"""Registre facultatif : fingerprint de dépôt → environnement connu fonctionnel.

- Toujours local par défaut (~/.zero/registry) : aucune dépendance cloud.
- ZERO_REGISTRY peut pointer vers un dossier partagé (NFS, volume…) ou une URL HTTP(S)
  statique servant {base}/{fingerprint}.json (lecture seule pour HTTP).
- Sécurité : une entrée ne sert qu'à épingler des versions. Les commandes sont toujours
  recalculées depuis le dépôt (voir freeze.apply_lock).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .util import fetch, zero_home


def _local() -> Path:
    p = zero_home() / "registry"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _remote_dir() -> Path | None:
    base = os.environ.get("ZERO_REGISTRY", "")
    if base and not base.startswith(("http://", "https://")):
        p = Path(base.removeprefix("file://"))
        p.mkdir(parents=True, exist_ok=True)
        return p
    return None


def _valid(data: object, fp: str) -> bool:
    return isinstance(data, dict) and data.get("zero_lock") == 1 and data.get("fingerprint") == fp


def lookup(fp: str) -> dict | None:
    cached = _local() / f"{fp}.json"
    if cached.is_file():
        try:
            data = json.loads(cached.read_text())
            if _valid(data, fp):
                return data
        except json.JSONDecodeError:
            pass
    base = os.environ.get("ZERO_REGISTRY", "")
    data = None
    try:
        if (rd := _remote_dir()) and (rd / f"{fp}.json").is_file():
            data = json.loads((rd / f"{fp}.json").read_text())
        elif base.startswith(("http://", "https://")):
            data = json.loads(fetch(f"{base.rstrip('/')}/{fp}.json", timeout=10))
    except Exception:
        return None
    if _valid(data, fp):
        cached.write_text(json.dumps(data))
        return data
    return None


def record(fp: str, lock: dict) -> list[str]:
    """Enregistre un environnement qui a fonctionné. Retourne les emplacements écrits."""
    where = []
    payload = json.dumps(lock, indent=2, ensure_ascii=False)
    (_local() / f"{fp}.json").write_text(payload)
    where.append(str(_local() / f"{fp}.json"))
    if rd := _remote_dir():
        (rd / f"{fp}.json").write_text(payload)
        where.append(str(rd / f"{fp}.json"))
    return where
