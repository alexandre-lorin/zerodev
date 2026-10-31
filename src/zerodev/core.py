"""Orchestration : Repository → Detectors → Planner → Resolver → Sandbox → Services → Supervisor."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import gpu as gpumod
from .freeze import (LOCK_NAME, apply_lock, build_lock, fingerprint, load_lock, lock_drift,
                     system_libs, write_lock)
from .plan import Plan, detect_python, detect_stacks, disambiguate_entry, find_manage_py, makefile_run, readme_run, resolve_project, venv_dir
from .recovery import MAX_ATTEMPTS, abi_cap, old_pin_build_failure, diagnose_corepack, cli_tool_hint, python2_hint, diagnose_dev_engines, diagnose_node_scripts, diagnose_scm_version, diagnose_npm_ci, Fix, diagnose, diagnose_install, diagnose_psycopg2, diagnose_python_install, diagnose_python_patch, flatten_requirements, journal, psycopg2_pin_unsatisfiable, swap_psycopg2
from .registry import lookup, record
from .runtimes import ENSURE, installed_version
from .services import Service, ServiceManager, detect_services, fill_env, report_env
from .share import BUNDLE_SUFFIX, create_bundle, open_bundle
from .supervisor import Supervisor
from .util import ZeroError, dep_text, die, free_port, log, port_open, q, requirements_file, run_tee, sh, warn, with_path, zero_home


@dataclass
class Context:
    root: Path
    plan: Plan
    services: list[Service]
    gpu: dict
    fp: str
    origin: str | None = None          # zero.lock.json | registre | None
    drift: list[str] = field(default_factory=list)
    name: str = ""                      # nom de la stack en mode --all


# ───────────────────────────── cible ─────────────────────────────

def resolve_target(target: str) -> Path:
    if re.match(r"^(https?://|git@|ssh://)", target):
        name = re.sub(r"\.git$", "", target.rstrip("/").split("/")[-1].split(":")[-1])
        dest = Path.cwd() / name
        if not dest.exists():
            log(f"clone de {target}")
            if subprocess.run(["git", "clone", "--depth", "1", target, str(dest)]).returncode:
                die("git clone a échoué")
        return dest
    p = Path(target).resolve()
    if p.is_file() and p.name.endswith(BUNDLE_SUFFIX):
        log(f"ouverture du bundle {p.name}")
        return open_bundle(p)
    if not p.is_dir():
        die(f"dossier introuvable : {target}")
    return p


# ───────────────────────────── plan ─────────────────────────────

def repin_python(plan: Plan) -> None:
    pin = q(plan.pinned or "")
    out = []
    for c in plan.install:
        if plan.version:
            c = c.replace(f"--python {q(plan.version)}", f"--python {pin}")
        else:
            c = c.replace("uv venv ", f"uv venv --python {pin} ").replace(
                "uv sync --frozen", f"uv sync --frozen --python {pin}")
        out.append(c)
    plan.install = out


def _note_multistack(plan: Plan, repo_root: Path) -> None:
    """Dépôt multi-stack dont la racine a déjà une commande : on le signale (seule cette stack sera lancée sans `--all`)."""
    stacks = detect_stacks(repo_root)
    if stacks:
        plan.notes.append("multi-stack : " + ", ".join(f"{n} ({p.lang})" for n, _, p in stacks)
                          + " — seul « " + plan.lang + " » sera lancé ; `zero --all` lance tout")


def _fill_missing_command(root: Path, plan: Plan) -> None:
    """Sans commande : départage les points d'entrée par une preuve (README/Dockerfile), puis, en dernier recours, une cible du Makefile."""
    if not plan.run and not plan.processes and len(plan.choices) > 1:
        picked = disambiguate_entry(root, plan.choices)
        if picked:
            others = [c for c in plan.choices if c != picked[0]]
            plan.run, plan.choices = picked[0], []
            plan.notes.append(f"point d'entrée choisi d'après le {picked[1]} (« {picked[0]} ») parmi {len(others) + 1} possibles ; "
                              f"autres : {', '.join(others[:5])} — précisez avec --cmd si ce n'est pas le bon")
    if not plan.run and not plan.processes and not plan.choices:
        mk = makefile_run(root)
        if mk:
            plan.run = mk[0]
            plan.notes.append(f"commande déduite du Makefile (cible « {mk[1]} ») — aucune autre commande trouvée, non vérifiée")
    if not plan.run and not plan.processes and not plan.choices and (rd := readme_run(root, plan.lang)):
        plan.run = rd[0]
        plan.notes.append(f"commande déduite du README (« {rd[1]} ») : le fichier cité existe, mais rien d'autre ne la confirme — "
                          "précisez avec --cmd si ce n'est pas la bonne")


