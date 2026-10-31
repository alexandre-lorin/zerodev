"""V4 : erreur process → diagnostic → hypothèse de dépendance → retry dans la sandbox.

Règles déterministes uniquement. Les corrections automatiques ne touchent que la sandbox
(venv, node_modules du dépôt, variable PORT). Tout changement est journalisé dans
~/.zero/logs/<projet>.jsonl. Les corrections système (apt/brew) ne sont jamais appliquées :
elles sont affichées comme actions manuelles.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .plan import Plan, venv_dir
from .util import free_port, q, zero_home

MAX_ATTEMPTS = 4          # les casses d'API se révèlent en cascade : chaque correctif n'est de toute façon tenté qu'une fois

PY_IMPORT_MAP = {
    "cv2": "opencv-python", "PIL": "pillow", "yaml": "pyyaml", "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4", "dotenv": "python-dotenv", "jwt": "pyjwt", "dateutil": "python-dateutil",
    "attr": "attrs", "serial": "pyserial", "OpenSSL": "pyopenssl", "Crypto": "pycryptodome",
    "magic": "python-magic", "psycopg2": "psycopg2-binary", "MySQLdb": "mysqlclient",
    "pkg_resources": "setuptools<81",    # retiré des setuptools récents ; requis par les vieux gunicorn, etc.
}
PY_LAUNCHERS = {"gunicorn": "gunicorn", "uvicorn": "uvicorn", "hypercorn": "hypercorn", "daphne": "daphne",
                "waitress-serve": "waitress", "granian": "granian", "flask": "flask"}

SYSTEM_TOOLS = {
    "ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "pg_config": "libpq-dev", "gcc": "build-essential",
    "cc": "build-essential", "make": "build-essential", "cmake": "cmake", "git": "git",
    "convert": "imagemagick", "pdftoppm": "poppler-utils", "tesseract": "tesseract-ocr",
    "pkg-config": "pkg-config", "protoc": "protobuf-compiler",
}


@dataclass
class Fix:
    description: str
    commands: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    manual: str | None = None     # action que l'utilisateur doit faire lui-même

    @property
    def automatic(self) -> bool:
        return bool(self.commands or self.env)

    @property
    def key(self) -> str:
        return self.description


# Chaque règle lit la sortie d'erreur et propose des correctifs (`Fix`) ; `diagnose` les évalue dans l'ordre de RULES (l'ordre est celui
# de l'affichage et de l'application) en écartant les correctifs déjà tentés. Une règle ne modifie rien : elle décrit.

def _py(root: Path) -> Path:
    return venv_dir(root) / "bin" / "python"


def _rule_python_module(plan: Plan, root: Path, tail: str):
    """Module Python manquant (hors module local du dépôt) → installé dans le venv."""
    for m in re.finditer(r"ModuleNotFoundError: No module named '([\w.]+)'", tail):
        top = m.group(1).split(".")[0]
        if (root / top).exists() or (root / f"{top}.py").exists():
            continue                                   # module local : ce n'est pas une dépendance à installer
        pkg = PY_IMPORT_MAP.get(top, top)
        yield Fix(f"module Python manquant « {top} » → installer {pkg}", commands=[f"uv pip install --python {q(str(_py(root)))} {q(pkg)}"])


def _rule_config_example(plan: Plan, root: Path, tail: str):
    """Module de configuration absent alors qu'un modèle « _example » existe → copie (jamais d'écrasement)."""
    if plan.lang == "python":
        for src_rel, dst_rel in config_example_copies(root, tail):
            yield Fix(f"configuration manquante « {Path(dst_rel).name} » : copie du modèle {src_rel} (le dépôt reçoit un nouveau fichier)",
                      commands=[f"cp -n {q(src_rel)} {q(dst_rel)}"])


def _rule_api_breaks(plan: Plan, root: Path, tail: str):
    """API retirée d'une dépendance récente (vieux code, paquet non épinglé) → plafonds de versions connus."""
    if plan.lang != "python":
        return
    flask_old = None                                   # Flask installé < 2.2 ? (calculé à la demande : lance un interpréteur)
    for pattern, pins, label in PY_API_BREAKS:
        if not pattern.search(tail):
            continue
        if pins[0].split("<")[0] in FLASK_ECOSYSTEM and pins not in (_OLD_FLASK_SET, _VERY_OLD_FLASK_SET):
            flask_old = installed_flask_is_old(_py(root)) if flask_old is None else flask_old
            if flask_old:                              # vieux Flask : poser d'un coup l'ensemble cohérent, sinon les casses arrivent en cascade
                pins, label = _OLD_FLASK_SET, label + ", Flask ancien installé : ensemble cohérent d'avant 2022"
        yield Fix(f"API retirée ({label}) : le code attend d'anciennes versions → {' '.join(pins)}",
                  commands=[f"uv pip install --python {q(str(_py(root)))} " + " ".join(q(x) for x in pins)])


