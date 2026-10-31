"""Exécution isolée (`--sandbox`, spécification §3) : bubblewrap sous Linux, `sandbox-exec` sous macOS (non éprouvé sur un vrai Mac).

Ce qui est protégé : le dossier personnel de l'utilisateur (clés SSH, jetons, profils de navigateur…) est **masqué**, le reste du système est
en **lecture seule** ; l'écriture n'est possible que dans le dépôt, dans `~/.zero` et dans un /tmp privé ; les processus sont dans un espace de
noms PID/IPC isolé. Ce qui ne l'est PAS : le réseau (un serveur de développement doit rester joignable ; un dépôt peut donc faire des requêtes
sortantes), les fichiers lisibles du système hors dossier personnel (/etc, /usr…), le processeur et la mémoire. Ce n'est pas une barrière contre un
code activement hostile qui exploiterait le noyau : c'est une limitation des dégâts d'un projet douteux, pas une garantie."""
from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .util import ZeroError, zero_home

_state: dict = {"root": None, "ok": None, "backend": None}
CACHE_VARS = {"UV_CACHE_DIR": "uv", "npm_config_cache": "npm", "PIP_CACHE_DIR": "pip", "YARN_CACHE_FOLDER": "yarn",
              "npm_config_store_dir": "pnpm"}            # sans cela, les caches iraient dans le dossier personnel masqué (donc perdus)


def _bwrap_usable() -> bool:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return False
    try:
        return subprocess.run([bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "true"], capture_output=True,
                              timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _seatbelt_usable() -> bool:
    """macOS : `sandbox-exec` présent et capable d'appliquer un profil minimal (déprécié par Apple mais toujours livré)."""
    exe = shutil.which("sandbox-exec")
    if sys.platform != "darwin" or not exe:
        return False
    try:
        return subprocess.run([exe, "-p", "(version 1)(allow default)", "true"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def backend() -> str | None:
    """« bwrap » (Linux), « sandbox-exec » (macOS) ou None si aucune isolation n'est utilisable ici."""
    if _state["ok"] is None:
        _state["backend"] = "bwrap" if _bwrap_usable() else "sandbox-exec" if _seatbelt_usable() else None
        _state["ok"] = _state["backend"] is not None
    return _state["backend"]


def available() -> bool:
    """Une isolation utilisable (bubblewrap sous Linux — les espaces de noms utilisateur peuvent être interdits —, sandbox-exec sous macOS)."""
    return backend() is not None


def enable(root: Path) -> None:
    """Active l'isolation pour la session ; refuse de continuer sans l'outil (jamais de repli silencieux sans isolation)."""
    if not available():
        raise ZeroError("--sandbox demande bubblewrap et les espaces de noms utilisateur (Linux : `apt install bubblewrap` / "
                        "`dnf install bubblewrap`) ou `sandbox-exec` (macOS). Rien n'a été lancé.")
    _state["root"] = Path(root).resolve()


def disable() -> None:
    _state["root"] = None


def enabled() -> bool:
    return _state["root"] is not None


def build_args(root: Path, home: Path | None = None, zhome: Path | None = None, extra_rw: list[Path] | None = None) -> list[str]:
    """Arguments bwrap (sans la commande) : ordre important, chaque montage après un tmpfs recrée ses dossiers."""
    home = Path(home or Path.home()).resolve()
    zhome = Path(zhome or zero_home()).resolve()
    zhome.mkdir(parents=True, exist_ok=True)
    args = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", str(home), "--tmpfs", "/tmp"]
    seen: set[str] = set()
    for p in [zhome, Path(root).resolve(), *(extra_rw or [])]:
        if str(p) not in seen:
            seen.add(str(p))
            args += ["--bind", str(p), str(p)]
    for var, sub in CACHE_VARS.items():
        d = zhome / "cache" / sub
        d.mkdir(parents=True, exist_ok=True)
        args += ["--setenv", var, str(d)]
    return args + ["--unshare-pid", "--unshare-ipc", "--die-with-parent", "--new-session"]


def _sbpl(path: Path | str) -> str:
    """Chaîne SBPL entre guillemets (échappe `\\` et `"`)."""
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(root: Path, home: Path | None = None, zhome: Path | None = None, extra_rw: list[Path] | None = None) -> str:
    """Profil `sandbox-exec` équivalent (en moins strict) à la configuration bwrap. SBPL : la dernière règle qui correspond l'emporte.

    Écriture refusée partout sauf dépôt, ~/.zero, /tmp et dossiers temporaires macOS ; lecture du dossier personnel refusée sauf dépôt et
    ~/.zero. Différences avec bwrap : pas de /tmp privé (celui de l'hôte reste partagé), pas d'espace de noms PID/IPC, et les outils installés
    dans le dossier personnel (nvm, ~/.cargo…) deviennent illisibles comme sous Linux. Réseau non isolé."""
    home = Path(home or Path.home()).resolve()
    zhome = Path(zhome or zero_home()).resolve()
    zhome.mkdir(parents=True, exist_ok=True)
    rw = [zhome, Path(root).resolve(), *(Path(p).resolve() for p in (extra_rw or []))]
    tmp_dirs = ["/private/tmp", "/private/var/folders", "/private/var/tmp"]
    lines = ["(version 1)", "(allow default)", "(deny file-write*)",
             "(allow file-write* " + " ".join(f"(subpath {_sbpl(p)})" for p in [*rw, *tmp_dirs]) + ")",
             '(allow file-write* (literal "/dev/null") (literal "/dev/tty") (regex #"^/dev/(fd|pts|ttys)"))',
             f"(deny file-read* (subpath {_sbpl(home)}))",
             "(allow file-read* " + " ".join(f"(subpath {_sbpl(p)})" for p in rw) + ")"]
    return "\n".join(lines)


def seatbelt_env(zhome: Path | None = None) -> dict[str, str]:
    """Variables de cache redirigées dans ~/.zero (sinon elles iraient dans le dossier personnel, illisible)."""
    zhome = Path(zhome or zero_home()).resolve()
    out = {}
    for var, sub in CACHE_VARS.items():
        d = zhome / "cache" / sub
        d.mkdir(parents=True, exist_ok=True)
        out[var] = str(d)
    return out


def wrap(cmd: str, root: Path | None = None, mode: str | None = None, **kw) -> str:
    """Commande shell `cmd` enveloppée dans bwrap (Linux) ou sandbox-exec (macOS) ; le shell interne reste `sh -c`."""
    root = root or _state["root"]
    if (mode or _state.get("backend")) == "sandbox-exec":
        env = " ".join(f"{k}={shlex.quote(v)}" for k, v in seatbelt_env(kw.get("zhome")).items())
        return (f"sandbox-exec -p {shlex.quote(seatbelt_profile(root, **kw))} env {env} sh -c " + shlex.quote(cmd))
    return " ".join(shlex.quote(a) for a in build_args(root, **kw)) + " sh -c " + shlex.quote(cmd)


def maybe_wrap(cmd: str) -> str:
    """Appelé aux points d'exécution de code de dépôt (installation, lancement) : enveloppe seulement si `--sandbox` est actif."""
    return wrap(cmd) if enabled() else cmd
