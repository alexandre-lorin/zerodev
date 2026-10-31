"""`zero report [dépôt]` : un seul bloc de texte à coller dans un retour d'essai (machine + plan + derniers correctifs), sans chemins
personnels ni nom d'utilisateur. Ne lance rien : seul le plan est calculé."""
from __future__ import annotations

import contextlib
import io
import json
import platform
import re
import sys
from pathlib import Path

from .util import VERSION, ZeroError, zero_home

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def redact(text: str, home: Path | None = None, user: str | None = None) -> str:
    """Supprime les codes couleur, remplace le dossier personnel par `~` et le nom d'utilisateur par `<user>`."""
    import getpass
    home = Path(home or Path.home())
    try:
        user = user if user is not None else getpass.getuser()
    except Exception:
        user = ""
    text = ANSI.sub("", text)
    for h in {str(home), str(home.resolve())}:
        if h and h != "/":
            text = text.replace(h, "~")
    if user and len(user) >= 3 and user not in ("root", "user"):
        text = re.sub(rf"(?<![\w.-]){re.escape(user)}(?![\w.-])", "<user>", text)
    return text


def _plan_text(target: str) -> str:
    from .cli import main
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        try:
            code = main(["plan", target])
        except SystemExit as e:
            code = e.code
        except ZeroError as e:
            return f"(erreur : {e})"
    out = (buf.getvalue() + err.getvalue()).strip()
    return out or f"(aucune sortie, code {code})"


def _last_fixes(root: Path, n: int = 5) -> list[str]:
    path = zero_home() / "logs" / f"{root.name}.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(errors="replace").splitlines()[-n:]:
        try:
            d = json.loads(line)
            out.append(f"{d.get('ts', '?')} {d.get('fix', '?')}")
        except ValueError:
            out.append(line[:200])
    return out


def build(target: str | None = None, network: bool = True) -> str:
    from . import doctor
    parts = [f"zero {VERSION} — {platform.system()} {platform.release()} {platform.machine()} — Python {sys.version.split()[0]}", "",
             "## doctor", doctor.render(doctor.collect(network=network))]
    if target:
        root = Path(target).expanduser()
        parts += ["", f"## plan : {root.name}", _plan_text(str(root))]
        fixes = _last_fixes(root.resolve())
        if fixes:
            parts += ["", "## derniers correctifs automatiques", *fixes]
    parts += ["", "## ce qui s'est passé (à compléter) : démarré ? message d'erreur exact ?"]
    return redact("\n".join(parts))
