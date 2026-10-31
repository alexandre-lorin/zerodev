"""Detectors : Repository → Plan (runtime, version, install, commande principale)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import gpu as gpumod
from .util import HAS_TOML, ZeroError, dep_text, die, has_dep, q, read, requirements_file, toml, tool_versions, zero_home

AI_LIBS = [
    "torch", "torchvision", "torchaudio", "tensorflow", "jax", "llama-cpp-python",
    "onnxruntime-gpu", "vllm", "xformers", "bitsandbytes", "cupy", "diffusers",
    "transformers", "accelerate",
]


@dataclass
class Plan:
    lang: str
    version: str | None
    source: str                       # d'où vient la version demandée
    install: list[str]                # commandes d'installation
    run: str | None                   # commande principale
    notes: list[str] = field(default_factory=list)
    pm: str | None = None             # gestionnaire de paquets
    processes: dict[str, str] = field(default_factory=dict)  # Procfile : web, worker…
    ai_libs: list[str] = field(default_factory=list)
    pinned: str | None = None         # version exacte issue de zero.lock.json
    choices: list[str] = field(default_factory=list)  # points d'entrée possibles quand on refuse de deviner
    soft_steps: list[str] = field(default_factory=list)  # étapes d'installation ignorables si elles échouent
    optional_steps: list[str] = field(default_factory=list)  # étapes dont l'échec n'empêche pas le lancement (avertissement)


# ───────────────────────────── Node ─────────────────────────────

# Signes qu'un fichier est un programme et non le point d'entrée d'une bibliothèque : shebang, garde
# `require.main === module`, lecture d'arguments, ou appel `app.listen(...)` au niveau racine (non indenté).
EXEC_HINT = re.compile(r"^#!.*node|require\.main\s*===\s*module|process\.argv|import\.meta\.main|"
                       r"^[A-Za-z_$][\w$.]*\.listen\(", re.M)


def _looks_executable(path: Path) -> bool:
    try:
        return bool(EXEC_HINT.search(path.read_text(errors="ignore")[:200_000]))
    except OSError:
        return False


def _node_version(root: Path, pkg: dict) -> tuple[str | None, str]:
    """Version de Node : `.nvmrc`, `.node-version`, `.tool-versions`, `engines.node`, sinon déduite du Dockerfile/de la CI, sinon la LTS."""
    for src, val in (
        (".nvmrc", read(root, ".nvmrc")),
        (".node-version", read(root, ".node-version")),
        (".tool-versions", tool_versions(root, "node")),
        ("package.json engines.node", (pkg.get("engines") or {}).get("node")),
    ):
        if val:
            return val, src
    hint = runtime_hint(root, "node")
    if hint:
        return hint[0], f"déduit de {hint[1]} (aucune version déclarée)"
    return None, "défaut (LTS)"


def _node_package_manager(root: Path, pkg: dict) -> tuple[str, str]:
    """(gestionnaire, commande d'installation) d'après les lockfiles, `packageManager` ou les scripts (bun)."""
    pm_field = (pkg.get("packageManager") or "").split("@")[0]
    if (root / "pnpm-lock.yaml").exists() or pm_field == "pnpm":
        return "pnpm", "pnpm install"
    if (root / "yarn.lock").exists() or pm_field == "yarn":
        return "yarn", "yarn install"
    if (root / "bun.lock").exists() or (root / "bun.lockb").exists() or pm_field == "bun" \
            or re.search(r"\bbun\s+(run|x|install)\b", " ".join((pkg.get("scripts") or {}).values())):
        return "bun", "bun install"
    if (root / "package-lock.json").exists():
        return "npm", "npm ci"
    return "npm", "npm install"


def _node_run(root: Path, pkg: dict, pm: str) -> tuple[list[str], str | None]:
    """(étapes supplémentaires, commande de lancement) : script `dev`, sinon `start` (avec `build` s'il existe), sinon `main`, `bin`
    ou un fichier d'entrée usuel qui démarre vraiment quelque chose."""
    scripts = pkg.get("scripts") or {}
    if "dev" in scripts:
        return [], f"{pm} run dev"
    if "start" in scripts:
        return ([f"{pm} run build"] if "build" in scripts else []), f"{pm} run start"
    if pkg.get("main") and (root / pkg["main"]).is_file() and _looks_executable(root / pkg["main"]):
        return [], f"node {q(pkg['main'])}"
    if (b := pkg.get("bin")) and (root / (b if isinstance(b, str) else next(iter(b.values()), ""))).is_file():
        return [], f"node {q(b if isinstance(b, str) else next(iter(b.values())))}"
    for cand in ("index.js", "server.js", "app.js", "main.js"):
        if (root / cand).is_file() and _looks_executable(root / cand):
            return [], f"node {cand}"
    return [], None


def detect_node(root: Path) -> Plan | None:
    pkg_file = root / "package.json"
    if not pkg_file.is_file():
        return None
    try:
        pkg = json.loads(pkg_file.read_text())
    except json.JSONDecodeError:
        die("package.json invalide")
    version, source = _node_version(root, pkg)
    pm, install = _node_package_manager(root, pkg)
    extra, run = _node_run(root, pkg, pm)
    notes = [f"gestionnaire : {pm}"]
    if run is None and pkg.get("main"):
        notes.append("bibliothèque probable : le fichier main ne démarre rien (pas de listen/argv/shebang)")
    return Plan("node", version, source, [install] + extra, run, notes, pm=pm)


# ───────────────────────────── Python ─────────────────────────────

MAKE_RUN_TARGETS = ("run", "dev", "start", "serve", "server")     # par ordre de préférence


def makefile_run(root: Path) -> tuple[str, str] | None:
    """Dernier recours (§2) : une cible `run`/`dev`/`start`/`serve`/`server` du Makefile → (`make cible`, cible).

    Ignore les cibles vides ou qui ne font qu'afficher (`@echo`), et les cibles génériques à motif (`%`)."""
    for name in ("Makefile", "makefile", "GNUmakefile"):
        text = read(root, name)
        if text:
            break
    else:
        return None
    bodies: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z][\w.-]*)\s*:(?!=)", line)
        if m:
            current = m.group(1)
            bodies.setdefault(current, [])
            rest = line.split(":", 1)[1].split("#")[0].strip()
            if rest and not rest.startswith(("=", "$")):
                bodies[current].append("deps:" + rest)      # prérequis : on les compte comme du contenu
        elif line.startswith("\t") and current:
            bodies[current].append(line.strip())
        elif line.strip() and not line.startswith(("#", " ")):
            current = None
    for target in MAKE_RUN_TARGETS:
        body = [b for b in bodies.get(target, []) if not re.match(r"^[@-]*(echo|printf)\b", b)]
        if body:
            return f"make {target}", target
    return None


def pipfile_specs(root: Path) -> list[str]:
    """Paquets d'un projet Pipenv : `Pipfile.lock` (versions exactes) sinon `Pipfile`. Sans git/chemin local."""
    specs: list[str] = []
    lock = root / "Pipfile.lock"
    if lock.is_file():
        try:
            entries = (json.loads(lock.read_text()).get("default") or {}).items()
        except (ValueError, OSError):
            entries = []
        for name, e in entries:
            if not isinstance(e, dict) or any(k in e for k in ("git", "path", "file", "ref", "editable")):
                continue
            extras = f"[{','.join(e['extras'])}]" if e.get("extras") else ""
            marker = f" ; {e['markers']}" if e.get("markers") else ""
            specs.append(f"{name}{extras}{e.get('version', '')}{marker}")
        if specs:
            return specs
    for name, e in (toml(root, "Pipfile").get("packages") or {}).items():
        if isinstance(e, str):
            specs.append(name + ("" if e.strip() in ("*", "") else e.strip()))
        elif isinstance(e, dict) and not any(k in e for k in ("git", "path", "file", "ref", "editable")):
            extras = f"[{','.join(e['extras'])}]" if e.get("extras") else ""
            v = str(e.get("version", "*")).strip()
            specs.append(f"{name}{extras}{'' if v in ('*', '') else v}")
    return specs


