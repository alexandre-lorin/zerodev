"""Benchmark public : détection, build, lancement, temps jusqu'au premier run, interventions."""
from __future__ import annotations

import json
import os
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import procs
from .util import zero_home
from pathlib import Path

from .core import make_plan
from .plan import AmbiguousProject
from .util import ZeroError, log


def read_corpus(path: Path) -> list[str]:
    entries = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    return entries


def _materialize(entry: str, workdir: Path) -> tuple[Path | None, float, str | None]:
    """Clone (URL) ou résolution (chemin). Retourne (dossier, secondes, erreur)."""
    t0 = time.time()
    if re.match(r"^(https?://|git@)", entry):
        parts = re.sub(r"\.git$", "", entry.rstrip("/")).split("/")
        dest = workdir / f"{parts[-2]}__{parts[-1]}"      # owner__repo : évite les collisions (cli, examples…)
        if not dest.exists():
            try:
                r = subprocess.run(["git", "clone", "--depth", "1", "--single-branch", "--quiet", entry, str(dest)],
                                   capture_output=True, text=True, timeout=300,
                                   env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
            except subprocess.TimeoutExpired:
                return None, time.time() - t0, "clone : délai dépassé (300 s)"
            if r.returncode:
                return None, time.time() - t0, f"clone : {r.stderr.strip()[:120]}"
        return dest, time.time() - t0, None
    p = Path(entry).resolve()
    return (p, 0.0, None) if p.is_dir() else (None, 0.0, "dossier introuvable")


def listening_ports(pid: int) -> list[int]:
    """Ports TCP en écoute ouverts par l'arbre de processus de `pid`."""
    inodes: set[str] = set()
    for q in procs.descendants(pid):
        try:
            for fd in Path(f"/proc/{q}/fd").iterdir():
                try:
                    m = re.match(r"socket:\[(\d+)\]", os.readlink(fd))
                except OSError:
                    continue
                if m:
                    inodes.add(m.group(1))
        except OSError:
            continue
    ports: set[int] = set()
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = Path(f).read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            c = row.split()
            if len(c) > 9 and c[3] == "0A" and c[9] in inodes:
                ports.add(int(c[1].rsplit(":", 1)[1], 16))
    return sorted(ports)


def http_probe(ports: list[int]) -> dict | None:
    """Premier port qui répond en HTTP (tout code, même 404/500 : le serveur parle HTTP)."""
    import urllib.error
    import urllib.request
    for port in ports:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
                return {"port": port, "status": r.status}
        except urllib.error.HTTPError as e:
            return {"port": port, "status": e.code}
        except Exception:
            continue
    return None


def _run_full(root: Path, timeout: int) -> dict:
    """Lance `zero run` et mesure build / launch / ttfr / interventions."""
    marks: dict[str, float] = {}
    counts = {"auto": 0, "manual": 0}
    lines: list[str] = []
    t0 = time.time()
    p = subprocess.Popen(
        [sys.executable, "-m", "zerodev", "run", str(root)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        errors="replace", start_new_session=True, env=dict(os.environ, PYTHONUNBUFFERED="1",
                 PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parent.parent), os.environ.get("PYTHONPATH", "")])),
    )

    def pump() -> None:
        assert p.stdout
        for line in p.stdout:
            lines.append(line)
            if "lancement :" in line and "launch" not in marks:
                marks["launch"] = time.time() - t0
            counts["auto"] += "correctif automatique" in line
            counts["manual"] += "action manuelle" in line

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        p.wait(timeout=timeout)
        alive, ports, probe = False, [], None
    except subprocess.TimeoutExpired:
        alive = True
        ports = listening_ports(p.pid)
        probe = http_probe(ports)
        for sig in (signal.SIGINT, signal.SIGTERM):   # arrêt propre : le superviseur nettoie ses enfants
            p.send_signal(sig)
            try:
                p.wait(timeout=15)
                break
            except subprocess.TimeoutExpired:
                continue
        else:
            os.killpg(p.pid, signal.SIGKILL)
    t.join(timeout=3)
    built = "launch" in marks
    phase = "run" if built else ("install_timeout" if alive else "install_failed")
    after = "".join(lines)[(lambda i: i if i >= 0 else 0)("".join(lines).find("lancement :")):]
    cli_tool = bool(built and not alive and CLI_HELP.search(after))        # a affiché son aide puis quitté : pas un serveur
    return {
        "phase": phase,
        "cli_tool": cli_tool,
        "built": built,
        "launched": built and (alive or p.returncode == 0),
        "ttfr_s": round(marks["launch"], 1) if built else None,
        "listening_ports": ports,
        "http": probe,
        "interventions_auto": counts["auto"],
        "interventions_manual": counts["manual"],
        "exit_code": None if alive else p.returncode,
        "tail": "".join(lines[-5:]).strip()[-300:],
    }


from .recovery import CLI_HELP      # noqa: E402  (même heuristique que le message de zero run)