def _rule_node_module(plan: Plan, root: Path, tail: str):
    """Module Node manquant (npm uniquement : pnpm/yarn modifieraient le lockfile)."""
    for m in re.finditer(r"Cannot find (?:module|package) '([^'\n]+)'", tail):
        name = m.group(1)
        if name.startswith((".", "/")) or name.startswith("node:"):
            continue
        parts = name.split("/")
        pkg = "/".join(parts[:2]) if name.startswith("@") else parts[0]
        if plan.pm == "npm":
            yield Fix(f"module Node manquant « {pkg} » → npm install --no-save", commands=[f"npm install --no-save {q(pkg)}"])
        else:
            yield Fix(f"module Node manquant « {pkg} »", manual=f"ajoutez {pkg} avec {plan.pm}")


def _rule_port_in_use(plan: Plan, root: Path, tail: str):
    """Port déjà utilisé : on bascule sur un port libre via PORT."""
    if re.search(r"EADDRINUSE|address already in use|Errno 98|Errno 48", tail, re.I):
        port = free_port(8000)
        yield Fix(f"port occupé → relance avec PORT={port}", env={"PORT": str(port)})


def _rule_no_ipv6(plan: Plan, root: Path, tail: str):
    """Pas d'IPv6 (Docker, sandbox…) alors que le serveur lie « :: » : GUNICORN_CMD_ARGS, prioritaire sur gunicorn.conf.py,
    force 0.0.0.0 sans toucher au dépôt."""
    if re.search(r"Address family not supported by protocol|Errno 97", tail) and "gunicorn" in (plan.run or "") + tail:
        m = re.search(r"\('::', (\d+)\)", tail)
        port = m.group(1) if m else "8000"
        yield Fix(f"IPv6 indisponible → gunicorn lié à 0.0.0.0:{port}", env={"GUNICORN_CMD_ARGS": f"--bind 0.0.0.0:{port}"})


def _rule_python_launcher(plan: Plan, root: Path, tail: str):
    """Serveur d'application cité par le Procfile/la commande mais absent des requirements (Heroku et consorts l'installent eux-mêmes)."""
    if plan.lang == "python":
        for tool in dict.fromkeys(re.findall(r"(?:^|\s)([\w.+-]+): (?:command )?not found", tail, re.M)):
            if tool in PY_LAUNCHERS:
                pkg = PY_LAUNCHERS[tool]
                yield Fix(f"serveur Python manquant « {tool} » → installer {pkg}",
                          commands=[f"uv pip install --python {q(str(_py(root)))} {q(pkg)}"])