def pipfile_python(root: Path) -> str | None:
    """`[requires] python_full_version / python_version` du Pipfile."""
    req = toml(root, "Pipfile").get("requires") or {}
    return req.get("python_full_version") or req.get("python_version")


NODE_CURRENT_LTS = 24
PYTHON_NEWEST_STABLE = (3, 14)        # une matrice de CI peut lister une version pas encore stable (3.15-dev…) : on ne la propose pas


def _versions_in(text: str, tool: str) -> list[tuple[int, ...]]:
    """Versions « X.Y » (Python) ou « X » (Node) d'un fragment de CI ; ignore les expressions ${{ }}, pypy, nightly, lts/*."""
    text = re.sub(r"\$\{\{.*?\}\}", " ", text)
    out: list[tuple[int, ...]] = []
    for m in re.finditer(r"(?<![\w.-])(\d+)(?:\.(\d+|x))?(?:\.(?:\d+|x))?(?![\w.-])", re.sub(r"pypy[-\d.]*|nightly|\bdev\b", " ", text)):
        major, minor = int(m.group(1)), m.group(2)
        if tool == "python" and major == 3 and minor and minor != "x":
            out.append((3, int(minor)))
        elif tool == "node" and 8 <= major <= 40:
            out.append((major,))
    return out


NODE_OLDEST_FROM_CI = 20            # une CI n'est à jour que si le projet l'est : une version en fin de vie y est pire que le défaut
PYTHON_OLDEST_FROM_CI = (3, 10)     # (mesuré : Node 16 lu dans une CI ancienne cassait l'installation d'un dépôt qui démarrait avec la LTS)


def _within_supported(vs: list[tuple[int, ...]], tool: str, from_ci: bool = False) -> list[tuple[int, ...]]:
    """Versions que zero sait fournir : Node au plus la LTS actuelle, Python au plus la dernière version stable ; pour la CI
    seulement, on écarte aussi les versions en fin de vie (le Dockerfile, lui, décrit ce qui est réellement livré)."""
    if tool == "node":
        return [v for v in vs if (NODE_OLDEST_FROM_CI if from_ci else 0) <= v[0] <= NODE_CURRENT_LTS]
    return [v for v in vs if (PYTHON_OLDEST_FROM_CI if from_ci else (0, 0)) <= v <= PYTHON_NEWEST_STABLE]


def _ci_files(root: Path) -> list[Path]:
    files = sorted((root / ".github" / "workflows").glob("*.y*ml")) if (root / ".github" / "workflows").is_dir() else []
    return files + [root / n for n in (".gitlab-ci.yml", ".travis.yml") if (root / n).is_file()]


def runtime_hint(root: Path, tool: str) -> tuple[str, str] | None:
    """Version de Python ou de Node que le projet utilise réellement, quand rien ne la fixe : `FROM python:3.9` / `FROM node:20`
    d'un Dockerfile d'abord (c'est ce qui est livré), puis la CI (GitHub Actions `python-version` / `node-version`, GitLab `image:`,
    Travis `python:` / `node_js:`). Une matrice de versions liste celles que le projet déclare supporter : on prend la plus
    récente (Node : au plus la LTS actuelle). Rien si aucune version claire. Retourne (version, source)."""
    if os.environ.get("ZERO_NO_RUNTIME_HINT"):          # désactivation (comparaison avec/sans, ou pour forcer le comportement d'avant)
        return None
    key = "python" if tool == "python" else "node"
    docker = re.compile(rf"(?im)^\s*FROM\s+(?:--\S+\s+)?(?:docker\.io/(?:library/)?)?{key}:(\d+(?:\.\d+)?)")
    for name in ("Dockerfile", "dockerfile", "Containerfile"):
        found = [m.group(1) for m in docker.finditer(read(root, name) or "")]
        vs = _versions_in(" ".join(found), tool) if tool == "python" else _versions_in(" ".join(found), "node")
        vs = _within_supported(vs, tool)
        if vs:
            best = max(vs)
            return (".".join(map(str, best)), name)
    for f in _ci_files(root):
        text = f.read_text(errors="ignore")
        vs: list[tuple[int, ...]] = []
        if f.name == ".travis.yml":
            for m in re.finditer(rf"(?m)^{'python' if tool == 'python' else 'node_js'}:\s*(.*(?:\n\s*-.*)*)", text):
                vs += _versions_in(m.group(1), tool)
        elif f.name == ".gitlab-ci.yml":
            vs += _versions_in(" ".join(re.findall(rf"(?m)^\s*image:\s*{key}:(\d+(?:\.\d+)?)", text)), tool)
        else:
            for m in re.finditer(rf"(?m)^[ \t]*{key}-version:[ \t]*(.*(?:\n[ \t]+-[ \t]*.*)*)", text):
                vs += _versions_in(m.group(1), tool)
        vs = _within_supported(vs, tool, from_ci=True)
        if vs:
            return (".".join(map(str, max(vs))), str(f.relative_to(root)))
    return None


def py_version(root: Path, pyproject: dict) -> tuple[str | None, str]:
    for src, val in (
        (".python-version", read(root, ".python-version")),
        ("runtime.txt", (read(root, "runtime.txt") or "").replace("python-", "") or None),
        (".tool-versions", tool_versions(root, "python")),
        ("pyproject requires-python", (pyproject.get("project") or {}).get("requires-python")),
        ("Pipfile requires", pipfile_python(root)),
    ):
        lines = [ln.strip() for ln in (val or "").splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if lines:                                   # ignore les lignes de commentaire (ex. Heroku : « # The Python version… »)
            return lines[0], src
    hint = runtime_hint(root, "python")
    if hint:
        return hint[0], f"déduit de {hint[1]} (aucune version déclarée)"
    return None, "défaut (uv)"


def venv_dir(root: Path) -> Path:
    h = hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:8]
    return zero_home() / "envs" / f"{root.resolve().name}-{h}"



# CLIs de framework qui exigent un argument/une cible : sans eux elles affichent l'aide et sortent.
NEEDS_ARGS_CLIS = {"flask", "django-admin", "celery", "uvicorn", "gunicorn", "fastapi", "pytest", "sphinx-build",
                   "alembic", "black", "ruff", "pip", "tox", "nox", "twine", "mkdocs", "pelican"}


def usable_script(name: str | None) -> str | None:
    """Écarte les scripts console qui n'affichent que leur aide faute d'argument."""
    return None if name and name.lower() in NEEDS_ARGS_CLIS else name


def console_script(root: Path) -> str | None:
    """Premier console_script déclaré dans setup.py / setup.cfg."""
    for name in ("setup.py", "setup.cfg"):
        t = read(root, name) or ""
        m = re.search(r"console_scripts['\"]?\s*[:=]\s*\[?\s*['\"]?\s*([\w.-]+)\s*=", t) \
            or re.search(r"console_scripts\s*=\s*\n\s+([\w.-]+)\s*=", t)
        if m:
            return m.group(1)
    return None