def classify(root: Path | None, err: str | None) -> dict:
    """Statut de détection d'un dépôt (sans rien exécuter)."""
    if root is None:
        return {"status": "clone_failed", "error": err}
    try:
        ctx = make_plan(root, use_lock=False)
    except AmbiguousProject as e:
        return {"status": "ambiguous_monorepo", "candidates": e.candidates, "multistack": bool(getattr(e, "multistack", False))}
    except ZeroError as e:
        return {"status": "unsupported", "error": str(e)}
    except Exception as e:      # un dépôt exotique ne doit jamais interrompre tout le benchmark (bug de zero, à corriger)
        return {"status": "detector_error", "error": f"{type(e).__name__}: {e}"}
    row = {"lang": ctx.plan.lang, "version": ctx.plan.version, "version_source": ctx.plan.source, "run": ctx.plan.run,
           "subproject": str(ctx.root.relative_to(root)) if ctx.root != root else None,
           "services": [s.kind for s in ctx.services], "ai_libs": ctx.plan.ai_libs}
    row["run_inferred"] = any("déduite du Makefile" in n for n in ctx.plan.notes)
    row["deps_deduced"] = any("DÉDUITES" in n for n in ctx.plan.notes)
    row["entry_from_docs"] = any(n.startswith("point d'entrée choisi d'après") for n in ctx.plan.notes)
    row["status"] = "runnable" if ctx.plan.run else ("ambiguous_entrypoint" if ctx.plan.choices else "no_run_command")
    if ctx.plan.choices:
        row["choices"] = ctx.plan.choices[:8]
    return row


def wait_for_disk(path: Path, min_mb: int = 700, max_wait: float = 120.0) -> bool:
    """Détection en parallèle : attend que d'autres clones soient libérés plutôt que de cloner sur un disque presque plein
    (un clone échoué faute d'espace serait pris pour un défaut du dépôt)."""
    import shutil
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if shutil.disk_usage(path).free // (1024 * 1024) >= min_mb:
            return True
        time.sleep(2)
    return False


def _detect_and_clean(entry: str, workdir: Path) -> dict:
    """Détection seule : clone, classe, puis supprime le clone (un corpus de 500 dépôts ne tient pas sur disque)."""
    import shutil
    wait_for_disk(workdir)
    root, clone_s, err = _materialize(entry, workdir)
    row: dict = {"repo": entry, "clone_s": round(clone_s, 1)}
    try:
        row.update(classify(root, err))
    finally:
        if root is not None and re.match(r"^(https?://|git@)", entry):
            shutil.rmtree(root, ignore_errors=True)
    row["detected"] = row["status"] == "runnable"
    return row


def ensure_disk(min_mb: int = 900) -> bool:
    """Vrai si assez d'espace libre ; sinon vide les caches (uv, npm, runtimes Node de repli) puis revérifie."""
    import shutil

    def free() -> int:
        probe = zero_home()
        while not probe.exists() and probe != probe.parent:      # ~/.zero peut ne pas exister encore
            probe = probe.parent
        return shutil.disk_usage(probe).free // (1024 * 1024)
    if free() >= min_mb:
        return True
    home = Path.home()
    for d in (home / ".cache" / "uv", home / ".npm" / "_cacache", zero_home() / "envs",
              home / ".local" / "share" / "pnpm",          # magasin global de pnpm : plusieurs Go après quelques dépôts
              home / ".bun" / "install" / "cache", home / ".cache" / "yarn", home / ".yarn" / "cache"):
        shutil.rmtree(d, ignore_errors=True)
    for rt in (zero_home() / "runtimes").glob("node-npm-*"):
        shutil.rmtree(rt, ignore_errors=True)
    return free() >= min_mb


def disk_failure(row: dict) -> bool:
    """Échec d'installation dû à un disque plein (et non au dépôt) : ENOSPC / « No space left on device »."""
    return row.get("phase") == "install_failed" and bool(
        re.search(r"ENOSPC|No space left on device|database or disk is full|disk is full|Disque plein", row.get("tail") or "", re.I))


def _cleanup(root: Path) -> None:
    import shutil
    from .plan import venv_dir
    try:
        shutil.rmtree(venv_dir(root), ignore_errors=True)
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)
    for rt in (zero_home() / "runtimes").glob("node-npm-*"):      # ~185 Mo par version de Node en repli npm
        shutil.rmtree(rt, ignore_errors=True)


def _checkpoint(out: Path, results: list[dict], full: bool) -> None:
    """Rapport partiel après chaque dépôt : un benchmark interrompu ne perd plus ses résultats."""
    tmp = out.with_suffix(out.suffix + ".tmp")          # écriture atomique : un disque plein ne corrompt plus le rapport
    tmp.write_text(json.dumps({"summary": summarize(results, full), "results": results, "partial": True},
                              indent=1, ensure_ascii=False))
    tmp.replace(out)


def _log_row(row: dict) -> None:
    mark = "✓" if row["detected"] else "✗"
    extra = row.get("error") or (", ".join(row["candidates"][:4]) if row.get("candidates") else row["status"])
    log(f"{mark} {row['repo']} — {row.get('lang', '?')} / {extra if not row['detected'] else row['run']}")