def _rule_system(plan: Plan, root: Path, tail: str):
    """Outils et bibliothèques système manquants : jamais installés automatiquement, seulement signalés."""
    tools = re.findall(r"(?:^|\s)([\w.+-]+): (?:command )?not found", tail, re.M)
    tools += re.findall(r"No such file or directory: '([\w.+-]+)'", tail)
    tools += re.findall(r'exec: "([\w.+-]+)": executable file not found', tail)   # Go / cgo
    for tool in dict.fromkeys(tools):
        if tool in SYSTEM_TOOLS:
            pkg = SYSTEM_TOOLS[tool]
            yield Fix(f"outil système manquant « {tool} »", manual=f"apt install {pkg}  (ou : brew install {pkg})")
    for lib in dict.fromkeys(re.findall(r"error while loading shared libraries: (lib[\w.+-]+)", tail)):
        yield Fix(f"bibliothèque système manquante « {lib} »", manual=f"installez le paquet qui fournit {lib} (apt-file search {lib})")
    if re.search(r"Python\.h: No such file|fatal error: Python\.h", tail):
        yield Fix("en-têtes Python manquants", manual="apt install python3-dev build-essential")
    if re.search(r"linker `cc` not found|Could not find openssl|openssl-sys", tail):
        yield Fix("toolchain C / OpenSSL manquants (Rust)", manual="apt install build-essential pkg-config libssl-dev")


def _rule_env_vars(plan: Plan, root: Path, tail: str):
    """Variables d'environnement manquantes : signalées, jamais inventées."""
    envs = re.findall(r"KeyError: '([A-Z][A-Z0-9_]+)'", tail)
    envs += re.findall(r"(?:Missing|Undefined|required) (?:required )?env(?:ironment)?(?: variable)?:? ['\"]?([A-Z][A-Z0-9_]+)", tail, re.I)
    for var in dict.fromkeys(envs):
        yield Fix(f"variable d'environnement manquante « {var} »", manual=f"définissez {var} dans .env")


RULES = (_rule_python_module, _rule_config_example, _rule_api_breaks, _rule_node_module, _rule_port_in_use, _rule_no_ipv6,
         _rule_python_launcher, _rule_system, _rule_env_vars)


def diagnose(plan: Plan, root: Path, tail: str, already: set[str]) -> list[Fix]:
    """Correctifs proposés pour cette sortie d'erreur, sans ceux déjà tentés (`already`) ni les doublons."""
    fixes: list[Fix] = []
    for rule in RULES:
        for fix in rule(plan, root, tail):
            if fix.key not in already and all(f.key != fix.key for f in fixes):
                fixes.append(fix)
    return fixes


def journal(project: str, entry: dict) -> Path:
    path = zero_home() / "logs" / f"{project}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}, ensure_ascii=False) + "\n")
    return path


# Alias ABC retirés du module `collections` en Python 3.10 (à importer depuis collections.abc)
COLLECTIONS_ABC = ("Awaitable", "Coroutine", "AsyncIterable", "AsyncIterator", "AsyncGenerator", "Hashable", "Iterable", "Iterator",
                   "Generator", "Reversible", "Sized", "Container", "Callable", "Collection", "Set", "MutableSet", "Mapping",
                   "MutableMapping", "MappingView", "KeysView", "ItemsView", "ValuesView", "Sequence", "MutableSequence", "ByteString")

# Échelle de rétrogradation : symptôme dans la sortie d'erreur → dernière version mineure de Python 3.x qui fonctionne.
PY_DOWNGRADE_RULES = (
    (re.compile(r"No module named ['\"](imp|distutils|asyncore|asynchat|smtpd|[\w.]*six\.moves)['\"]|ImpImporter"), 11),   # retirés en 3.12
    (re.compile(r"has no attribute ['\"]getargspec['\"]"), 10),                                              # retiré en 3.11
    (re.compile(r"cannot import name ['\"](" + "|".join(COLLECTIONS_ABC) + r")['\"] from ['\"]collections['\"]"), 9),  # 3.10
)