WEB_ENTRIES = ("main.py", "app.py", "app/main.py", "src/main.py", "src/app.py", "api.py", "server.py", "wsgi.py", "backend/main.py")
SCRIPT_ENTRIES = ("main.py", "app.py", "run.py", "server.py", "launch.py", "webui.py", "start.py", "bot.py", "__main__.py")


def python_entry(root: Path, text: str) -> tuple[str | None, list[str]]:
    """Devine la commande principale d'un projet Python sans script déclaré."""
    for rel in ("streamlit_app.py", "app.py", "main.py"):
        if has_dep(text, "streamlit") and (root / rel).is_file():
            return f"streamlit run {rel}", []
    for rel in WEB_ENTRIES:
        f = root / rel
        if not f.is_file():
            continue
        src = f.read_text(errors="ignore")
        if "__main__" in src:
            return f"python {rel}", []
        module = rel[:-3].replace("/", ".")
        if m := re.search(r"^(\w+)\s*(?::[^=]+)?=\s*FastAPI\(", src, re.M):
            extra = [] if has_dep(text, "uvicorn", "fastapi[standard]") else ["uvicorn"]
            return f"uvicorn {module}:{m.group(1)}", extra
        if m := re.search(r"^(\w+)\s*=\s*Flask\(", src, re.M):
            return f"flask --app {module}:{m.group(1)} run", []
    for cand in SCRIPT_ENTRIES:
        if (root / cand).is_file():
            return f"python {cand}", []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "__main__.py").is_file() and not d.name.startswith("."):
            return f"python -m {d.name}", []
    return None, []


MANAGE_SKIP = {"node_modules", "venv", ".venv", "env", "site-packages", "build", "dist", "docs", "doc", "tests", "test", "examples"}


def find_manage_py(root: Path) -> str | None:
    """`manage.py` à la racine, sinon dans UN SEUL sous-dossier direct (Django/Flask-Script rangent souvent le projet dans
    `<projet>/manage.py` ou `src/manage.py`) : chemin relatif à la racine. Un sous-dossier n'est retenu que si le fichier
    ressemble à Django ou Flask-Script ; plusieurs candidats → None (on ne devine pas)."""
    if (root / "manage.py").is_file():
        return "manage.py"
    found = []
    try:
        subs = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".") and d.name not in MANAGE_SKIP)
    except OSError:
        return None
    for d in subs:
        f = d / "manage.py"
        if f.is_file() and re.search(r"django|flask_script|flask_migrate|flask\.cli", f.read_text(errors="ignore"), re.I):
            found.append(f"{d.name}/manage.py")
    return found[0] if len(found) == 1 else None


def django_collectstatic(root: Path, deps: str) -> bool:
    """Django avec STATIC_ROOT défini : `collectstatic` est nécessaire (sinon « Missing staticfiles manifest entry », HTTP 500).

    Le buildpack Heroku le lançait à la construction. Sans STATIC_ROOT la commande échouerait : on ne la lance pas."""
    mp = find_manage_py(root)
    if not mp or "django" not in deps:
        return False
    base = (root / mp).parent
    for f in list(base.glob("*/settings*.py")) + list(base.glob("*/settings/*.py")) + list(base.glob("settings*.py")):
        try:
            if re.search(r"^\s*STATIC_ROOT\s*=", f.read_text(errors="ignore"), re.M):
                return True
        except OSError:
            continue
    return False


@dataclass
class _PyManifest:
    """Ce qui déclare les dépendances d'un projet Python : requirements (ou une variante matérielle), pyproject, setup.py, Pipfile."""
    req_file: str | None
    variant_note: str | None
    has_pp: bool
    has_setup: bool
    pipfile: list[str]

    @property
    def has_req(self) -> bool:
        return self.req_file is not None


def _python_manifest(root: Path) -> _PyManifest | None:
    req_file = requirements_file(root)
    variant_note = None
    if req_file is None:                                  # dépendances rangées par variante matérielle ?
        picked = gpumod.pick_requirements_variant(root)
        if picked:
            req_file, variant_note = picked
    has_req = req_file is not None
    has_pp = (root / "pyproject.toml").is_file()
    has_setup = (root / "setup.py").is_file()
    pipfile = pipfile_specs(root) if (root / "Pipfile").is_file() and not has_req else []
    if not (has_req or has_pp or has_setup or pipfile):
        return None
    return _PyManifest(req_file, variant_note, has_pp, has_setup, pipfile)


def _python_install_steps(root: Path, m: _PyManifest, pyflag: str, pip: str) -> tuple[list[str], list[str]]:
    """(étapes d'installation, étapes ignorables si elles échouent) : `uv sync` si `uv.lock`, sinon venv + requirements ou Pipfile + `-e .`."""
    venv = venv_dir(root)
    if (root / "uv.lock").is_file():
        return [f"uv sync --frozen{pyflag}"], []
    steps = [f"[ -d {q(str(venv))} ] || uv venv{pyflag} {q(str(venv))}"]
    soft: list[str] = []
    if m.has_req:
        steps.append(f"{pip} -r {q(m.req_file)}")
    elif m.pipfile:
        steps.append(f"{pip} " + " ".join(q(sp) for sp in m.pipfile))
        if m.has_pp or m.has_setup:
            soft.append(steps[-1])          # versions du lock trop vieilles ? setup.py/pyproject déclare ses dépendances
    if m.has_pp or m.has_setup:
        steps.append(f"{pip} -e .")
    return steps, soft


def _python_run(root: Path, pp: dict, text: str) -> tuple[str | None, list[str], str | None]:
    """(commande, paquets nécessaires à une commande devinée, manage.py) : script console, sinon `manage.py runserver`, sinon un fichier d'entrée."""
    scripts = (pp.get("project") or {}).get("scripts") or (pp.get("tool", {}).get("poetry", {}) or {}).get("scripts") or {}
    run = usable_script(next(iter(scripts)) if scripts else console_script(root))
    extra: list[str] = []
    manage = find_manage_py(root)
    if not run and manage:
        run = f"python {manage} runserver"
    if not run:
        run, extra = python_entry(root, text)
    return run, extra, manage


def detect_python(root: Path, version_override: str | None = None) -> Plan | None:
    m = _python_manifest(root)
    if m is None:
        return None
    pp = toml(root, "pyproject.toml")
    version, source = py_version(root, pp)
    if version_override:
        version, source = version_override, "correctif automatique"
    pyflag = f" --python {q(version)}" if version else ""
    venv = venv_dir(root)
    text = dep_text(root)
    if m.variant_note and m.req_file:
        text += "\n" + read(root, m.req_file).lower()
    ai = [lib for lib in AI_LIBS if has_dep(text, lib)]
    backend = " --torch-backend=auto" if has_dep(text, "torch", "torchvision", "torchaudio") else ""
    pip = f"uv pip install --python {q(str(venv / 'bin' / 'python'))}{backend}"

    steps, soft = _python_install_steps(root, m, pyflag, pip)
    run, extra, manage = _python_run(root, pp, text)
    steps += [f"{pip} {pkg}" for pkg in extra]       # paquets nécessaires à la commande devinée
    optional: list[str] = []
    if django_collectstatic(root, text):
        steps.append(f"{q(str(venv_dir(root) / 'bin' / 'python'))} {manage} collectstatic --noinput")
        optional.append(steps[-1])          # utile mais pas vital : une base absente ou un réglage manquant ne doit pas tout bloquer
    plan = Plan("python", version, source, steps, run, ["runtime via uv"], pm="uv", ai_libs=ai, soft_steps=soft, optional_steps=optional)
    if m.variant_note:
        plan.notes.append(m.variant_note + " (changez avec --cmd ou installez à la main une autre variante)")
    return plan