def run_bench(corpus: Path, workdir: Path, full: bool, timeout: int, out: Path, jobs: int = 4) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    entries = read_corpus(corpus)
    results = []
    stopped = False
    if not full:                                    # détection seule : en flux, clones supprimés au fur et à mesure
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            for row in pool.map(lambda e: _detect_and_clean(e, workdir), entries):
                results.append(row)
                _log_row(row)
    else:                                           # lancement réel : un dépôt à la fois (ports, disque), clone → run → nettoyage
        for entry in entries:
            if os.environ.get("ZERO_BENCH_CLEANUP") and not ensure_disk():
                log("espace disque insuffisant : benchmark arrêté proprement (rapport partiel)")
                stopped = True
                break
            root, clone_s, err = _materialize(entry, workdir)
            row = {"repo": entry, "clone_s": round(clone_s, 1)}
            row.update(classify(root, err))
            row["detected"] = row["status"] == "runnable"
            if row["detected"] and root is not None:
                row.update(_run_full(root, timeout))
                if disk_failure(row) and os.environ.get("ZERO_BENCH_CLEANUP"):
                    ensure_disk(min_mb=10 ** 9)          # vide tous les caches, puis une seule nouvelle tentative
                    log(f"échec lié à l'espace disque : nouvelle tentative de {entry}")
                    row.update(_run_full(root, timeout))
                    row["retried_after_disk_failure"] = True
                    if disk_failure(row):
                        row["phase"] = "disk_full"          # toujours faute d'espace : ce n'est pas le dépôt
            if root is not None and os.environ.get("ZERO_BENCH_CLEANUP") and re.match(r"^(https?://|git@)", entry):
                _cleanup(root)          # node_modules + venv : sans cela 40 dépôts remplissent le disque
            results.append(row)
            _log_row(row)
            _checkpoint(out, results, full)
    summary = summarize(results, full)
    summary["stopped_disk_low"] = stopped
    summary["not_run"] = len(entries) - len(results)
    out.write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False))
    return summary


def _flag(key: str):
    return lambda r: bool(r.get(key))


def _phase(name: str):
    return lambda r: r.get("phase") == name


# Compteurs du résumé : clé → prédicat sur une ligne de résultat (l'ordre est celui du rapport JSON).
COUNTERS = {
    "disk_full": _phase("disk_full"),
    "install_timeout": _phase("install_timeout"),
    "cli_tools": _flag("cli_tool"),
    "multistack_monorepos": _flag("multistack"),
    "entry_from_docs": _flag("entry_from_docs"),          # point d'entrée départagé par une preuve du README/Dockerfile
    "deps_deduced": _flag("deps_deduced"),                # dépendances déduites des import (aucun manifeste)
    "inferred_from_makefile": _flag("run_inferred"),      # commande déduite du Makefile
}
FULL_COUNTERS = {"built": _flag("built"), "launched": _flag("launched"), "http_ok": _flag("http")}
LAST_RESORT = ("inferred_from_makefile", "entry_from_docs", "deps_deduced")      # heuristiques de confiance plus faible


def _count(results: list[dict], pred) -> int:
    return sum(1 for r in results if pred(r))


def summarize(results: list[dict], full: bool) -> dict:
    n = len(results) or 1
    cloned = [r for r in results if r.get("status") != "clone_failed"]
    nc = len(cloned) or 1
    s: dict = {"repos": len(results), "cloned": len(cloned)}
    s["status"] = dict(Counter(r.get("status", "unsupported") for r in results))
    s["detected"] = _count(results, _flag("detected"))
    s["detection_rate"] = round(s["detected"] / n, 3)
    s["detection_rate_of_cloned"] = round(s["detected"] / nc, 3)       # taux « honnête » : seulement les dépôts effectivement clonés
    for key, pred in COUNTERS.items():
        s[key] = _count(results, pred)
    # « strict » : commandes trouvées sans heuristique de dernier recours (Makefile, preuve du README/Dockerfile, imports déduits)
    s["detection_rate_strict_of_cloned"] = round((s["detected"] - sum(s[k] for k in LAST_RESORT)) / nc, 3)
    langs: dict[str, dict] = {}
    for r in cloned:
        d = langs.setdefault(r.get("lang") or "inconnu", {"repos": 0, "runnable": 0})
        d["repos"] += 1
        d["runnable"] += bool(r.get("detected"))
    s["by_language"] = langs
    if full:
        for key, pred in FULL_COUNTERS.items():
            s[key] = _count(results, pred)
        s["build_rate"], s["launch_rate"] = round(s["built"] / n, 3), round(s["launched"] / n, 3)
        ttfr = [r["ttfr_s"] for r in results if r.get("ttfr_s") is not None]
        s["median_ttfr_s"] = round(statistics.median(ttfr), 1) if ttfr else None
        s["interventions_auto"] = sum(r.get("interventions_auto", 0) for r in results)
        s["interventions_manual"] = sum(r.get("interventions_manual", 0) for r in results)
        s["zero_touch"] = _count(results, lambda r: r.get("launched") and not r.get("interventions_manual"))
    return s