def _apply_lock_or_registry(ctx: Context, root: Path) -> None:
    """Épingle les versions d'après `zero.lock.json` (avec dérive éventuelle) ou, à défaut, d'après le registre (jamais les commandes)."""
    plan = ctx.plan
    lock = load_lock(root)
    if lock and apply_lock(plan, lock):
        ctx.origin, ctx.drift = LOCK_NAME, lock_drift(root, lock)
    elif not lock and (reg := lookup(ctx.fp)) and apply_lock(plan, reg, "registre"):
        ctx.origin = "registre"
    if plan.pinned and plan.lang == "python":
        repin_python(plan)


def make_plan(root: Path, use_lock: bool = True, project: str | None = None, cmd: str | None = None) -> Context:
    repo_root = root
    root, plan = resolve_project(root, project)     # monorepo : peut descendre dans un sous-dossier
    if not project and not cmd and root == repo_root:
        _note_multistack(plan, repo_root)
    if cmd:
        plan.run, plan.processes, plan.choices = cmd, {}, []
        plan.notes.append("commande imposée par --cmd")
    _fill_missing_command(root, plan)
    services = detect_services(root)
    gpu = gpumod.detect_gpu() if plan.ai_libs else {"vendor": None, "name": None, "cuda": None}
    ctx = Context(root, plan, services, gpu, fingerprint(root))
    if plan.ai_libs:
        plan.notes += gpumod.describe(plan.ai_libs, gpu) + gpumod.model_notes(root)
    if use_lock:
        _apply_lock_or_registry(ctx, root)
    libs = system_libs(root)
    if libs:
        plan.notes.append("paquets système cités par le dépôt : " + "; ".join(f"{k}: {' '.join(v)}" for k, v in libs.items()))
    return ctx


def print_plan(ctx: Context) -> None:
    p = ctx.plan
    print(f"\n\033[1mPlan pour {ctx.root.name}\033[0m  (empreinte {ctx.fp})")
    print(f"  langage   : {p.lang}")
    print(f"  version   : {p.pinned or p.version or 'dernière stable'}  ({p.source})")
    if ctx.origin and ctx.drift:
        print(f"  \033[33mdérive    : modifié depuis le freeze → {', '.join(ctx.drift)}\033[0m")
    for s in p.install:
        print(f"  installer : {s}")
    if p.processes:
        for n, c in p.processes.items():
            print(f"  process   : {n}: {c}")
    else:
        print(f"  lancer    : {p.run or '??? (aucune commande principale trouvée)'}")
        for c in p.choices[:8]:
            print(f"  choix     : {c}")
    for s in ctx.services:
        mode = "réutilisé" if s.reuse else f"conteneur {s.image}"
        print(f"  service   : {s.kind} → localhost:{s.port} ({mode}; via {', '.join(s.sources)})")
    for n in p.notes:
        print(f"  note      : {n}")
    print()


# ───────────────────────────── run ─────────────────────────────