# ───────────────────────────── Rust ─────────────────────────────

def _pkg_bins(d: Path, cargo: dict) -> tuple[str | None, list[str], str | None]:
    """(nom du paquet, binaires, default-run) d'un dossier de crate."""
    pkg = cargo.get("package") or {}
    name = pkg.get("name")
    declared = [b for b in cargo.get("bin", []) if isinstance(b, dict) and b.get("name")]
    bins = [b["name"] for b in declared]
    declared_paths = {b.get("path") for b in declared}
    declares_main = any(b.get("path") == "src/main.rs" for b in declared)
    if name and (d / "src" / "main.rs").is_file() and not declares_main:
        bins.append(name)           # sinon le binaire porte le nom du [[bin]] (ex. paquet fd-find → binaire fd)
    if (d / "src" / "bin").is_dir():
        bins += [f.stem for f in (d / "src" / "bin").glob("*.rs") if f"src/bin/{f.name}" not in declared_paths]
        bins += [x.name for x in (d / "src" / "bin").iterdir() if (x / "main.rs").is_file()]
    return name, sorted(set(bins)), pkg.get("default-run")


def safe_glob(root: Path, pattern: str) -> list[Path]:
    """`root.glob` qui ne plante pas sur un motif vide, absolu ou invalide (« . », « /x », « »)."""
    pattern = (pattern or "").strip()
    if pattern in ("", ".", "./"):
        return [root]
    if pattern.startswith("./"):
        pattern = pattern[2:]
    try:
        return sorted(root.glob(pattern))
    except (ValueError, IndexError, NotImplementedError, OSError):
        return []


def _members(root: Path, cargo: dict) -> list[Path]:
    out: list[Path] = []
    ws = cargo.get("workspace") or {}
    for pat in ws.get("members", []):
        if isinstance(pat, str):
            out += [m for m in safe_glob(root, pat) if (m / "Cargo.toml").is_file()]
    excluded = {str(root / e) for e in ws.get("exclude", [])}
    return [m for m in out if str(m) not in excluded]


def _rust_toolchain(root: Path) -> tuple[str, str]:
    """Canal Rust : `rust-toolchain.toml`, sinon l'ancien fichier `rust-toolchain`, sinon stable."""
    tc = toml(root, "rust-toolchain.toml").get("toolchain", {}).get("channel")
    legacy = read(root, "rust-toolchain")
    if tc:
        return tc, "rust-toolchain.toml"
    if legacy and not legacy.startswith("["):
        return legacy.splitlines()[0].strip(), "rust-toolchain"
    return "stable", "défaut"


def _rust_run_from_bins(name: str | None, bins: list[str], default_run: str | None) -> tuple[str | None, list[str], list[str]]:
    """(commande, choix, notes) pour un paquet qui a des binaires : l'unique, `default-run`, celui qui porte le nom du paquet,
    l'unique « serveur » ; sinon les propose tous."""
    servers = [b for b in bins if "server" in b or "serve" in b]
    if len(bins) == 1 or default_run:
        return "cargo run --release", [], []
    if name in bins:
        return f"cargo run --release --bin {name}", [], []
    if len(servers) == 1:
        return f"cargo run --release --bin {servers[0]}", [], []
    return None, [f"cargo run --release --bin {b}" for b in bins], [f"plusieurs binaires ({', '.join(bins)}) : précisez avec --cmd"]


def _rust_run_from_workspace(root: Path, cargo: dict) -> tuple[str | None, list[str], list[str]]:
    """(commande, choix, notes) pour un workspace : l'unique crate exécutable, ou la seule au nom usuel (dossier, cli, app, server, main)."""
    cands = []
    for m in _members(root, cargo):
        mname, mbins, _ = _pkg_bins(m, toml(m, "Cargo.toml"))
        if mname and mbins:
            cands.append((mname, mbins))
    preferred = {root.resolve().name, "cli", "app", "server", "main"}
    pick = [c for c in cands if c[0] in preferred]
    if len(cands) == 1 or len(pick) == 1:
        mname, mbins = (pick or cands)[0]
        return f"cargo run --release -p {mname}" + (f" --bin {mbins[0]}" if len(mbins) > 1 else ""), [], []
    if cands:
        return None, [f"cargo run --release -p {c[0]}" for c in cands], [
            f"workspace : {len(cands)} crates exécutables ({', '.join(c[0] for c in cands[:6])}"
            f"{'…' if len(cands) > 6 else ''}) : précisez avec --cmd"]
    return None, [], []


def detect_rust(root: Path) -> Plan | None:
    if not (root / "Cargo.toml").is_file():
        return None
    version, source = _rust_toolchain(root)
    cargo = toml(root, "Cargo.toml")
    if not HAS_TOML or not cargo:      # pas de parseur TOML (Python < 3.11) : ancien comportement
        return Plan("rust", version, source, ["cargo build --release"], "cargo run --release", [], pm="cargo")
    run, choices, notes = None, [], []
    name, bins, default_run = _pkg_bins(root, cargo)
    if bins:
        run, choices, notes = _rust_run_from_bins(name, bins, default_run)
    elif "workspace" in cargo:
        run, choices, notes = _rust_run_from_workspace(root, cargo)
    if run is None and not choices:
        notes.append("bibliothèque : aucune cible binaire (src/main.rs, [[bin]])")
    return Plan("rust", version, source, ["cargo build --release"], run, notes, pm="cargo", choices=choices)


# ───────────────────────────── Go ─────────────────────────────

KNOWN_BUILD_TAGS = set("""aix android darwin dragonfly freebsd hurd illumos ios js linux nacl netbsd openbsd plan9 solaris
wasip1 windows zos 386 amd64 amd64p32 arm armbe arm64 arm64be loong64 mips mipsle mips64 mips64le mips64p32
mips64p32le ppc ppc64 ppc64le riscv riscv64 s390 s390x sparc sparc64 wasm cgo unix gc gccgo""".split())


def _excluded_by_build_tags(text: str) -> bool:
    """Vrai si le fichier exige une étiquette de build personnalisée (ignore, tools, integration…) :
    il n'est alors pas compilé par défaut et ne définit pas le binaire."""
    header = text.split("\npackage ", 1)[0]
    exprs = re.findall(r"^//go:build\s+(.+)$", header, re.M) or re.findall(r"^// \+build\s+(.+)$", header, re.M)
    for expr in exprs:
        for m in re.finditer(r"(!?)([A-Za-z_][\w.]*)", expr):
            neg, tag = m.groups()
            if not neg and tag not in KNOWN_BUILD_TAGS and not re.fullmatch(r"go\d+\.\d+", tag):
                return True
    return False


def _has_main_package(directory: Path) -> bool:
    for f in sorted(directory.glob("*.go")):
        if f.name.endswith("_test.go"):
            continue
        text = f.read_text(errors="ignore")
        if _excluded_by_build_tags(text):
            continue        # exclu du paquet par défaut (ex. build.go de syncthing) : ne définit pas le binaire
        if re.search(r"^package\s+main\b", text, re.M):
            return True
    return False


def _go_version(root: Path, gomod: str) -> tuple[str | None, str]:
    """Version de Go : `.go-version`, `.tool-versions`, directive `toolchain` puis `go` de go.mod, sinon la dernière stable."""
    m_tc = re.search(r"^toolchain\s+go([\d.]+)", gomod, re.M)
    m_go = re.search(r"^go\s+([\d.]+)", gomod, re.M)
    for src, val in (
        (".go-version", read(root, ".go-version")),
        (".tool-versions", tool_versions(root, "go")),
        ("go.mod toolchain", m_tc.group(1) if m_tc else None),
        ("go.mod go", m_go.group(1) if m_go else None),
    ):
        if val:
            return val.lstrip("go").strip(), src
    return None, "défaut (dernière stable)"


