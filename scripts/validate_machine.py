#!/usr/bin/env python3
"""Validation automatique de zero sur UNE machine (Linux ou macOS) : crée de petits dépôts synthétiques, lance zero dessus,
sonde le HTTP et imprime un tableau OK / KO / SKIP + un fichier de rapport sans chemins personnels.

    python3 scripts/validate_machine.py [--keep-home] [--only NOM ...] [--timeout 120] [--out validate-report.txt]

Ne lance QUE les dépôts synthétiques qu'il crée lui-même (aucun code tiers). Réseau nécessaire (runtimes, PyPI). ~3 à 6 min la première fois.
Code de sortie : 0 si aucun KO, 1 sinon (les SKIP ne comptent pas).
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ZERO = str(HERE / "bin" / "zero")
sys.path.insert(0, str(HERE / "src"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_status(port: int, timeout: float = 2.0) -> int | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=timeout) as r:
            return r.status
    except Exception:
        return None


def write(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


NODE_SERVER = "require('http').createServer((q,r)=>r.end('{tag}')).listen({port})\n"
PY_SERVER = "import http.server, socketserver\nsocketserver.TCPServer(('127.0.0.1', {port}), http.server.SimpleHTTPRequestHandler).serve_forever()\n"


class Ctx:
    def __init__(self, work: Path, env: dict, timeout: int):
        self.work, self.env, self.timeout = work, env, timeout

    def run(self, args: list[str], timeout: int = 120) -> tuple[int, str]:
        p = subprocess.run([ZERO, *args], capture_output=True, text=True, env=self.env, timeout=timeout)
        return p.returncode, p.stdout + p.stderr

    def launch(self, args: list[str], port: int, other_port: int | None = None, timeout: int | None = None) -> tuple[bool, str]:
        """Lance zero en arrière-plan, attend un HTTP 200 sur `port` (jusqu'à `timeout`), puis arrête tout le groupe de processus."""
        log = self.work / f"launch-{port}.log"
        with open(log, "w") as fh:
            proc = subprocess.Popen([ZERO, *args], stdout=fh, stderr=subprocess.STDOUT, env=self.env, start_new_session=True)
            ok, deadline = False, time.time() + (timeout or self.timeout)
            try:
                while time.time() < deadline and proc.poll() is None:
                    if http_status(port) == 200:
                        ok = True
                        break
                    time.sleep(1)
                if ok and other_port is not None and http_status(other_port) is not None:
                    ok = False
                    fh.write(f"\n[validate] le port {other_port} répond alors qu'il ne devrait pas\n")
            finally:
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(proc.pid, sig)
                    except ProcessLookupError:
                        break
                    try:
                        proc.wait(timeout=8)
                        break
                    except subprocess.TimeoutExpired:
                        continue
        return ok, log.read_text(errors="replace")


def tail(text: str, n: int = 12) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


# ───────────────────────────── les vérifications ─────────────────────────────
def check_node(c: Ctx):
    port = free_port()
    repo = write(c.work / "node", {"package.json": '{"name":"n","scripts":{"start":"node server.js"}}', "server.js": NODE_SERVER.format(tag="hi", port=port)})
    ok, log = c.launch([str(repo)], port)
    return ("OK" if ok else "KO"), "HTTP 200" if ok else tail(log)


def check_python_pyproject(c: Ctx):
    port = free_port()
    repo = write(c.work / "pyproj", {
        "pyproject.toml": '[project]\nname="x"\nversion="0.1"\nrequires-python=">=3.10"\ndependencies=[]\n[project.scripts]\nx="x:main"\n',
        "x/__init__.py": "def main():\n    " + PY_SERVER.format(port=port).replace("\n", "\n    ").rstrip() + "\n"})
    ok, log = c.launch([str(repo)], port)
    return ("OK" if ok else "KO"), "HTTP 200" if ok else tail(log)


def check_readme_run(c: Ctx):
    port = free_port()
    repo = write(c.work / "readme", {"README.md": "# Demo\n```bash\npip install -r requirements.txt\npython serve_it.py\n```\n",
                                     "requirements.txt": "requests\n", "helper.py": "x = 1\n", "serve_it.py": PY_SERVER.format(port=port)})
    ok, log = c.launch([str(repo)], port)
    noted = "commande déduite du README" in log
    return ("OK" if ok and noted else "KO"), ("HTTP 200 + note README" if ok and noted else f"http={ok} note={noted}\n{tail(log)}")


def check_readme_utility_not_guessed(c: Ctx):
    repo = write(c.work / "utility", {"README.md": "```\npython scripts/reset_db.py\n```\n", "requirements.txt": "requests\n", "scripts/reset_db.py": "x = 1\n", "a.py": "x=1\n", "b.py": "y=1\n"})
    code, out = c.run(["plan", str(repo)])
    guessed = "commande déduite du README" in out
    return ("KO" if guessed else "OK"), ("un script d'outillage a été pris pour la commande de lancement" if guessed else "aucune commande devinée (attendu)")


def check_monorepo_readme(c: Ctx):
    api, web = free_port(), free_port()
    repo = write(c.work / "mono", {
        "README.md": "# Mono\n```\ncd web\nnpm start\n```\n",
        "api/package.json": '{"name":"api","scripts":{"start":"node s.js"}}', "api/s.js": NODE_SERVER.format(tag="api", port=api),
        "web/package.json": '{"name":"web","scripts":{"start":"node s.js"}}', "web/s.js": NODE_SERVER.format(tag="web", port=web)})
    ok, log = c.launch([str(repo)], web, other_port=api)
    return ("OK" if ok else "KO"), "web lancé, api non lancé" if ok else tail(log)


def check_monorepo_ambiguous_refused(c: Ctx):
    repo = write(c.work / "amb", {"api/package.json": '{"scripts":{"start":"node s.js"}}', "api/s.js": "1", "web/package.json": '{"scripts":{"start":"node s.js"}}', "web/s.js": "1"})
    code, out = c.run([str(repo)])
    good = code != 0 and "--project" in out
    return ("OK" if good else "KO"), "refus avec --project (attendu)" if good else f"code={code}\n{tail(out)}"


def check_foreign_hint(c: Ctx):
    repo = write(c.work / "ruby", {"Gemfile": "source 'https://rubygems.org'\n"})
    code, out = c.run([str(repo)])
    good = code != 0 and "Ruby" in out and "À la main" in out
    return ("OK" if good else "KO"), "message Ruby + commande manuelle (attendu)" if good else f"code={code}\n{tail(out)}"


def check_report(c: Ctx):
    repo = write(c.work / "reportme", {"package.json": '{"scripts":{"start":"node s.js"}}', "s.js": "1"})
    # sans ZERO_HOME temporaire : le plan contient alors des chemins sous votre dossier personnel, qui DOIVENT être masqués
    env, c.env = c.env, {k: v for k, v in c.env.items() if k != "ZERO_HOME"}
    try:
        code, out = c.run(["report", str(repo), "--no-network"])
    finally:
        c.env = env
    home = str(Path.home())
    leaks = [x for x in (home,) if len(x) > 1 and x in out]
    good = code == 0 and "## plan : reportme" in out and not leaks and "\x1b[" not in out
    return ("OK" if good else "KO"), "bloc complet, dossier personnel masqué" if good else f"code={code} fuite={leaks}\n{tail(out)}"


def check_sandbox(c: Ctx):
    from zerodev import sandbox
    backend = sandbox.backend()
    port = free_port()
    repo = write(c.work / "sbx", {"package.json": '{"scripts":{"start":"node server.js"}}', "server.js": NODE_SERVER.format(tag="sbx", port=port)})
    if backend is None:
        code, out = c.run(["run", "--sandbox", str(repo)], timeout=60)
        good = code != 0 and "sandbox" in out.lower()
        return ("OK" if good else "KO"), ("aucun backend d'isolation : refus clair (attendu)" if good else f"devait refuser\n{tail(out)}")
    ok, log = c.launch(["run", "--sandbox", str(repo)], port)
    announced = f"mode isolé ({backend})" in log
    return ("OK" if ok and announced else "KO"), (f"{backend} : HTTP 200 + annonce" if ok and announced else f"backend={backend} http={ok} annonce={announced}\n{tail(log)}")


def check_sandbox_blocks_home(c: Ctx):
    from zerodev import sandbox
    if sandbox.backend() is None:
        return "SKIP", "aucun backend d'isolation utilisable"
    secret = Path.home() / ".zero-validate-secret"
    secret.write_text("SECRET-MARKER")
    try:
        repo = write(c.work / "sbx2", {"package.json": '{"scripts":{"start":"node -e 0"}}'})
        code, out = c.run(["run", "--sandbox", "--cmd", f"cat {secret}; echo fin", str(repo)], timeout=90)
        leaked = "SECRET-MARKER" in out
        return ("KO" if leaked else "OK"), ("le dépôt isolé a pu LIRE un fichier de votre dossier personnel" if leaked else "fichier du dossier personnel illisible (attendu)")
    finally:
        secret.unlink(missing_ok=True)


def check_container_wrapper(c: Ctx):
    rt = shutil.which("podman") or shutil.which("docker")
    if not rt:
        return "SKIP", "ni podman ni docker"
    img = subprocess.run([rt, "image", "inspect", "zerodev:latest"], capture_output=True).returncode == 0
    if not img:
        return "SKIP", f"image absente : {rt} build -f contrib/Dockerfile -t zerodev:latest .  (puis relancer)"
    port = free_port()
    server = f"require('http').createServer((q,r)=>r.end('ctr')).listen({port}, '0.0.0.0')\n"     # 0.0.0.0 : sinon injoignable depuis l'hôte
    repo = write(c.work / "ctr", {"package.json": '{"scripts":{"start":"node server.js"}}', "server.js": server})
    old, c.env = c.env, {**c.env, "ZERO_PORTS": str(port)}
    try:
        ok, log = _launch_script(c, repo, port)
    finally:
        c.env = old
    return ("OK" if ok else "KO"), "HTTP 200 depuis le conteneur" if ok else tail(log)


def _launch_script(c: Ctx, repo: Path, port: int) -> tuple[bool, str]:
    log = c.work / f"container-{port}.log"
    with open(log, "w") as fh:
        proc = subprocess.Popen(["sh", str(HERE / "contrib" / "zero-container.sh"), str(repo)], stdout=fh, stderr=subprocess.STDOUT, env=c.env, start_new_session=True)
        ok, deadline = False, time.time() + max(c.timeout, 180)
        try:
            while time.time() < deadline and proc.poll() is None:
                if http_status(port) == 200:
                    ok = True
                    break
                time.sleep(2)
        finally:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(proc.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    proc.wait(timeout=15)
                    break
                except subprocess.TimeoutExpired:
                    continue
    return ok, log.read_text(errors="replace")


GO_SERVER = ('package main\nimport ("fmt"; "net/http")\n'
             'func main() { http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, "go") }); http.ListenAndServe("127.0.0.1:{port}", nil) }\n')
RUST_SERVER = (r'use std::io::{Read, Write}; use std::net::TcpListener;' '\n'
               r'fn main() { let l = TcpListener::bind("127.0.0.1:{port}").unwrap(); for s in l.incoming() { if let Ok(mut s) = s { let mut b = [0u8; 512]; let _ = s.read(&mut b);'
               r' let _ = s.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nrs"); } } }' '\n')


def check_go(c: Ctx):
    """NON ÉPROUVÉ par l'auteur (pas de Go ici) : si KO, vérifier à la main que le dépôt synthétique est correct avant de conclure à un bug de zero."""
    port = free_port()
    repo = write(c.work / "goapp", {"go.mod": "module example.com/app\n\ngo 1.21\n", "main.go": GO_SERVER.replace("{port}", str(port))})
    ok, log = c.launch([str(repo)], port, timeout=max(c.timeout, 300))
    return ("OK" if ok else "KO"), "HTTP 200" if ok else tail(log)


def check_rust(c: Ctx):
    """NON ÉPROUVÉ par l'auteur (pas de Rust ici) : même réserve que check_go ; la première compilation peut prendre plusieurs minutes."""
    port = free_port()
    repo = write(c.work / "rustapp", {"Cargo.toml": '[package]\nname = "app"\nversion = "0.1.0"\nedition = "2021"\n', "src/main.rs": RUST_SERVER.replace("{port}", str(port))})
    ok, log = c.launch([str(repo)], port, timeout=max(c.timeout, 600))
    return ("OK" if ok else "KO"), "HTTP 200" if ok else tail(log)


CHECKS = [("node", check_node), ("python-pyproject", check_python_pyproject), ("go", check_go), ("rust", check_rust), ("readme-run", check_readme_run),
          ("readme-utility-refused", check_readme_utility_not_guessed), ("monorepo-readme", check_monorepo_readme),
          ("monorepo-ambiguous", check_monorepo_ambiguous_refused), ("foreign-hint", check_foreign_hint), ("report", check_report),
          ("sandbox", check_sandbox), ("sandbox-blocks-home", check_sandbox_blocks_home), ("container-wrapper", check_container_wrapper)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep-home", action="store_true", help="utilise votre ~/.zero (cache des runtimes) au lieu d'un dossier temporaire")
    ap.add_argument("--only", nargs="*", help="noms des vérifications à lancer : " + ", ".join(n for n, _ in CHECKS))
    ap.add_argument("--timeout", type=int, default=120, help="secondes d'attente HTTP par lancement (défaut 120)")
    ap.add_argument("--out", default="validate-report.txt")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="zero-validate-"))
    env = dict(os.environ)
    if not args.keep_home:
        env["ZERO_HOME"] = str(work / "zero-home")
    ctx = Ctx(work, env, args.timeout)
    from zerodev import report
    from zerodev.util import VERSION

    rows, ko = [], 0
    print(f"zero {VERSION} — validation dans {work}\n")
    for name, fn in CHECKS:
        if args.only and name not in args.only:
            continue
        t0 = time.time()
        try:
            status, detail = fn(ctx)
        except Exception as e:           # une vérification qui plante est un KO, pas un arrêt de tout
            status, detail = "KO", f"exception : {type(e).__name__}: {e}"
        ko += status == "KO"
        rows.append((name, status, detail, time.time() - t0))
        print(f"{status:<4} {name:<24} ({rows[-1][3]:.0f}s)  {detail.splitlines()[0] if detail else ''}", flush=True)

    lines = [f"zero {VERSION} — validate_machine — {sys.platform}", ""]
    for name, status, detail, secs in rows:
        lines.append(f"{status:<4} {name} ({secs:.0f}s)")
        if status != "OK":
            lines += ["     " + l for l in detail.splitlines()[-25:]]
    lines += ["", "## doctor", report.build(None, network=True)]
    Path(args.out).write_text(report.redact("\n".join(lines)))
    print(f"\n{len(rows) - ko}/{len(rows)} sans KO — rapport (chemins personnels masqués) : {args.out}")
    shutil.rmtree(work, ignore_errors=True)
    return 1 if ko else 0


if __name__ == "__main__":
    sys.exit(main())