_OLD_FLASK_SET = ["flask<2.1", "werkzeug<2.1", "jinja2<3.1", "itsdangerous<2.1", "markupsafe<2.1"]    # l'ensemble cohérent d'avant 2022
EXAMPLE_SUFFIXES = ("_example", ".example", "_sample", ".sample", "_template", ".dist", "-example")
MISSING_CONFIG_MODULE = re.compile(
    r"No module named '([\w.]+)'|module '[\w.]+' has no attribute '(\w+)'|import_string\(\) failed for '([\w.]+)'")


def config_example_copies(root: Path, tail: str) -> list[tuple[str, str]]:
    """Le module absent (`app.local_settings`, `config_local`…) a un modèle voisin `<nom>_example.py` (ou `.example`, `_sample`…)
    et un seul : [(modèle, cible)] relatifs à la racine. Sans modèle, ou avec plusieurs, rien (on ne devine pas)."""
    names = {n.split(".")[-1] for m in MISSING_CONFIG_MODULE.finditer(tail or "") for n in m.groups() if n}
    out: list[tuple[str, str]] = []
    for name in sorted(names):
        if (root / name).exists() or (root / f"{name}.py").exists():
            continue                                     # module local réel : un autre problème
        found: list[Path] = []
        for suffix in EXAMPLE_SUFFIXES:
            for cand in (f"{name}{suffix}.py", f"{name}.py{suffix}"):
                found += [f for f in root.rglob(cand) if f.is_file() and not any(
                    part in ("node_modules", ".git", "venv", ".venv", "site-packages") for part in f.parts)]
        found = sorted(set(found))
        if len(found) == 1:
            dst = found[0].with_name(f"{name}.py")
            if not dst.exists():
                out.append((str(found[0].relative_to(root)), str(dst.relative_to(root))))
    return out


FLASK_ECOSYSTEM = {"jinja2", "markupsafe", "itsdangerous", "werkzeug"}