def _go_run_from_cmd_dir(root: Path, gomod: str) -> tuple[str | None, list[str], list[str]]:
    """(commande, choix, notes) quand la racine n'est pas un paquet `main` : l'unique `cmd/*`, ou celui qui porte le nom du dépôt ou du module."""
    cmds = sorted(d for d in (root / "cmd").iterdir() if d.is_dir() and _has_main_package(d)) if (root / "cmd").is_dir() else []
    mod = re.search(r"^module\s+(\S+)", gomod, re.M)
    parts = [x for x in (mod.group(1).split("/") if mod else []) if not re.fullmatch(r"v\d+", x)]
    wanted = {root.resolve().name, parts[-1] if parts else ""}
    match = [d for d in cmds if d.name in wanted]
    if len(cmds) == 1:
        return f"go run ./cmd/{cmds[0].name}", [], []
    if match:
        return f"go run ./cmd/{match[0].name}", [], []
    if cmds:
        return None, [f"go run ./cmd/{d.name}" for d in cmds], [
            f"plusieurs binaires dans cmd/ ({', '.join(d.name for d in cmds)}) : précisez avec --cmd"]
    return None, [], []


def detect_go(root: Path) -> Plan | None:
    gomod = read(root, "go.mod")
    if gomod is None:
        return None
    version, source = _go_version(root, gomod)
    if _has_main_package(root):
        run, choices, notes = "go run .", [], []
    else:
        run, choices, notes = _go_run_from_cmd_dir(root, gomod)
    return Plan("go", version, source, ["go mod download"], run, notes, pm="go", choices=choices)


DETECTORS = [detect_node, detect_python, detect_rust, detect_go]


# ───────────────────────────── Procfile ─────────────────────────────

def parse_procfile(root: Path) -> dict[str, str]:
    procs: dict[str, str] = {}
    for line in (read(root, "Procfile") or "").splitlines():
        m = re.match(r"^([\w-]+):\s*(.+)$", line.strip())
        if m and not line.lstrip().startswith("#"):
            procs[m.group(1)] = m.group(2)
    return procs


def missing_local_exec(root: Path, procs: dict[str, str]) -> str | None:
    """Premier exécutable relatif (`bin/x`, `./x`) d'un Procfile qui n'existe pas dans le dépôt, sinon None.
    Ex. le Procfile d'etcd (goreman) vise `bin/etcd`, qui n'existe qu'après compilation."""
    import shlex
    for cmd in procs.values():
        try:
            words = shlex.split(cmd)
        except ValueError:
            continue
        words = [w for w in words if not re.match(r"^\w+=", w)]      # ignore les affectations FOO=bar
        if not words:
            continue
        exe = words[0]
        if "/" in exe and not exe.startswith(("/", "$", "~")) and not (root / exe).exists():
            return exe
    return None


FOREIGN = [("Ruby", "Gemfile"), ("PHP", "composer.json"), ("Java", "pom.xml"), ("Java/Kotlin", "build.gradle"),
           ("Java/Kotlin", "build.gradle.kts"), ("Elixir", "mix.exs"), ("C/C++", "CMakeLists.txt")]


# Commande habituelle à lancer À LA MAIN pour chaque écosystème non géré (indication générale, pas une garantie pour ce dépôt).
FOREIGN_HINTS = {
    "Ruby": "bundle install, puis souvent `bin/rails server` (Rails) ou `bundle exec rackup` ; voir le README",
    "PHP": "composer install, puis `php artisan serve` (Laravel) ou `php -S localhost:8000 -t public` ; voir le README",
    "Java": "souvent `./mvnw spring-boot:run` (Spring Boot) ou `mvn package` puis `java -jar target/*.jar` ; voir le README",
    "Java/Kotlin": "souvent `./gradlew bootRun` (Spring Boot) ou `./gradlew run` ; voir le README",
    "Elixir": "mix deps.get, puis `mix phx.server` (Phoenix) ou `mix run` ; voir le README",
    "C/C++": "cmake -S . -B build && cmake --build build, puis lancer l'exécutable produit ; voir le README",
    ".NET": "dotnet run ; voir le README",
}


def foreign_message(foreign: str) -> str:
    """« écosystème non supporté : Ruby (Gemfile) — … À la main : … » (le nom avant la parenthèse sert de clé)."""
    hint = FOREIGN_HINTS.get(foreign.split(" (")[0])
    return f"écosystème non supporté : {foreign} — zero gère Node, Python, Rust et Go" + (f". À la main : {hint}" if hint else "")


def foreign_ecosystem(root: Path) -> str | None:
    for name, manifest in FOREIGN:
        if (root / manifest).is_file():
            return f"{name} ({manifest})"
    if any(root.glob("*.csproj")) or any(root.glob("*.sln")):
        return ".NET"
    return None


LAUNCH_NOISE = re.compile(r"[|;<>]|&&|\$|\.\.\.|\byour\b|path/to|<|>|\bxxx\b", re.I)
NOT_LAUNCH_FILES = ("setup.py", "conftest.py", "manage.py")
UTILITY_DIRS = {"scripts", "script", "test", "tests", "test-suite", "testing", "tools", "utils", "util", "examples", "example", "docs", "doc",
                "migrations", "ci", "bench", "benchmark", "benchmarks", "hack", "dev-tools", "tasks"}
UTILITY_WORDS = re.compile(r"(?:^|[-_.])(?:reset|migrate|migration|seed|test|tests|setup|install|build|lint|format|clean|generate|convert|export|import|"
                           r"check|manifest|bench|benchmark|release|deploy|backup|restore|init|admin|update|upgrade|publish|verify|validate|fix)(?:[-_.]|$)", re.I)


def _is_utility_script(ref: str) -> bool:
    """Un script d'outillage (tests, migration, remise à zéro…) n'est pas « la commande qui lance l'application »."""
    parts = Path(ref.replace(".", "/") if not re.search(r"\.\w+$", ref) else ref).parts
    return bool(set(parts[:-1]) & UTILITY_DIRS) or bool(UTILITY_WORDS.search(Path(ref).stem if "/" in ref or "." in ref else ref))


def _py_target_exists(root: Path, ref: str) -> bool:
    ref = ref.split(":")[0]
    if ref.startswith(("/", "..")) or ".." in Path(ref).parts:
        return False
    base = ref.replace(".", "/") if not ref.endswith(".py") else ref[:-3]
    return (root / (base + ".py")).is_file() or (root / base / "__init__.py").is_file()


