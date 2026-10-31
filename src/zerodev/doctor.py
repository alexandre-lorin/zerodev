"""`zero doctor` : l'état de la machine en un coup d'œil (système, outils, conteneurs, GPU, réseau, disque).

Sert surtout à joindre un diagnostic fiable à un retour d'essai : tout ce qui est affiché peut être collé tel quel."""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import urllib.request

from . import gpu, localsvc, sandbox
from .util import VERSION, zero_home

REACH_URLS = {"github.com": "https://github.com", "pypi.org": "https://pypi.org/simple/",
              "registry.npmjs.org": "https://registry.npmjs.org/", "nodejs.org": "https://nodejs.org/dist/index.json",
              "go.dev": "https://go.dev/dl/?mode=json", "static.rust-lang.org": "https://static.rust-lang.org/dist/channel-rust-stable.toml"}


VERSION_CMDS = {"go": ["go", "version"]}          # go n'a pas de --version


def _version(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip().splitlines()
    return text[0][:80] if text and out.returncode == 0 else None


def _reachable(url: str, timeout: float = 5.0) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": f"zerodev/{VERSION}"})
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True                 # le serveur répond : joignable (405 sur HEAD, par exemple)
    except Exception:
        return False


def _user() -> str:
    import getpass
    try:
        return getpass.getuser()
    except Exception:
        return "?"


def _ipv6() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


def _container_runtime() -> dict:
    out: dict = {}
    for name in ("docker", "podman"):
        path = shutil.which(name)
        if not path:
            out[name] = None
            continue
        ver = _version([name, "--version"])
        try:
            ok = subprocess.run([name, "info"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        out[name] = {"version": ver, "daemon": ok}
    return out


def collect(network: bool = True) -> dict:
    home = zero_home()
    probe = home
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free // (1024 * 1024)
    info = {
        "zerodev": VERSION,
        "system": {"os": platform.platform(), "arch": platform.machine(), "python": sys.version.split()[0],
                   "user": _user(), "root": os.geteuid() == 0
                   if hasattr(os, "geteuid") else None, "ipv6_loopback": _ipv6()},
        "disk": {"zero_home": str(home), "free_mb": free},
        "tools": {t: (_version(VERSION_CMDS.get(t, [t, "--version"])) if shutil.which(t) else None)
                  for t in ("git", "uv", "node", "npm", "pnpm", "yarn", "bun", "cargo", "go")},
        "containers": _container_runtime(),
        "local_services": {"redis": shutil.which("redis-server"), "postgres": localsvc._pg("initdb") if hasattr(localsvc, "_pg") else None,
                           "mysql/mariadb": bool(localsvc.available("mysql")), "mongodb": shutil.which("mongod")},
        "gpu": gpu.detect_gpu(),
        "sandbox": {"bwrap": shutil.which("bwrap"), "sandbox_exec": shutil.which("sandbox-exec"), "backend": sandbox.backend(), "usable": sandbox.available()},
    }
    if network:
        info["network"] = {host: _reachable(url) for host, url in REACH_URLS.items()}
    return info


def render(info: dict) -> str:
    ok = lambda v: "✓" if v else "✗"
    sy, lines = info["system"], []
    add = lines.append
    add(f"zerodev {info['zerodev']}  —  {sy['os']} ({sy['arch']}), Python {sy['python']}")
    add(f"utilisateur {sy['user']}{' (root)' if sy['root'] else ''} ; IPv6 loopback {ok(sy['ipv6_loopback'])} ; "
        f"{info['disk']['free_mb']} Mo libres dans {info['disk']['zero_home']}")
    add("\nOutils :")
    for k, v in info["tools"].items():
        add(f"  {ok(v)} {k:<6} {v or 'absent'}")
    add("\nConteneurs :")
    for k, v in info["containers"].items():
        add(f"  {ok(v and v['daemon'])} {k:<7} " + ("absent" if not v else f"{v['version']} — démon {'joignable' if v['daemon'] else 'INJOIGNABLE'}"))
    add("\nServices locaux (repli sans conteneur) :")
    for k, v in info["local_services"].items():
        add(f"  {ok(v)} {k:<14} {v if isinstance(v, str) else ('présent' if v else 'absent')}")
    g = info["gpu"]
    add(f"\nGPU : {g['vendor'] or 'aucun détecté'}" + (f" — {g['name']}" if g.get("name") else "") + (f", CUDA {g['cuda']}" if g.get("cuda") else ""))
    sb = info["sandbox"]
    names = {"bwrap": "bubblewrap", "sandbox-exec": "sandbox-exec (macOS)"}
    if sb["usable"]:
        detail = f"{names[sb['backend']]} utilisable"
    elif sb["bwrap"]:
        detail = "bubblewrap présent mais inutilisable (espaces de noms utilisateur interdits ?)"
    elif sb["sandbox_exec"]:
        detail = "sandbox-exec présent mais inutilisable"
    else:
        detail = "bubblewrap (Linux) / sandbox-exec (macOS) absent"
    add(f"\nIsolation (--sandbox) : {ok(sb['usable'])} {detail}")
    if "network" in info:
        add("\nRéseau (HEAD, 5 s) :")
        for host, v in info["network"].items():
            add(f"  {ok(v)} {host}")
    return "\n".join(lines)