def installed_flask_is_old(py: Path) -> bool:
    """Flask < 2.2 dans ce venv ? (les extensions et le code de cette époque supposent l'ensemble Werkzeug/Jinja d'avant 2022)"""
    import subprocess
    try:
        out = subprocess.run([str(py), "-c", "import importlib.metadata as m;print(m.version('flask'))"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        major, minor = (int(x) for x in re.match(r"(\d+)\.(\d+)", out).groups())
    except (OSError, subprocess.TimeoutExpired, AttributeError, ValueError):
        return False
    return (major, minor) < (2, 2)


_VERY_OLD_FLASK_SET = ["flask<1.1", "werkzeug<1.0", "jinja2<3.0", "itsdangerous<1.2", "markupsafe<2.0"]    # Flask 1.0 (2018)
# Casses d'API bien connues : (symptôme dans la trace, versions plafonnées, libellé). Table volontairement courte et à entretenir.
PY_API_BREAKS = (
    (re.compile(r"cannot import name '(?:escape|Markup|contextfilter|environmentfilter|evalcontextfilter|contextfunction|"
                r"environmentfunction|evalcontextfunction)' from 'jinja2'"), ["jinja2<3.1"], "jinja2 ≥ 3.1"),
    (re.compile(r"cannot import name 'soft_unicode' from 'markupsafe'"), ["markupsafe<2.1"], "markupsafe ≥ 2.1"),
    (re.compile(r"cannot import name '(?:BaseResponse|BaseRequest|safe_str_cmp)' from 'werkzeug"), _OLD_FLASK_SET, "werkzeug ≥ 2.1"),
    (re.compile(r"cannot import name '(?:url_encode|url_decode|url_quote|url_quote_plus|url_unquote|url_fix|cached_property|"
                r"secure_filename|escape)' from 'werkzeug' \("), _VERY_OLD_FLASK_SET, "werkzeug ≥ 1.0 (imports au niveau supérieur retirés)"),
    (re.compile(r"cannot import name '(?:url_quote|url_encode|url_decode|url_unquote)' from 'werkzeug\.urls'"),
     ["flask<3", "werkzeug<3"], "werkzeug ≥ 3"),
    (re.compile(r"cannot import name '(?:escape|Markup)' from 'flask'|module 'flask\.json' has no attribute 'JSONEncoder'"),
     ["flask<2.3"], "flask ≥ 2.3"),
    (re.compile(r"cannot import name 'json' from 'itsdangerous'"), ["itsdangerous<2.1"], "itsdangerous ≥ 2.1"),
    (re.compile(r"module 'sqlalchemy' has no attribute '__all__'|'Engine' object has no attribute 'execute'|"
                r"Not an executable object: '"), ["sqlalchemy<2"], "SQLAlchemy ≥ 2.0"),
    (re.compile(r"cannot import name '(?:TextField|SelectMultipleField_)' from 'wtforms'|No module named 'wtforms\.ext"),
     ["wtforms<3"], "wtforms ≥ 3"),
)


def _minor(version: str | None) -> int:
    m = re.match(r"3\.(\d+)", (version or "").lstrip("<>=~^! "))
    return int(m.group(1)) if m else 99                # version inconnue : la plus récente


BUILD_FAILED_PINNED = re.compile(r"Failed to build `([\w.-]+)==([\w.+!-]+)`")
SYSTEM_HEADER_MISSING = re.compile(r"fatal error: [\w./+-]+\.h: No such file|Can't find (?:the )?\w+ (?:headers|library)|pg_config", re.I)


def old_pin_build_failure(tail: str) -> tuple[str, str] | None:
    """`Failed to build `pkg==x.y`` pour une dépendance épinglée, hors manque d'en-têtes système (un autre Python n'y changerait
    rien) et hors code Python 2 (non portable) : (paquet, version) ou None."""
    m = BUILD_FAILED_PINNED.search(tail or "")
    if not m or SYSTEM_HEADER_MISSING.search(tail) or python2_hint(tail):
        return None
    return m.group(1), m.group(2)


def _actual_minor(tail: str, fallback: int) -> int:
    m = re.search(r"python3\.(\d+)/|CPython 3\.(\d+)|Python 3\.(\d+)\b", tail or "")
    return int(next(g for g in m.groups() if g)) if m else fallback


def diagnose_python_install(plan: Plan, tail: str) -> str | None:
    """Échec dû à une API retirée d'une version récente de Python → version « 3.N » à utiliser (ou None).

    Typique des vieux projets sans version déclarée : la version par défaut (la plus récente) est alors trop neuve.
    Ne propose qu'une version plus ancienne que l'actuelle ; l'appelant n'essaie chaque palier qu'une fois."""
    if plan.lang != "python":
        return None
    current = _minor(plan.version)
    for pattern, minor in PY_DOWNGRADE_RULES:
        if pattern.search(tail) and current > minor:
            return f"3.{minor}"
    old_pin = old_pin_build_failure(tail)
    if old_pin and abi_cap(tail) is None:
        actual = _actual_minor(tail, current)
        target = 9 if actual >= 10 else 8 if actual == 9 else None   # les anciens pins (2019-2021) n'ont souvent des roues que jusqu'à cp39
        floor = re.match(r"\s*(?:>=|>|\^|~=)\s*3\.(\d+)", plan.version or "")
        if target is None or (floor and int(floor.group(1)) > target):
            return None             # le projet exige au moins cette version : on ne descend pas en dessous
        return f"3.{target}"
    abi = abi_cap(tail)
    if abi is not None:
        # version réellement utilisée : celle que cite uv (plan.version peut n'être qu'une contrainte « >=3.11 »)
        m = re.search(r"CPython 3\.(\d+)|Using (?:CPython|Python) 3\.(\d+)", tail)
        actual = int(m.group(1) or m.group(2)) if m else current
        if actual > abi:
            return f"3.{abi}"
    return None


ABI_TAGS = re.compile(r"Python ABI tags?:?\s*((?:`?cp3\d+`?[,\s]*(?:and\s+)?)+)", re.I)


def abi_cap(tail: str) -> int | None:
    """« aucune roue pour ce Python ; roues publiées pour cp311, cp312, cp313 » → 13 (plus récent Python couvert).

    uv liste les ABI pour lesquels le paquet publie des roues : au-delà du plus récent, il n'y en a pas."""
    m = ABI_TAGS.search(tail)
    if not m:
        return None
    minors = [int(x) for x in re.findall(r"cp3(\d+)", m.group(1))]
    return max(minors) if minors else None


PY_NO_INTERPRETER = re.compile(r"No interpreter found for Python (\d+)\.(\d+)(\.\d+)?")
PY_OLDEST_AVAILABLE = "3.8"     # plus ancien Python que uv sait encore fournir


def diagnose_python_patch(plan: Plan, tail: str) -> str | None:
    """Python demandé indisponible via uv → version de repli (ou None).

    « 3.8.1 » introuvable (uv ne garde que le dernier correctif de chaque mineure) → « 3.8 » ;
    « 3.6 » / « 3.7 » (plus fournis) → la plus ancienne disponible (3.8)."""
    if plan.lang != "python":
        return None
    m = PY_NO_INTERPRETER.search(tail)
    if not m:
        return None
    major, minor, patch = int(m.group(1)), int(m.group(2)), m.group(3)
    if (major, minor) < (3, 8):
        return PY_OLDEST_AVAILABLE if plan.version != PY_OLDEST_AVAILABLE else None
    return f"{major}.{minor}" if patch else None


PG_CONFIG_MISSING = re.compile(
    r"pg_config (executable not found|is required)"
    r"|(?:pg_config|libpq-fe|postgres_ext)\.h: No such file", re.I)   # en-têtes libpq absents (libpq-dev)


def diagnose_psycopg2(plan: Plan, tail: str) -> bool:
    """psycopg2 veut se compiler et il manque libpq (pg_config) → utiliser psycopg2-binary (même version)."""
    return plan.lang == "python" and bool(PG_CONFIG_MISSING.search(tail))


def flatten_requirements(path: Path, _seen: set | None = None) -> list[str]:
    """Contenu d'un requirements.txt avec les `-r autre.txt` développés (chemins relatifs au fichier qui inclut)."""
    seen = _seen if _seen is not None else set()
    path = path.resolve()
    if path in seen or not path.is_file():
        return []
    seen.add(path)
    out: list[str] = []
    for line in path.read_text(errors="ignore").splitlines():
        m = re.match(r"^\s*(?:-r|--requirement)[\s=]+(\S+)", line)
        if m:
            out += flatten_requirements(path.parent / m.group(1), seen)
        else:
            out.append(line)
    return out


def swap_psycopg2(lines: list[str], keep_version: bool = True) -> list[str]:
    """psycopg2 → psycopg2-binary (extras et contrainte de version conservés) ; ne touche pas psycopg2-binary.

    keep_version=False : retire aussi la contrainte de version (vieux pin sans wheel binaire pour ce Python)."""
    out = []
    for ln in lines:
        if keep_version:
            out.append(re.sub(r"^(\s*)psycopg2(?![\w.-])", r"\1psycopg2-binary", ln))
        else:
            out.append(re.sub(r"^(\s*)psycopg2(?:-binary)?(?![\w.-])(\[[^\]]*\])?\s*(?:[=<>!~]=?[^;#\s]*(?:\s*,\s*[=<>!~]=?[^;#\s]*)*)?",
                              r"\1psycopg2-binary\2", ln))
    return out


def psycopg2_pin_unsatisfiable(tail: str) -> bool:
    """Après le passage à psycopg2-binary : la version épinglée n'a pas de binaire pour cette version de Python."""
    return "psycopg2-binary" in tail and bool(re.search(r"unsatisfiable|No solution found|no version of psycopg2-binary", tail, re.I))


COREPACK_FETCH_FAIL = re.compile(r"Error when performing the request to https://(?:repo|registry)\.yarnpkg\.com")


def diagnose_corepack(tail: str) -> dict[str, str] | None:
    """Corepack ne joint pas repo.yarnpkg.com (proxy d'entreprise, domaine filtré) → le télécharger depuis le registre npm
    (`@yarnpkg/cli-dist`), celui que l'utilisateur a configuré s'il y en a un."""
    if not COREPACK_FETCH_FAIL.search(tail or ""):
        return None
    return {"COREPACK_NPM_REGISTRY": os.environ.get("npm_config_registry") or "https://registry.npmjs.org"}


NPM_CI_OUT_OF_SYNC = re.compile(
    r"npm ci` can only install packages|package-lock\.json.*(?:not in sync|out of sync)|Missing: \S+ from lock file"
    r"|EUSAGE|Invalid: lock file", re.I)
NPM_LOCK_UNUSABLE = re.compile(r"EALLOWREMOTE|npm error 404|npm ERR! 404|code E404")     # URL de miroir / version absente du registre
NPM_PEER_CONFLICT = re.compile(r"ERESOLVE|Could not resolve dependency|peer dep", re.I)


def diagnose_npm_ci(step: str, tail: str) -> str | None:
    """`npm ci` échoue → commande de remplacement (ou None).

    Lockfile désynchronisé de package.json → `npm install` (le lockfile du dépôt n'est pas écrit : npm l'ignore si
    incohérent, le dépôt reste inchangé hors `package-lock.json` éventuel) ; conflit de pairs → `--legacy-peer-deps`."""
    if not re.search(r"(?:^|\s)npm ci(?:\s|$)", step):
        return None
    if NPM_PEER_CONFLICT.search(tail):
        return re.sub(r"npm ci", "npm install --legacy-peer-deps", step, count=1)
    if NPM_CI_OUT_OF_SYNC.search(tail):
        return re.sub(r"npm ci", "npm install", step, count=1)
    if NPM_LOCK_UNUSABLE.search(tail):                 # lockfile pointant vers un miroir inaccessible ou des versions absentes
        return re.sub(r"npm ci", "npm install --no-package-lock", step, count=1)
    return None


SCM_VERSION_FAIL = re.compile(
    r"setuptools[-_]scm|vcs[-_]versioning|hatch[-_]vcs|is shallow and may cause errors"
    r"|unable to detect version|Unable to determine version|dunamai|versioneer", re.I)
SCM_PRETEND = {"SETUPTOOLS_SCM_PRETEND_VERSION": "0.0.0", "VCS_VERSIONING_PRETEND_VERSION": "0.0.0",
               "HATCH_VCS_PRETEND_VERSION": "0.0.0"}


def diagnose_scm_version(plan: Plan, tail: str) -> dict[str, str] | None:
    """La construction du projet calcule sa version depuis git (setuptools-scm, hatch-vcs…) et échoue faute
    d'historique/étiquettes (clone `--depth 1`, archive) → variables « version imposée » (0.0.0)."""
    if plan.lang != "python" or not SCM_VERSION_FAIL.search(tail):
        return None
    return dict(SCM_PRETEND)


NODE_LIFECYCLE_FAIL = re.compile(
    r"npm (?:error|ERR!) command failed\s*\n(?:npm (?:error|ERR!)[^\n]*\n)*?npm (?:error|ERR!) command sh -c"
    r"|ELIFECYCLE|Command failed with exit code.*\bpostinstall|lifecycle script"
    r"|install script from \"[^\"]+\" exited with", re.I)                  # bun
PNPM_IGNORED_BUILDS = re.compile(r"ERR_PNPM_IGNORED_BUILDS")


def diagnose_node_scripts(step: str, tail: str) -> str | None:
    """Un script de cycle de vie (postinstall…) fait échouer `npm|pnpm|yarn|bun install|ci` → même commande avec
    `--ignore-scripts` (dernier recours : un module natif à compiler ne fonctionnera alors pas)."""
    pnpm = re.search(r"(?:^|\s)pnpm\s+(?:install|i|add)(?:\s|$)", step)
    if pnpm and PNPM_IGNORED_BUILDS.search(tail):
        # pnpm ≥ 10 n'exécute pas les scripts de dépendances non approuvés et, depuis la 12, en fait une ERREUR : on garde son
        # comportement par défaut (scripts non exécutés) sans l'erreur. `--ignore-scripts` ne suffit pas à l'éviter.
        return None if "strict-dep-builds" in step else step + " --config.strict-dep-builds=false"
    if "--ignore-scripts" in step or not re.search(r"(?:^|\s)(?:npm|pnpm|yarn|bun)\s+(?:ci|install|i)(?:\s|$)", step):
        return None
    return step + " --ignore-scripts" if NODE_LIFECYCLE_FAIL.search(tail) else None


DEV_ENGINES_NPM = re.compile(r"EBADDEVENGINES[\s\S]{0,400}?required:\s*\{\s*name:\s*'npm',\s*version:\s*'([^']+)'")


def diagnose_dev_engines(tail: str) -> str | None:
    """`devEngines.packageManager` exige une version d'npm que celle du Node choisi n'est pas → la plage demandée."""
    m = DEV_ENGINES_NPM.search(tail)
    return m.group(1) if m else None


CLI_HELP = re.compile(r"(?im)^\s*usage:|\bsubcommands?\b|--help\b|requires an interactive terminal|interactive terminal")


def cli_tool_hint(tail: str, uptime: float) -> str | None:
    """Sortie rapide qui affiche une aide/un usage : c'est un outil en ligne de commande, pas un serveur."""
    if uptime >= 8 or not CLI_HELP.search(tail or ""):
        return None
    return ("ce projet ressemble à un outil en ligne de commande (il affiche son aide puis quitte) : ce n'est pas un serveur. "
            "Il est installé ; lancez-le avec vos arguments : `zero run <dossier> -- <arguments>`.")


PY2_MODULES = {"cPickle", "cStringIO", "StringIO", "urllib2", "urlparse", "ConfigParser", "Tkinter", "tkMessageBox",
               "httplib", "HTMLParser", "commands", "__builtin__", "xmlrpclib", "SocketServer", "Cookie", "copy_reg",
               "thread", "Queue", "exceptions", "ttk", "tkFileDialog", "BaseHTTPServer", "SimpleHTTPServer"}
PY2_SIGNS = re.compile(
    r"Missing parentheses in call to 'print'|No module named '?(?:%s)'?|SyntaxError: invalid syntax.*\bprint\b"
    r"|except \w+, \w+:|Python 2\b(?!\.?\d*\+)|python2" % "|".join(sorted(PY2_MODULES)), re.I)


def python2_hint(tail: str) -> str | None:
    """Trace typique d'un code Python 2 (print sans parenthèses, cPickle, urllib2…) → explication claire, sinon None."""
    if not PY2_SIGNS.search(tail or ""):
        return None
    return ("ce projet semble écrit pour Python 2 (print sans parenthèses, modules cPickle/urllib2…) : zero ne fournit que "
            "Python ≥ 3.8 et ne porte pas le code. Il faut le migrer vers Python 3 (outil `2to3`) ou lancer un Python 2 vous-même.")


def diagnose_install(plan: Plan, tail: str) -> str | None:
    """Échec d'installation → version de Node requise par une dépendance (ou None).

    Couvre pnpm (« Expected version: >=22.12.0 / Got: v20… ») et yarn (« Expected version ">=22" »).
    Le .nvmrc du dépôt est alors périmé : on monte de version dans la sandbox, sans toucher au dépôt.
    """
    if plan.lang != "node":
        return None
    m = re.search(r"Expected version:?\s*\"?([^\n\"]+)", tail)
    if m and re.search(r"\d", m.group(1)) and re.search(r"Unsupported|incompatible|engine", tail, re.I):
        return m.group(1).strip()
    return None