def _readme_line_to_command(root: Path, line: str, lang: str) -> str | None:
    """Une ligne de bloc de code du README → commande de lancement VÉRIFIABLE (le fichier cité existe, l'outil est déclaré), sinon None."""
    line = re.sub(r"^\s*(?:\$|>)\s*", "", line).split(" #")[0].strip()
    if not line or line.startswith("#") or LAUNCH_NOISE.search(line):
        return None
    deps = dep_text(root)
    if lang == "python":
        if (m := re.match(r"python3?\s+(?:-u\s+)?([\w./-]+\.py)(?:\s+[\w=./:-]+)*$", line)):
            f = m.group(1)
            if Path(f).name not in NOT_LAUNCH_FILES and not _is_utility_script(f) and _py_target_exists(root, f):
                return line
        if (m := re.match(r"python3?\s+-m\s+([\w.]+)(?:\s+[\w=./:-]+)*$", line)):
            if m.group(1) not in ("pip", "venv", "pytest", "unittest", "http.server") and not _is_utility_script(m.group(1).replace(".", "/") + ".py") \
                    and _py_target_exists(root, m.group(1)):
                return line
        if (m := re.match(r"(uvicorn|gunicorn|hypercorn)\s+([\w.]+:[\w.]+)(?:\s+[\w=./:-]+)*$", line)):
            if has_dep(deps, m.group(1)) and _py_target_exists(root, m.group(2)):
                return line
        if (m := re.match(r"streamlit\s+run\s+([\w./-]+\.py)$", line)):
            if has_dep(deps, "streamlit") and (root / m.group(1)).is_file():
                return line
        if re.match(r"flask(?:\s+--app\s+[\w.:]+)?\s+run(?:\s+--[\w-]+(?:[ =][\w.:]+)?)*$", line) and has_dep(deps, "flask"):
            app = re.search(r"--app\s+([\w.:]+)", line)
            if (app and _py_target_exists(root, app.group(1))) or (root / "app.py").is_file() or (root / "wsgi.py").is_file():
                return line
    if lang == "node" and (m := re.match(r"node\s+([\w./-]+\.(?:js|mjs|cjs))$", line)) \
            and not _is_utility_script(m.group(1)) and (root / m.group(1)).is_file():
        return line
    return None


def readme_run(root: Path, lang: str) -> tuple[str, str] | None:
    """Dernier recours après le Makefile : la première commande de lancement d'un bloc de code du README qui se vérifie sur le dépôt
    (`python app.py` avec app.py présent, `uvicorn main:app` avec uvicorn déclaré et main.py présent, `streamlit run`, `flask run`, `node server.js`).
    Une commande avec des placeholders, des pipes ou un `cd` n'est jamais retenue. → (commande, ligne du README) ou None."""
    for line in _readme_code_lines(root):
        if (cmd := _readme_line_to_command(root, line, lang)):
            return cmd, line.strip()
    return None


def detect_all(root: Path) -> Plan:
    plans = [p for d in DETECTORS if (p := d(root))]
    if not plans:
        die(foreign_message(f) if (f := foreign_ecosystem(root)) else "aucun projet Node, Python, Rust ou Go détecté")
    primary = next((p for p in plans if p.run), plans[0])
    foreign = foreign_ecosystem(root)
    if foreign and primary.lang == "node":
        # package.json sert alors surtout au front : lancer `npm run dev` seul serait trompeur
        die(f"{foreign_message(foreign)} (le package.json n'est que l'outillage front)")
    if foreign:
        primary.notes.append(f"écosystème {foreign} aussi présent : non géré")
    for other in plans:
        if other is not primary:
            primary.notes.append(f"{other.lang} aussi détecté (ignoré : un seul langage principal)")
    procs = parse_procfile(root)
    missing = missing_local_exec(root, procs)
    if missing:
        primary.notes.append(f"Procfile ignoré : `{missing}` n'existe pas dans le dépôt (à compiler d'abord ?)")
        procs = {}
    release = procs.pop("release", None)
    if release:
        primary.install.append(release)
        primary.notes.append("Procfile : phase `release` exécutée après l'installation")
    if procs:
        primary.processes = procs
        primary.run = procs.get("web") or next(iter(procs.values()))
        primary.notes.append(f"Procfile : {', '.join(procs)}")
    if primary.ai_libs:
        primary.notes.append(f"projet IA/GPU : {', '.join(primary.ai_libs)}")
    return primary


# ───────────────────────────── monorepos ─────────────────────────────

class AmbiguousProject(ZeroError):
    """Plusieurs sous-projets exécutables : l'utilisateur doit choisir avec --project."""

    def __init__(self, candidates: list[str], multistack: bool = False):
        self.candidates = candidates
        self.multistack = multistack
        hint = " ou `zero --all` pour tout lancer ensemble" if multistack else ""
        super().__init__(
            "monorepo : plusieurs projets exécutables (" + ", ".join(candidates)
            + ") — choisissez avec `zero run --project <dossier>`" + hint
        )


MANIFEST_FILES = {"package.json", "pyproject.toml", "requirements.txt", "setup.py", "Pipfile", "Cargo.toml", "go.mod"}
SKIP_SCAN = {"node_modules", "target", "vendor", "dist", "build", "venv", "env", "docs", "doc", "test", "tests",
             "testdata", "fixtures", "examples", "example", "samples", "third_party", "site-packages",
             "template", "templates", "scaffold", "boilerplate"}


def find_projects(root: Path, max_depth: int = 2) -> list[str]:
    """Sous-dossiers (profondeur ≤ 2) contenant un projet avec une commande principale."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        depth = len(d.relative_to(root).parts)
        dirnames[:] = [x for x in dirnames if not x.startswith(".") and x not in SKIP_SCAN] if depth < max_depth else []
        if depth and MANIFEST_FILES & set(filenames):
            try:
                if detect_all(d).run:
                    found.append(str(d.relative_to(root)))
            except ZeroError:
                continue
    return sorted(found)


def is_js_workspace(root: Path) -> bool:
    if any((root / f).is_file() for f in ("pnpm-workspace.yaml", "lerna.json", "nx.json", "turbo.json", "rush.json")):
        return True
    try:
        return bool(json.loads((root / "package.json").read_text()).get("workspaces"))
    except Exception:
        return False


GENERIC_NAMES = {"utils", "util", "common", "helpers", "helper", "config", "configs", "lib", "libs", "tools", "models",
                 "model", "data", "test", "tests", "src", "app", "core", "main", "base", "settings", "constants", "types"}


def _imported_modules(source: str) -> list[str]:
    """Noms de modules importés par un script (`import a.b`, `from a.b import c`) ; les imports relatifs et un script illisible donnent rien."""
    import ast
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def script_imports(root: Path) -> tuple[list[str], list[Path], list[str]]:
    """Modules importés par les scripts Python de la racine (hors stdlib et modules locaux), les scripts lus, et les
    modules propres à Python 2 rencontrés (jamais installés : ce ne sont pas des paquets PyPI)."""
    from .recovery import PY2_MODULES
    scripts = sorted(p for p in root.glob("*.py") if p.is_file() and p.stat().st_size < 400_000)
    local = {p.stem for p in scripts} | {d.name for d in root.iterdir() if d.is_dir()}
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    found: set[str] = set()
    py2: set[str] = set()
    for sc in scripts:
        for name in _imported_modules(sc.read_text(errors="ignore")):
            top = name.split(".")[0]
            if top in PY2_MODULES:
                py2.add(top)
            elif top and top not in stdlib and top not in local and top.lower() not in GENERIC_NAMES:
                found.add(top)
    return sorted(found), scripts, sorted(py2)


def script_entry(root: Path, scripts: list[Path]) -> tuple[str | None, list[str]]:
    """Point d'entrée d'un dépôt de scripts : garde `__main__` unique, sinon script que personne n'importe, sinon choix."""
    texts = {p.name: p.read_text(errors="ignore") for p in scripts}
    stems = {p.stem for p in scripts}
    imported = {s for t in texts.values() for s in stems if re.search(rf"^\s*(?:from|import)\s+{re.escape(s)}\b", t, re.M)}
    skip = lambda n: n.startswith(("test_", "conftest")) or n in ("setup.py", "__init__.py")
    guarded = [n for n, t in texts.items() if not skip(n) and re.search(r"if\s+__name__\s*==\s*[\"']__main__[\"']", t)]
    cands = guarded or [n for n in texts if not skip(n) and Path(n).stem not in imported]
    return (cands[0], cands) if len(cands) == 1 else (None, cands)