def _env_file_keys(root: Path) -> set[str]:
    f = root / ".env"
    if not f.is_file():
        return set()
    return set(re.findall(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=", f.read_text(errors="ignore"), re.M))


def _apply_fix(fix: Fix, root: Path, env: dict) -> None:
    log(f"correctif automatique : {fix.description}")
    for c in fix.commands:
        sh(c, root, env, check=False)
    env.update(fix.env)


def _downgrade_python(ctx: Context, version: str, reason: str | None = None) -> dict:
    """Recrée l'environnement Python avec une autre version (le venv existant a la mauvaise) ; retourne l'env."""
    root, plan = ctx.root, ctx.plan
    log(reason or f"correctif automatique : un module retiré de Python 3.12 est requis "
        f"(version : {plan.version or 'dernière stable'}) → Python {version}")
    journal(root.name, {"fix": "python version downgrade", "from": plan.version, "to": version})
    shutil.rmtree(venv_dir(root), ignore_errors=True)
    plan.version, plan.install = version, detect_python(root, version_override=version).install
    return ENSURE[plan.lang](plan, root, dict(os.environ))


@dataclass
class InstallState:
    """État de la boucle d'installation, partagé par les correctifs (chacun peut modifier l'environnement, le plan et `applied`)."""
    ctx: Context
    env: dict
    applied: set[str] = field(default_factory=set)
    step: str = ""             # étape qui vient d'échouer
    tail: str = ""             # sa sortie (début et fin)

    @property
    def root(self) -> Path:
        return self.ctx.root

    @property
    def plan(self) -> Plan:
        return self.ctx.plan

    def once(self, key: str) -> bool:
        """Vrai la première fois seulement pour cette clé (chaque correctif n'est tenté qu'une fois) ; la mémorise."""
        if key in self.applied:
            return False
        self.applied.add(key)
        return True

    def announce(self, message: str, **journal_fields) -> None:
        log("correctif automatique : " + message)
        journal(self.root.name, journal_fields)


def _run_install_steps(ctx: Context, env: dict) -> tuple[str, str] | None:
    """Lance les étapes d'installation ; retourne (étape, sortie) de la première qui échoue, ou None si tout passe."""
    for step in ctx.plan.install:
        code, tail = run_tee(step, ctx.root, env)
        if code and step in ctx.plan.optional_steps:
            warn(f"étape facultative échouée, on continue : {step.split(' ', 2)[-1][:100]}")
            continue
        if code:
            return step, tail
    return None


def _tmp_requirements(root: Path, lines: list[str]) -> Path:
    """Fichier de dépendances temporaire (le dépôt reste inchangé) : `~/.zero/envs/<venv>.requirements.txt`."""
    tmp = zero_home() / "envs" / f"{venv_dir(root).name}.requirements.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("\n".join(lines) + "\n")
    return tmp


def _use_requirements(plan: Plan, req: str, tmp: Path) -> None:
    plan.install = [s.replace(f"-r {q(req)}", f"-r {q(str(tmp))}") for s in plan.install]


# Un correctif d'installation reçoit l'état et retourne vrai s'il a agi (on relance alors l'installation) ; faux pour passer au suivant.
# L'ORDRE de INSTALL_FIXERS compte : il est celui des priorités (variables d'environnement, version de Python, psycopg2, Node, puis étapes à ignorer).

def _fix_corepack(st: InstallState) -> bool:
    cp = diagnose_corepack(st.tail)
    if not cp or not st.once("corepack-registry"):
        return False
    st.announce(f"corepack n'atteint pas repo.yarnpkg.com → téléchargement depuis le registre npm ({cp['COREPACK_NPM_REGISTRY']})",
                fix="COREPACK_NPM_REGISTRY", registry=cp["COREPACK_NPM_REGISTRY"])
    st.env = {**st.env, **cp}
    return True


def _fix_scm_version(st: InstallState) -> bool:
    pretend = diagnose_scm_version(st.plan, st.tail)
    if not pretend or not st.once("scm-pretend"):
        return False
    st.announce("la version du projet est calculée depuis git (setuptools-scm / hatch-vcs) et l'historique manque (clone superficiel) "
                "→ version imposée 0.0.0", fix="scm pretend version", env=sorted(pretend))
    st.env = {**st.env, **pretend}
    return True


def _fix_python_patch(st: InstallState) -> bool:
    patch = diagnose_python_patch(st.plan, st.tail)
    if not patch or not st.once(f"python-patch-{patch}"):
        return False
    st.env = _downgrade_python(st.ctx, patch, f"correctif automatique : Python {st.plan.version} indisponible avec uv "
                                              f"(dernier correctif seulement, ou version trop ancienne) → Python {patch}")
    return True


def _fix_python_version(st: InstallState) -> bool:
    py_needed = diagnose_python_install(st.plan, st.tail)
    if not py_needed or not st.once(f"python-{py_needed}"):
        return False
    cap, pin = abi_cap(st.tail), old_pin_build_failure(st.tail)
    if cap is not None:
        reason = f"correctif automatique : un paquet n'a pas de roue pour ce Python (publiées jusqu'à 3.{cap}) → Python {py_needed}"
    elif pin:
        reason = f"correctif automatique : l'ancien paquet épinglé {pin[0]}=={pin[1]} ne se construit pas sur ce Python → Python {py_needed}"
    else:
        reason = None                                  # message par défaut : un module retiré de Python est requis
    st.env = _downgrade_python(st.ctx, py_needed, reason)
    # le venv est neuf et le plan recalculé : les autres correctifs (psycopg2, version imposée…) sont à refaire
    st.applied = {k for k in st.applied if k.startswith("python-")}
    return True


def _fix_psycopg2_swap(st: InstallState) -> bool:
    """libpq absente : psycopg2 → psycopg2-binary. Sans effet si le fichier est déjà en `-binary` : on passe alors au retrait du pin."""
    req = requirements_file(st.root)
    if "psycopg2" in st.applied or not req or not diagnose_psycopg2(st.plan, st.tail):
        return False
    st.applied.add("psycopg2")
    lines = flatten_requirements(st.root / req)
    swapped = swap_psycopg2(lines)
    if swapped == lines:
        return False
    tmp = _tmp_requirements(st.root, swapped)
    st.announce(f"libpq absente → psycopg2-binary (dépôt inchangé, fichier : {tmp})",
                fix="psycopg2 -> psycopg2-binary", requirements=str(tmp))
    _use_requirements(st.plan, req, tmp)
    return True


def _fix_psycopg2_unpin(st: InstallState) -> bool:
    """psycopg2-binary épinglé sans roue pour ce Python : on retire le pin."""
    req = requirements_file(st.root)
    if "psycopg2" not in st.applied or "psycopg2-unpin" in st.applied or not req:
        return False
    if not (psycopg2_pin_unsatisfiable(st.tail) or diagnose_psycopg2(st.plan, st.tail)):
        return False
    st.applied.add("psycopg2-unpin")
    tmp = _tmp_requirements(st.root, swap_psycopg2(flatten_requirements(st.root / req), keep_version=False))
    _use_requirements(st.plan, req, tmp)
    st.announce(f"pas de binaire psycopg2 pour la version épinglée → pin retiré pour psycopg2-binary (dépôt inchangé, fichier : {tmp})",
                fix="psycopg2-binary unpinned", requirements=str(tmp))
    return True


def _fix_node_version(st: InstallState) -> bool:
    needed = diagnose_install(st.plan, st.tail)
    if not needed or not st.once("node"):
        return False
    st.announce(f"une dépendance exige Node {needed} (dépôt : {st.plan.version}) → changement de version",
                fix="node version bump", **{"from": st.plan.version, "to": needed})
    st.plan.version, st.plan.pinned = needed, None
    st.env = ENSURE[st.plan.lang](st.plan, st.root, dict(os.environ))
    return True


def _fix_dev_engines(st: InstallState) -> bool:
    """`devEngines.packageManager` exige un npm plus récent : on l'installe dans un dossier dédié placé en tête du PATH."""
    npm_range = diagnose_dev_engines(st.tail)
    if not npm_range or not st.once("dev-engines"):
        return False
    st.announce(f"le dépôt exige npm {npm_range} (devEngines) → installation de cet npm dans le runtime",
                fix="npm version from devEngines", range=npm_range)
    dest = zero_home() / "runtimes" / ("npm-" + re.sub(r"[^\w.]+", "_", npm_range))
    dest.mkdir(parents=True, exist_ok=True)
    code, _ = run_tee(f"npm install --prefix {q(str(dest))} {q('npm@' + npm_range)} --no-audit --no-fund",
                      dest, st.env)                    # hors du dépôt : npm y relirait devEngines
    if code == 0 and (dest / "node_modules" / ".bin" / "npm").exists():
        st.env = with_path(st.env, dest / "node_modules" / ".bin")      # ce npm passe devant celui du Node
        return True
    return False                                       # échec : on essaie les correctifs suivants


def _replace_step(st: InstallState, new_step: str) -> None:
    st.plan.install = [new_step if s == st.step else s for s in st.plan.install]


def _fix_npm_ci(st: InstallState) -> bool:
    new_step = diagnose_npm_ci(st.step, st.tail)
    if not new_step or not st.once(f"npm-ci:{new_step}"):
        return False
    st.announce(f"`npm ci` échoue (lockfile désynchronisé, miroir inaccessible ou conflit de dépendances) → `{new_step}`",
                fix="npm ci fallback", to=new_step)
    _replace_step(st, new_step)
    return True


def _fix_node_scripts(st: InstallState) -> bool:
    new_step = diagnose_node_scripts(st.step, st.tail)
    if not new_step or not st.once(f"ignore-scripts:{st.step}"):
        return False
    st.announce(f"un script d'installation (postinstall…) échoue → `{new_step}` (les modules natifs à compiler ne fonctionneront pas)",
                fix="ignore install scripts", to=new_step)
    _replace_step(st, new_step)
    return True


def _drop_step(st: InstallState) -> None:
    st.plan.install = [s for s in st.plan.install if s != st.step]


def _fix_soft_pins(st: InstallState) -> bool:
    """Étape « versions épinglées du lock » inutilisable : on la saute si une autre étape (setup.py/pyproject) suit."""
    plan = st.plan
    if st.step not in plan.soft_steps or plan.install.index(st.step) >= len(plan.install) - 1 or not st.once("soft-pins"):
        return False
    st.announce("versions épinglées de Pipfile.lock inutilisables sur ce Python → ignorées, les dépendances du projet "
                "(setup.py / pyproject) suffisent", fix="skip pinned Pipfile.lock step", step=st.step[:200])
    _drop_step(st)
    return True


def _fix_self_install(st: InstallState) -> bool:
    if not optional_self_install(st.plan, st.step) or not st.once("self-install"):
        return False
    st.announce("l'installation du projet lui-même (-e .) échoue alors que ses dépendances sont installées → ignorée "
                "(application lancée depuis ses sources)", fix="skip editable self-install", step=st.step)
    _drop_step(st)
    return True


INSTALL_FIXERS = (_fix_corepack, _fix_scm_version, _fix_python_patch, _fix_python_version, _fix_psycopg2_swap, _fix_psycopg2_unpin,
                  _fix_node_version, _fix_dev_engines, _fix_npm_ci, _fix_node_scripts, _fix_soft_pins, _fix_self_install)


def install_deps(ctx: Context, env: dict, recover: bool) -> dict:
    """Installe les dépendances. Quand une étape échoue, les correctifs automatiques de `INSTALL_FIXERS` sont essayés dans l'ordre
    (chacun une seule fois, journalisé) puis l'installation est relancée, jusqu'à 8 tours."""
    log("installation des dépendances")
    st = InstallState(ctx, env)
    for _ in range(8):
        failed = _run_install_steps(ctx, st.env)
        if not failed:
            return st.env
        st.step, st.tail = failed
        if not recover:
            die(f"commande échouée : {st.step}")
        if any(fixer(st) for fixer in INSTALL_FIXERS):
            continue
        if ctx.plan.lang == "python" and (hint := python2_hint(st.tail)):
            warn(hint)
        die(f"commande échouée : {st.step}")
    die("installation impossible après les correctifs automatiques")


def optional_self_install(plan: Plan, step: str) -> bool:
    """Étape `pip install -e .` du projet lui-même, précédée d'une étape qui installe déjà un requirements.

    Un dépôt d'application n'est souvent pas un paquet installable (pyproject d'outillage) :
    ses dépendances suffisent pour le lancer depuis ses sources."""
    if plan.lang != "python" or not re.search(r"\s-e \.$", step) or step not in plan.install:
        return False
    return any(" -r " in earlier for earlier in plan.install[:plan.install.index(step)])


def should_migrate(root: Path, plan: Plan, services: list, svc_env: dict[str, str]) -> bool:
    """Django + une base gérée par zero (Postgres/MySQL) + aucune commande qui migre déjà.

    Sans base de zero (SQLite, base externe) on ne touche à rien : la migration créerait ou
    modifierait des données qu'on ne maîtrise pas."""
    if plan.lang != "python" or not find_manage_py(root) or "django" not in dep_text(root):
        return False
    if not any(s.kind in ("postgres", "mysql") for s in services) or not svc_env:
        return False
    commands = list((plan.processes or {}).values()) + [plan.run or ""]
    return not any("migrate" in c for c in commands)


def run_django_migrate(root: Path, env: dict) -> bool:
    """`manage.py migrate --noinput` sur la base de zero. Un échec avertit sans interrompre le lancement."""
    py = venv_dir(root) / "bin" / "python"
    log("migrations Django (base de zero)")
    try:
        r = subprocess.run([str(py if py.exists() else "python"), find_manage_py(root) or "manage.py", "migrate", "--noinput"],
                           cwd=root, env=env, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        warn(f"migrate impossible : {e}")
        return False
    if r.returncode:
        warn("migrate a échoué (le lancement continue) : " + (r.stderr or r.stdout).strip().splitlines()[-1][:200]
             if (r.stderr or r.stdout).strip() else "migrate a échoué (le lancement continue)")
        return False
    return True


def migrate_stack(c: Context, env: dict, svc_env: dict[str, str]) -> bool:
    """Migrations Django d'une stack (mode --all) ; vrai si la commande a été lancée avec succès."""
    return should_migrate(c.root, c.plan, c.services, svc_env) and run_django_migrate(c.root, env)


def append_run_args(ctx: Context, extra: list[str]) -> None:
    """Arguments de l'utilisateur (`zero run dépôt -- …`) ajoutés, protégés, à la commande principale."""
    if not ctx.plan.run:
        raise ZeroError("pas de commande principale à laquelle passer des arguments ; utilisez --cmd")
    if ctx.plan.processes:
        warn("arguments ignorés : le projet se lance par un Procfile (plusieurs processus)")
        return
    run = ctx.plan.run
    # npm garde pour lui les options qui suivent `npm run x` : il faut `--` pour qu'elles atteignent le script
    sep = " --" if re.match(r"^npm (?:run|run-script|start|test)\b", run) and " -- " not in f"{run} " else ""
    ctx.plan.run = run + sep + " " + " ".join(q(a) for a in extra)


def _prepare_environment(ctx: Context, recover: bool) -> dict:
    """Runtime isolé, variables GPU/IA, installation des dépendances : l'environnement dans lequel le projet sera lancé."""
    env = ENSURE[ctx.plan.lang](ctx.plan, ctx.root, dict(os.environ))
    env.update(gpumod.build_env(ctx.plan.ai_libs, ctx.gpu))
    return install_deps(ctx, env, recover)


def _setup_run_environment(ctx: Context, env: dict, mgr: ServiceManager | None) -> None:
    """Démarre les services, leur donne leurs variables (jamais par-dessus le .env ni l'environnement de l'utilisateur), attribue un
    PORT par défaut aux Procfile et applique les migrations Django. Modifie `env` en place."""
    root, plan = ctx.root, ctx.plan
    pre_keys = _env_file_keys(root)
    svc_env = mgr.start() if mgr else {}
    report_env(fill_env(root, svc_env))
    for k, v in svc_env.items():
        if k not in pre_keys and k not in os.environ:
            env[k] = v
    if plan.processes:
        env.setdefault("PORT", str(free_port(8000)))
    if should_migrate(root, plan, ctx.services if mgr else [], svc_env):
        run_django_migrate(root, env)


def _retry_with_other_python(ctx: Context, tail: str, applied: set[str], recover: bool) -> dict | None:
    """Erreur qui se règle en changeant de version de Python (ex. vieux gunicorn/six sur Python ≥ 3.12) : le nouvel environnement, ou None.
    Hors budget : chaque palier (3.11, 3.10, 3.9) n'est tenté qu'une fois. Le venv est neuf : les autres correctifs sont à refaire."""
    py_needed = diagnose_python_install(ctx.plan, tail) if recover else None
    if not py_needed or f"python-{py_needed}" in applied:
        return None
    applied.add(f"python-{py_needed}")
    env = install_deps(ctx, _downgrade_python(ctx, py_needed), recover)
    applied.intersection_update({k for k in applied if k.startswith("python-")})
    return env


def _apply_run_fixes(ctx: Context, tail: str, env: dict, applied: set[str], recover: bool, attempts: int) -> bool:
    """Diagnostique l'échec : signale les actions manuelles et applique les correctifs automatiques. Vrai s'il faut relancer."""
    fixes = diagnose(ctx.plan, ctx.root, tail, applied)
    for f in (f for f in fixes if f.manual):
        warn(f"action manuelle : {f.description} → {f.manual}")
    auto = [f for f in fixes if f.automatic]
    if not recover or attempts >= MAX_ATTEMPTS or not auto:
        return False
    for f in auto:
        _apply_fix(f, ctx.root, env)
        applied.add(f.key)
        journal(ctx.root.name, {"fix": f.description, "commands": f.commands, "env": f.env})
    return True


def _supervise(ctx: Context, env: dict, recover: bool):
    """Lance le projet et le relance après correctif tant que c'est utile. Retourne (résultat, succès, correctifs appliqués, environnement final)."""
    plan = ctx.plan
    applied: set[str] = set()
    attempts = 0
    while True:
        commands = plan.processes or {"main": plan.run}
        log(f"lancement : {' | '.join(commands.values())}")
        res = Supervisor(ctx.root, env).run(commands)
        success = res.code == 0 or (res.interrupted and res.uptime >= 10)
        if success or res.interrupted:
            return res, success, applied, env
        if (new_env := _retry_with_other_python(ctx, res.tail, applied, recover)) is not None:
            env, attempts = new_env, 0
            log("nouvelle tentative (version de Python)")
            continue
        if not _apply_run_fixes(ctx, res.tail, env, applied, recover, attempts):
            return res, success, applied, env
        attempts += 1
        log(f"nouvelle tentative ({attempts}/{MAX_ATTEMPTS})")


def _report_outcome(ctx: Context, res, success: bool, applied: set[str]) -> None:
    """Explications après un échec (Python 2, outil en ligne de commande) et rappel du journal des correctifs."""
    if not success and not res.interrupted and ctx.plan.lang == "python" and (hint := python2_hint(res.tail)):
        warn(hint)
    if not res.interrupted and (hint := cli_tool_hint(res.tail, res.uptime)):
        log(hint)
    if applied:
        log(f"{len(applied)} correctif(s) appliqué(s) — journal : ~/.zero/logs/{ctx.root.name}.jsonl")


def _record_success(ctx: Context, env: dict) -> None:
    lock = build_lock(ctx.root, ctx.plan, ctx.services, ctx.gpu, installed_version(ctx.plan, ctx.root, env))
    lock["fingerprint"] = ctx.fp          # empreinte d'avant installation
    record(ctx.fp, lock)


def run_project(ctx: Context, recover: bool = True, with_services: bool = True, services_mode: str = "auto") -> int:
    """Installe, démarre les services, lance le projet sous supervision (avec relances après correctif) et retourne son code de sortie."""
    plan = ctx.plan
    if not plan.run:
        hint = f" — choix possibles : {' | '.join(plan.choices)}" if plan.choices else ""
        die("pas de commande principale détectée ; utilisez --cmd" + hint)
    env = _prepare_environment(ctx, recover)
    mgr = ServiceManager(ctx.root.name, ctx.services, services_mode) if with_services and ctx.services else None
    try:
        _setup_run_environment(ctx, env, mgr)
        res, success, applied, env = _supervise(ctx, env, recover)
        _report_outcome(ctx, res, success, applied)
        if success:
            _record_success(ctx, env)
            return 0
        return res.code
    finally:
        if mgr:
            mgr.stop()


# ───────────────────────────── freeze / share ─────────────────────────────

def _resolve_version(plan: Plan, root: Path, env: dict) -> str | None:
    v = installed_version(plan, root, env)
    if v or plan.lang != "python":
        return v
    spec = plan.pinned or plan.version
    cmd = ["uv", "python", "find"] + ([spec] if spec else [])
    try:
        path = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30).stdout.strip()
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10).stdout
        return out.replace("Python ", "").strip() or None
    except Exception:
        return None


def freeze_project(ctx: Context) -> Path:
    plan, root = ctx.plan, ctx.root
    env = ENSURE[plan.lang](plan, root, dict(os.environ))
    resolved = _resolve_version(plan, root, env)
    if not resolved:
        warn("version exacte non résolue : le lock contiendra seulement la contrainte demandée")
    lock = build_lock(root, plan, ctx.services, ctx.gpu, resolved)
    path = write_lock(root, lock)
    log(f"{LOCK_NAME} écrit : {plan.lang} {resolved or plan.version}, "
        f"{len(ctx.services)} service(s), {len(lock['env']['keys'])} variable(s) d'env")
    return path


def share_project(ctx: Context) -> Path:
    freeze_project(ctx)
    bundle = create_bundle(ctx.root)
    log(f"bundle prêt : {bundle}")
    log(f"destinataire : zero {bundle.name}")
    return bundle


# ───────────────────────────── multi-stack (--all) ─────────────────────────────

def find_stacks(repo: Path, use_lock: bool = True) -> list[Context]:
    stacks = detect_stacks(repo)
    if len(stacks) < 2:
        die("--all : moins de deux stacks de langages différents détectées "
            "(cherché : racine, backend/, frontend/, server/, client/, api/, web/, app/, ui/, worker/, aussi sous src/, app/, apps/)")
    ctxs = []
    for name, d, _ in stacks:
        c = make_plan(d, use_lock=use_lock)
        c.name = name
        ctxs.append(c)
    return ctxs


PREFERRED_PORTS = {"node": 3000, "python": 8000, "go": 8080, "rust": 8080}


def assign_ports(ctxs: list[Context], envs: list[dict]) -> dict[str, int]:
    """Donne un PORT distinct à chaque stack (sauf si l'utilisateur ou le .env en fixe déjà un)."""
    used: set[int] = set()
    out: dict[str, int] = {}
    for c, env in zip(ctxs, envs):
        if "PORT" in os.environ or "PORT" in _env_file_keys(c.root):
            continue
        port = PREFERRED_PORTS.get(c.plan.lang, 8000)
        while port in used or port_open(port):
            port += 1
        used.add(port)
        env["PORT"] = str(port)
        out[c.name] = port
    return out


BACKEND_STACKS = ("backend", "server", "api")
FRONTEND_STACKS = ("frontend", "client", "web", "ui", "app")
API_URL_VARS = ("BACKEND_URL", "API_URL", "VITE_API_URL", "VITE_BACKEND_URL", "NEXT_PUBLIC_API_URL", "REACT_APP_API_URL")


def link_stacks(ctxs: list[Context], envs: list[dict], ports: dict[str, int]) -> dict[str, str]:
    """Donne à chaque stack frontend l'URL du backend (variables usuelles), sans écraser l'existant.

    Ne s'applique que si le backend a reçu un PORT de zero (sinon son port est inconnu). C'est une convention :
    elle n'a d'effet que si le frontend lit l'une de ces variables et que le backend lit PORT."""
    back = next((c.name for c in ctxs if c.name in BACKEND_STACKS and c.name in ports), None)
    if back is None:
        return {}
    url = f"http://localhost:{ports[back]}"
    linked: dict[str, str] = {}
    for c, env in zip(ctxs, envs):
        if c.name not in FRONTEND_STACKS:
            continue
        pre = _env_file_keys(c.root)
        for var in API_URL_VARS:
            if var not in pre and var not in os.environ:
                env[var] = url
        linked[c.name] = url
    return linked


def _install_stacks(ctxs: list[Context], recover: bool) -> list[dict]:
    """Installe chaque stack dans son propre runtime ; retourne l'environnement de chacune."""
    envs = []
    for c in ctxs:
        env = ENSURE[c.plan.lang](c.plan, c.root, dict(os.environ))
        env.update(gpumod.build_env(c.plan.ai_libs, c.gpu))
        log(f"── stack « {c.name} » ({c.plan.lang})")
        envs.append(install_deps(c, env, recover))
    return envs


def _shared_services(ctxs: list[Context]) -> dict[str, Service]:
    """Un seul service par type pour tout le dépôt (le premier déclaré gagne : un seul Postgres)."""
    services: dict[str, Service] = {}
    for c in ctxs:
        for s in c.services:
            services.setdefault(s.kind, s)
    return services


def _wire_stacks(ctxs: list[Context], envs: list[dict], svc_env: dict[str, str]) -> dict:
    """Ports distincts, URL du backend pour le frontend, variables des services (jamais par-dessus le .env d'une stack ni l'environnement
    du processus), migrations Django ; retourne les commandes à superviser, clés = 8 premières lettres du nom de la stack."""
    ports = assign_ports(ctxs, envs)
    if ports:
        log("ports : " + ", ".join(f"{n}={p}" for n, p in ports.items()))
    for n, url in link_stacks(ctxs, envs, ports).items():
        log(f"« {n} » reçoit l'URL du backend : {url} ({', '.join(API_URL_VARS)})")
    commands = {}
    for c, env in zip(ctxs, envs):
        pre_keys = _env_file_keys(c.root)
        report_env(fill_env(c.root, svc_env))
        for k, v in svc_env.items():
            if k not in pre_keys and k not in os.environ:
                env[k] = v
        migrate_stack(c, env, svc_env)
        commands[c.name[:8]] = (c.plan.run, c.root, env)
    return commands


def run_stacks(repo: Path, ctxs: list[Context], recover: bool = True, with_services: bool = True,
               services_mode: str = "auto") -> int:
    """Installe chaque stack dans son propre runtime, partage les services, lance tout sous un seul superviseur."""
    envs = _install_stacks(ctxs, recover)
    services = _shared_services(ctxs)
    mgr = ServiceManager(repo.name, list(services.values()), services_mode) if with_services and services else None
    try:
        svc_env = mgr.start() if mgr else {}
        commands = _wire_stacks(ctxs, envs, svc_env)
        log("lancement : " + " | ".join(f"{n}: {spec[0]}" for n, spec in commands.items()))
        res = Supervisor(repo, dict(os.environ)).run(commands)
        if res.failed and not res.interrupted:
            warn(f"« {res.failed} » s'est arrêté (code {res.code}) : les autres stacks ont été arrêtées. "
                 "La récupération automatique n'est pas appliquée en mode --all.")
        return 0 if res.code == 0 or (res.interrupted and res.uptime >= 10) else res.code
    finally:
        if mgr:
            mgr.stop()
