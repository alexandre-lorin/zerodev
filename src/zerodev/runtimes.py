"""Resolver + Sandbox Runtime : installe des runtimes isolés dans ~/.zero."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from .plan import Plan, venv_dir
from .util import die, fetch, log, with_path, zero_home


def _platform() -> tuple[str, str]:
    sysname = {"Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    arch = {"x86_64": "x64", "AMD64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine())
    if not sysname or not arch:
        die(f"plateforme non supportée : {platform.system()} {platform.machine()}")
    return sysname, arch


# ───────────────────────────── Node ─────────────────────────────

LTS_MAJORS = (24, 22, 20, 18, 16, 14, 12, 10, 8, 6, 4)       # hors-ligne : majeures LTS connues, plus récente d'abord


def _parts(text: str) -> list[int | None]:
    """« 20.11 » → [20, 11, None] ; « 20.x » / « * » → None pour le joker."""
    out: list[int | None] = []
    for tok in text.strip().lstrip("v=").split(".")[:3]:
        out.append(int(tok) if tok.isdigit() else None)
    return (out + [None, None, None])[:3]


def _cmp(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return (a > b) - (a < b)


def _comparator_ok(v: tuple[int, ...], op: str, raw: str) -> bool:
    """Une comparaison élémentaire (`>=20.1`, `^18`, `20.x`, `*`…) appliquée à la version `v`."""
    p = _parts(raw)
    if p[0] is None:                           # « * » : tout
        return True
    lo = tuple(x or 0 for x in p)
    if op in ("", "="):
        if None in p:                          # « 20 » / « 20.11 » / « 20.x » : plage partielle
            n = sum(x is not None for x in p)
            return v[:n] == tuple(p[:n])
        return v == lo
    c = _cmp(v, lo)
    if op == ">=":
        return c >= 0
    if op == ">":
        return c > 0
    if op == "<=":
        return c <= 0
    if op == "<":
        return c < 0
    if op == "^":                              # même majeure (0.x : même mineure)
        return c >= 0 and (v[0] == lo[0] if lo[0] else v[:2] == lo[:2])
    if op == "~":
        return c >= 0 and v[:2] == lo[:2]
    return True


def node_satisfies(version: str, spec: str) -> bool:
    """Plage semver (npm) minimale : >=, >, <=, <, =, ^, ~, jokers (20, 20.x, *) et `||`."""
    v = tuple(int(x) for x in version.lstrip("v").split(".")[:3])
    for alt in (spec or "*").split("||"):
        toks = re.findall(r"(>=|<=|>|<|=|\^|~)?\s*v?([\dxX*][\w.*]*)", alt.strip())
        if toks and all(_comparator_ok(v, op, raw) for op, raw in toks):
            return True
    return False


def pick_node_major(spec: str | None) -> str | None:
    """Hors-ligne : la plus récente majeure LTS qui satisfait la plage (« >=20.0.0 » → 24), sinon None."""
    if not spec or "lts" in spec.lower():
        return None
    for major in LTS_MAJORS:
        if node_satisfies(f"{major}.99.0", spec):
            return str(major)
    return None


def resolve_node(spec: str | None) -> str | None:
    """Spec (18, >=20, ^20.1, v20.11.0, lts/*) → version exacte ; None si hors-ligne.

    Une version exacte ou partielle (20, 20.11) est respectée ; une plage ouverte (>=20.0.0) donne la LTS la plus
    récente qui la satisfait, pas sa borne basse (Next.js & co. refusent 20.0.0)."""
    try:
        index = json.loads(fetch("https://nodejs.org/dist/index.json", timeout=15))
    except Exception:
        return None
    if spec and "lts" not in spec.lower() and re.search(r"\d", spec):
        for lts_only in (True, False):
            for e in index:                                     # index.json : plus récent d'abord
                if (e["lts"] or not lts_only) and node_satisfies(e["version"], spec):
                    return e["version"]
        log(f"Node {spec} introuvable, repli sur la LTS")
    return next(e["version"] for e in index if e["lts"])


def _node_bin(version: str) -> Path:
    return zero_home() / "runtimes" / f"node-{version}"


def ensure_node(plan: Plan, root: Path, env: dict) -> dict:
    spec = plan.pinned or plan.version
    pin = "v" + plan.pinned.lstrip("v") if plan.pinned else None
    full = pin if pin and _node_bin(pin).exists() else resolve_node(spec)
    if full:
        dest = _node_bin(full)
        bindir = dest / "bin"
        if not (bindir / "node").exists():
            sysname, arch = _platform()
            log(f"installation de Node {full} (isolé dans {dest})")
            try:
                url = f"https://nodejs.org/dist/{full}/node-{full}-{sysname}-{arch}.tar.gz"
                with tempfile.TemporaryDirectory() as tmp:
                    tgz = Path(tmp) / "node.tgz"
                    tgz.write_bytes(fetch(url, timeout=300))
                    with tarfile.open(tgz) as t:
                        t.extractall(tmp)
                    extracted = next(p for p in Path(tmp).iterdir() if p.is_dir())
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(extracted), dest)
            except Exception as e:
                log(f"téléchargement direct impossible ({e}), repli sur le paquet npm « node »")
                full = None
        else:
            log(f"Node {full} déjà en cache")
    if not full:
        bindir = _node_via_npm(spec)
    env = with_path(env, bindir)
    env["COREPACK_ENABLE_DOWNLOAD_PROMPT"] = "0"
    if plan.pm in ("pnpm", "yarn", "bun"):
        env = ensure_pm(plan.pm, env, bindir)
    return env


def ensure_pm(pm: str, env: dict, node_bin: Path) -> dict:
    """Rend `pnpm`/`yarn` disponibles dans le PATH (les scripts du projet les appellent eux-mêmes)."""
    shims = zero_home() / "shims" / re.sub(r"[^\w.-]", "_", str(node_bin.parent.name))
    shims.mkdir(parents=True, exist_ok=True)
    if not (shims / pm).exists() and shutil.which("corepack", path=env["PATH"]):
        subprocess.run(["corepack", "enable", "--install-directory", str(shims), pm], env=env,
                       capture_output=True, text=True)
    if (shims / pm).exists():
        return with_path(env, shims)
    pkg_dir = zero_home() / "shims" / "npm-pm"                       # repli : pnpm/yarn depuis npm
    if not (pkg_dir / "node_modules" / ".bin" / pm).exists():
        log(f"installation de {pm} via npm")
        subprocess.run(["npm", "install", "--prefix", str(pkg_dir), pm, "--no-audit", "--no-fund"], env=env)
    return with_path(env, pkg_dir / "node_modules" / ".bin")


def _node_via_npm(spec: str | None) -> Path:
    """Repli : le paquet npm `node` fournit des binaires Node pour une version donnée."""
    m = re.search(r"\d+(?:\.\d+){0,2}", spec or "")
    if not (m and "lts" not in (spec or "").lower()):
        if system := shutil.which("node"):                      # aucune contrainte : le Node du système convient
            log("aucune version demandée et nodejs.org inaccessible : Node du système")
            return Path(system).parent
    if not shutil.which("npm"):
        die("impossible d'obtenir Node (réseau bloqué et npm absent)")
    tag = m.group() if m and "lts" not in (spec or "").lower() else "latest"
    if m and re.search(r"[<>^~|*xX]", spec or ""):         # plage : majeure LTS la plus récente qui la satisfait
        tag = pick_node_major(spec) or tag
    dest = zero_home() / "runtimes" / f"node-npm-{tag}"
    bindir = dest / "node_modules" / "node" / "bin"
    if not (bindir / "node").exists():
        log(f"installation de Node {tag} via npm")
        dest.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["npm", "install", "--prefix", str(dest), f"node@{tag}", "--no-audit", "--no-fund"])
        if r.returncode:
            die(f"npm install node@{tag} a échoué")
    _compatible_npm(dest, bindir, tag)
    return bindir


def npm_for_node(major: int) -> str | None:
    """Version d'npm utilisable avec ce Node (le npm du système est trop récent pour les vieux Node)."""
    if major >= 18:
        return None
    return "3" if major <= 6 else "6" if major < 12 else "8"


def _compatible_npm(dest: Path, bindir: Path, tag: str) -> None:
    """Le paquet npm `node` ne fournit pas npm : en installe un compatible à côté du binaire."""
    m = re.match(r"\d+", tag)
    want = npm_for_node(int(m.group())) if m else None
    if not want or (bindir / "npm").exists():
        return
    log(f"installation de npm@{want} (compatible Node {tag})")
    r = subprocess.run(["npm", "install", "--prefix", str(dest), f"npm@{want}", "--no-audit", "--no-fund"],
                       capture_output=True, text=True)
    cli = dest / "node_modules" / "npm" / "bin"
    if r.returncode or not (cli / "npm-cli.js").exists():
        log("npm compatible indisponible, npm du système conservé")
        return
    for name, target in (("npm", "npm-cli.js"), ("npx", "npx-cli.js")):
        link = bindir / name
        if (cli / target).exists() and not link.exists():
            link.symlink_to(os.path.relpath(cli / target, bindir))


# ───────────────────────────── Python / uv ─────────────────────────────

def ensure_uv(env: dict) -> dict:
    local = zero_home() / "bin"
    if shutil.which("uv", path=str(local) + os.pathsep + env["PATH"]):
        return with_path(env, local)
    log("installation de uv (gestionnaire Python isolé)")
    local.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile("wb", suffix=".sh", delete=False) as f:
            f.write(fetch("https://astral.sh/uv/install.sh", timeout=30))
        r = subprocess.run(["sh", f.name], env=dict(env, UV_UNMANAGED_INSTALL=str(local)))
        if r.returncode:
            raise RuntimeError("installeur uv en échec")
    except Exception:
        log("repli : installation de uv via pip")
        target = zero_home() / "uvpkg"
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--target", str(target), "uv"])
        if r.returncode:
            die("installation de uv impossible")
        return with_path(env, target / "bin")
    return with_path(env, local)


def ensure_python(plan: Plan, root: Path, env: dict) -> dict:
    env = ensure_uv(env)
    venv = venv_dir(root)
    venv.parent.mkdir(parents=True, exist_ok=True)
    env = with_path(env, venv / "bin")
    env["VIRTUAL_ENV"] = str(venv)
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)
    env["UV_PYTHON_INSTALL_DIR"] = str(zero_home() / "runtimes" / "python")
    return env


# ───────────────────────────── Rust ─────────────────────────────

def ensure_rust(plan: Plan, root: Path, env: dict) -> dict:
    cargo_home, rustup_home = zero_home() / "cargo", zero_home() / "rustup"
    env = with_path(dict(env, CARGO_HOME=str(cargo_home), RUSTUP_HOME=str(rustup_home)), cargo_home / "bin")
    if not (cargo_home / "bin" / "rustup").exists():
        log("installation de rustup (isolé)")
        with tempfile.NamedTemporaryFile("wb", suffix=".sh", delete=False) as f:
            f.write(fetch("https://sh.rustup.rs", timeout=60))
        cmd = ["sh", f.name, "-y", "--no-modify-path", "--profile", "minimal", "--default-toolchain", "none"]
        if subprocess.run(cmd, env=env).returncode:
            die("installation de rustup impossible")
    version = plan.pinned or plan.version
    log(f"toolchain Rust {version}")
    if subprocess.run(["rustup", "toolchain", "install", version, "--profile", "minimal"], env=env).returncode:
        die(f"toolchain {version} indisponible")
    env["RUSTUP_TOOLCHAIN"] = version
    return env



# ───────────────────────────── Go ─────────────────────────────

def resolve_go(spec: str | None) -> str | None:
    """Spec (1.22, 1.22.3) → version exacte « 1.22.3 » ; None si hors-ligne."""
    try:
        releases = json.loads(fetch("https://go.dev/dl/?mode=json&include=all", timeout=15))
    except Exception:
        return None
    versions = [r["version"][2:] for r in releases]          # du plus récent au plus ancien
    stable = [r["version"][2:] for r in releases if r.get("stable")]
    m = re.search(r"\d+\.\d+(?:\.\d+)?", spec or "")
    if m:
        want = m.group()
        for v in versions:
            if v == want or v.startswith(want + "."):
                return v
        log(f"Go {spec} introuvable, repli sur la dernière stable")
    return stable[0] if stable else None


def ensure_go(plan: Plan, root: Path, env: dict) -> dict:
    spec = plan.pinned or plan.version
    sysname = {"Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    arch = {"x86_64": "amd64", "AMD64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine())
    env = dict(env, GOPATH=str(zero_home() / "gopath"), GOCACHE=str(zero_home() / "gocache"))
    version = resolve_go(spec) if sysname and arch else None
    if version:
        goroot = zero_home() / "runtimes" / f"go-{version}" / "go"
        if not (goroot / "bin" / "go").exists():
            log(f"installation de Go {version} (isolé dans {goroot.parent})")
            try:
                url = f"https://go.dev/dl/go{version}.{sysname}-{arch}.tar.gz"
                with tempfile.TemporaryDirectory() as tmp:
                    tgz = Path(tmp) / "go.tgz"
                    tgz.write_bytes(fetch(url, timeout=600))
                    goroot.parent.mkdir(parents=True, exist_ok=True)
                    with tarfile.open(tgz) as t:
                        t.extractall(goroot.parent)
            except Exception as e:
                log(f"téléchargement de Go impossible ({e})")
                version = None
        else:
            log(f"Go {version} déjà en cache")
    if version:
        env["GOROOT"] = str(goroot)
        env["GOTOOLCHAIN"] = "local"        # déterministe : pas de téléchargement implicite
        return with_path(env, goroot / "bin")
    if shutil.which("go"):
        log("repli sur le Go du système (version non garantie)")
        return env
    die("impossible d'obtenir Go : réseau bloqué (go.dev) et aucun Go sur le système")

ENSURE = {"node": ensure_node, "python": ensure_python, "rust": ensure_rust, "go": ensure_go}


def installed_version(plan: Plan, root: Path, env: dict) -> str | None:
    """Version exacte réellement utilisée (pour zero freeze)."""
    try:
        if plan.lang == "node":
            out = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True, timeout=10).stdout
            return out.strip().lstrip("v") or None
        if plan.lang == "python":
            py = venv_dir(root) / "bin" / "python"
            if py.exists():
                out = subprocess.run([str(py), "--version"], capture_output=True, text=True, timeout=10).stdout
                return out.strip().replace("Python ", "") or None
        if plan.lang == "go":
            out = subprocess.run(["go", "env", "GOVERSION"], env=env, capture_output=True, text=True, timeout=10).stdout
            return out.strip().removeprefix("go") or None
        if plan.lang == "rust":
            out = subprocess.run(["rustc", "--version"], env=env, capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"rustc ([\d.]+)", out)
            return m.group(1) if m else None
    except Exception:
        return None
    return None