def detect_scripts(root: Path) -> Plan | None:
    """Dernier recours (§2) : scripts Python à la racine sans aucun manifeste → dépendances déduites des `import`."""
    from .recovery import PY_IMPORT_MAP        # import tardif : recovery importe ce module
    mods, scripts, py2 = script_imports(root)
    if not scripts:
        return None
    pkgs = sorted({PY_IMPORT_MAP.get(m, m.replace("_", "-")) for m in mods})
    venv = venv_dir(root)
    backend = " --torch-backend=auto" if any(m in ("torch", "torchvision", "torchaudio") for m in mods) else ""
    steps = [f"[ -d {q(str(venv))} ] || uv venv {q(str(venv))}"]
    if pkgs:
        steps.append(f"uv pip install --python {q(str(venv / 'bin' / 'python'))}{backend} " + " ".join(q(x) for x in pkgs))
    entry, cands = script_entry(root, scripts)
    notes = ["runtime via uv", "aucun manifeste : dépendances DÉDUITES des import des scripts — "
             + (", ".join(pkgs) if pkgs else "aucune") + " (nom PyPI supposé égal au nom du module sauf table connue)"]
    if py2:
        notes.append("imports propres à Python 2 (" + ", ".join(py2) + ") : projet probablement en Python 2, non supporté")
    plan = Plan("python", None, "défaut (uv)", steps, f"python {q(entry)}" if entry else None, notes, pm="uv")
    if not entry:
        plan.choices = [f"python {q(c)}" for c in cands[:8]]
    return plan


DOCKER_FILES = ("Dockerfile", "dockerfile", "Containerfile", "docker/Dockerfile", "deploy/Dockerfile", "build/Dockerfile")
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def _choice_name(choice: str) -> str:
    """`cargo run --release --bin x` / `-p x` / `go run ./cmd/x` / `python x.py` → `x` (ou `x.py`)."""
    m = re.search(r"(?:--bin|-p)\s+(\S+)|\./cmd/(\S+)|python\s+'?([^\s']+)", choice)
    return next((g for g in m.groups() if g), "") if m else ""


def _docker_command_lines(root: Path) -> list[str]:
    """Lignes `ENTRYPOINT`/`CMD` des Dockerfile et `command:`/`entrypoint:` des fichiers compose."""
    lines: list[str] = []
    for f in DOCKER_FILES:
        lines += [l for l in (read(root, f) or "").splitlines() if re.match(r"\s*(ENTRYPOINT|CMD)\b", l)]
    for f in COMPOSE_FILES:
        lines += [l for l in (read(root, f) or "").splitlines() if re.match(r"\s*(command|entrypoint)\s*:", l)]
    return lines


def _readme_code_blocks(root: Path) -> list[list[str]]:
    """Blocs de code du premier README trouvé (blocs ``` ou, à défaut, groupes de lignes indentées), 2000 lignes au plus au total."""
    for f in ("README.md", "README.rst", "readme.md", "README"):
        text = read(root, f) or ""
        if text:
            raw = (re.findall(r"```[^\n]*\n(.*?)```", text, re.S) or re.findall(r"~~~[^\n]*\n(.*?)~~~", text, re.S)
                   or re.findall(r"(?m)((?:^(?: {4}|\t).+\n?)+)", text))
            out, n = [], 0
            for b in raw:
                lines = [re.sub(r"^(?: {4}|\t)", "", l) for l in str(b).splitlines()][: max(0, 2000 - n)]
                n += len(lines)
                out.append(lines)
            return out
    return []


def _readme_code_lines(root: Path) -> list[str]:
    """Lignes des blocs de code du premier README trouvé, 2000 au plus."""
    return [l for b in _readme_code_blocks(root) for l in b]


def _entry_score(name: str, docker_lines: list[str], readme_lines: list[str]) -> int:
    """3 si le nom est exécutable ou argument d'un ENTRYPOINT/CMD (et non un dossier : « name/config.json »), 2 s'il est la CIBLE
    d'une commande de lancement du README (`cargo run --bin`, `./target/release/`, `go run ./cmd/`, `python x.py`), sinon 0."""
    n = re.escape(name)
    dpat = re.compile(rf"(?<![\w.-]){n}(?![\w/-])")
    if any(dpat.search(l) for l in docker_lines):
        return 3
    rpat = re.compile(
        rf"cargo\s+run\b[^\n]*?(?:--bin|-p|--package)[ =]{n}(?![\w-])"            # cargo run … --bin NOM / -p NOM
        rf"|\./target/(?:release|debug)/{n}(?![\w-])"                              # ./target/release/NOM
        rf"|go\s+(?:run|build|install)\b[^\n]*?(?:\./)?cmd/{n}(?![\w/-])"          # go run ./cmd/NOM
        rf"|(?:^|[\s$>])python3?\s+{n}(?![\w/-])")                                # python NOM.py
    return 2 if any(rpat.search(l) for l in readme_lines) else 0


def entry_evidence(root: Path, choices: list[str]) -> dict[str, int]:
    """Preuves textuelles pour chaque point d'entrée possible : Dockerfile (ENTRYPOINT/CMD) et compose (command/entrypoint) = 3,
    commande de lancement dans un bloc de code du README = 2. Rien d'autre (une simple mention en prose ne compte pas)."""
    docker_lines, readme_lines = _docker_command_lines(root), _readme_code_lines(root)
    return {c: _entry_score(name, docker_lines, readme_lines) for c in choices if (name := _choice_name(c))}


def disambiguate_entry(root: Path, choices: list[str]) -> tuple[str, str] | None:
    """Le seul point d'entrée appuyé par une preuve (et mieux que tous les autres) → (commande, source) ; sinon None."""
    ev = entry_evidence(root, choices)
    ranked = sorted(ev.items(), key=lambda kv: -kv[1])
    if not ranked or ranked[0][1] < 2:
        return None
    if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
        return None
    return ranked[0][0], ("Dockerfile/compose" if ranked[0][1] >= 3 else "README")


RUN_SCRIPT_NAMES = ("dev", "start", "serve", "develop", "run")
LAUNCH_RE = re.compile(
    r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:dev|start|serve|develop)\b|\bmake\s+(?:run|dev|start|serve|server)\b|\buvicorn\b|\bgunicorn\b"
    r"|\bflask\s+(?:--app\s+\S+\s+)?run\b|\bpython3?\s+(?:-m\s+)?[\w./-]+|\bcargo\s+run\b|\bgo\s+run\b|\bnode\s+[\w./-]+|\bdocker[ -]compose\s+up\b"
    r"|\bstreamlit\s+run\b|\bzero\b")
NOT_LAUNCH_RE = re.compile(r"\b(?:test|tests|pytest|lint|ruff|eslint|format|build|install|ci|migrate|typecheck|mypy|fmt)\b|\bpip\b|\bnpm\s+i(?:nstall)?\b|\bpython3?\s+-m\s+(?:pytest|pip|venv)\b")


def _launch_lines_by_cwd(root: Path, candidates: list[str]) -> tuple[dict[str, int], int]:
    """Parcourt les blocs du README en suivant `cd <dossier>` : → ({candidat: nb de commandes de lancement exécutées dedans},
    nb de commandes de lancement exécutées AILLEURS — racine ou dossier non candidat). Un bloc recommence à la racine ; les commandes de
    test/lint/build/installation ne comptent pas comme lancement."""
    inside = {c: 0 for c in candidates}
    elsewhere = 0
    cd_re = re.compile(r"^\s*(?:\$\s*)?cd\s+(?:\.{1,2}/)*([\w./-]+?)/?(?:\s*(?:&&|;)\s*(.*))?\s*$")
    for block in _readme_code_blocks(root):
        cwd: str | None = None
        for raw in block:
            line = raw.split(" #")[0].strip()
            if not line or line.startswith("#"):
                continue
            m, rest = cd_re.match(line), None
            if m:
                target, rest = m.group(1), m.group(2)
                cwd = None if target in ("..", ".") else target
                line = rest or ""
            if not line or NOT_LAUNCH_RE.search(line) or not LAUNCH_RE.search(line):
                continue
            hit = next((c for c in candidates if cwd and (cwd == c or c.endswith("/" + cwd) or cwd.endswith("/" + c))), None)
            if hit:
                inside[hit] += 1
            else:
                elsewhere += 1
    return inside, elsewhere


def project_evidence(root: Path, candidates: list[str]) -> dict[str, int]:
    """Preuve textuelle pour chaque sous-projet d'un monorepo : un script `dev`/`start`/… du package.json RACINE qui vise le dossier
    (`cd api && …`, `--prefix api`, `--filter api`, `-w api`, `./api/…`) = 3 ; une commande de LANCEMENT exécutée dans ce dossier par un bloc de
    code du README (`cd web` puis `npm run dev`) = 2, à condition qu'aucune autre commande de lancement n'existe ailleurs dans le README
    (ex. `make run-dev` à la racine) : sinon le README décrit plusieurs choses à lancer. Une mention en prose, ou un `cd` suivi d'un test/lint, ne compte pas."""
    try:
        scripts = json.loads(read(root, "package.json") or "{}").get("scripts") or {}
    except (ValueError, AttributeError):
        scripts = {}
    script_lines = [str(v) for k, v in scripts.items() if isinstance(v, str) and k.split(":")[0] in RUN_SCRIPT_NAMES]
    inside, elsewhere = _launch_lines_by_cwd(root, candidates)
    ev: dict[str, int] = {}
    for c in candidates:
        n = re.escape(c)
        spat = re.compile(rf"(?:\bcd|--prefix|--filter|--workspace|--cwd|--dir|\s-w|\s-C)[ =]+(?:\.{{1,2}}/)?{n}(?![\w-])|(?:^|\s)\./{n}/")
        ev[c] = 3 if any(spat.search(l) for l in script_lines) else 2 if inside[c] and not elsewhere else 0
    return ev


def disambiguate_project(root: Path, candidates: list[str]) -> tuple[str, str] | None:
    """Le seul sous-projet appuyé par une preuve (et mieux que tous les autres) → (dossier, source) ; sinon None (l'utilisateur choisit)."""
    ranked = sorted(project_evidence(root, candidates).items(), key=lambda kv: -kv[1])
    if not ranked or ranked[0][1] < 2 or (len(ranked) > 1 and ranked[1][1] == ranked[0][1]):
        return None
    return ranked[0][0], ("script du package.json racine" if ranked[0][1] >= 3 else "README")


def resolve_project(root: Path, project: str | None = None) -> tuple[Path, Plan]:
    """Racine du dépôt → (dossier du projet, plan). Descend dans un sous-dossier si le root n'est pas exécutable."""
    if project:
        sub = (root / project).resolve()
        if not sub.is_dir() or root.resolve() not in sub.parents:
            die(f"--project : « {project} » n'est pas un sous-dossier de {root.name}")
        return sub, detect_all(sub)
    try:
        plan = detect_all(root)
        if plan.run or plan.choices:
            return root, plan
        if not (plan.lang == "node" and is_js_workspace(root)):
            return root, plan      # reconnu (ex. bibliothèque Go) : ne pas descendre dans un autre langage
        err: ZeroError | None = None
    except ZeroError as e:
        plan, err = None, e
        if foreign_ecosystem(root):
            raise                       # Ruby/PHP/Java… à la racine : les sous-dossiers Node ne sont que de l'outillage
    if plan is None and any(root.glob("*.py")):
        deduced = detect_scripts(root)
        if deduced and (deduced.run or deduced.choices):
            return root, deduced
        raise ZeroError("scripts Python à la racine mais aucun manifeste reconnu (requirements dans un sous-dossier ?) "
                        "— utilisez --cmd, ou --project si un sous-dossier est le projet")
    candidates = find_projects(root)
    if len(candidates) == 1:
        sub = root / candidates[0]
        found = detect_all(sub)
        found.notes.append(f"monorepo : projet unique trouvé dans {candidates[0]}/")
        return sub, found
    if len(candidates) > 1:
        multistack = bool(detect_stacks(root))
        picked = None if multistack else disambiguate_project(root, candidates)
        if picked:
            sub = root / picked[0]
            found = detect_all(sub)
            found.notes.append(f"monorepo : {picked[0]}/ choisi d'après le {picked[1]} parmi {len(candidates)} projets "
                               f"({', '.join(c for c in candidates if c != picked[0])}) — précisez avec --project si ce n'est pas le bon")
            return sub, found
        raise AmbiguousProject(candidates, multistack=multistack)
    if plan is not None:
        return root, plan          # reconnu mais sans commande principale
    raise err or ZeroError("aucun projet détecté")


# ───────────────────────────── multi-stack ─────────────────────────────

STACK_DIRS = ("backend", "frontend", "server", "client", "api", "web", "app", "ui", "worker")


def _runnable(d: Path) -> Plan | None:
    """Le plan d'un dossier s'il a une commande de lancement, sinon None (y compris quand rien n'y est reconnu)."""
    try:
        p = detect_all(d)
    except ZeroError:
        return None
    return p if p.run else None


def _conventional_stack_dirs(root: Path):
    """Dossiers de stack usuels (backend/, frontend/, api/, web/…) à la racine puis sous src/, app/, apps/ ; `app/` seul n'est ignoré que
    s'il n'est qu'un conteneur (app/backend, app/web…). Chaque nom n'est retenu qu'une fois."""
    seen: set[str] = set()
    for base in ("", "src", "app", "apps"):
        for name in STACK_DIRS:
            d = (root / base / name) if base else (root / name)
            if name in seen or not d.is_dir():
                continue
            if not base and name == "app" and any((d / n).is_dir() for n in STACK_DIRS):
                continue
            yield name, d, seen


def detect_stacks(root: Path) -> list[tuple[str, Path, Plan]]:
    """Dépôt multi-stack : au moins deux langages DIFFÉRENTS exécutables (racine + dossiers conventionnels, aussi sous src/, app/, apps/).

    Ne se déclenche pas avec un Procfile (déjà multi-process) ni avec un seul langage (workspace JS, etc.)."""
    if (root / "Procfile").is_file():
        return []
    found: list[tuple[str, Path, Plan]] = []
    if (p := _runnable(root)):
        found.append(("root", root, p))
    for name, d, seen in _conventional_stack_dirs(root):
        if (p := _runnable(d)):
            seen.add(name)
            found.append((name, d, p))
    # racine du même langage qu'un sous-dossier : c'est un orchestrateur (workspace JS qui lance frontend/…),
    # le lancer en plus démarrerait la même chose deux fois
    sub_langs = {p.lang for n, _, p in found if n != "root"}
    found = [t for t in found if not (t[0] == "root" and t[2].lang in sub_langs)]
    return found if len(found) >= 2 and len({p.lang for _, _, p in found}) >= 2 else []
