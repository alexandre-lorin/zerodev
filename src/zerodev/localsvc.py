"""Services sans conteneur : repli sur des binaires locaux (redis-server, postgres, mongod).

Utilisé quand ni podman ni docker n'est installé (ou avec --services local). Les données PostgreSQL
et MySQL/MariaDB sont conservées entre deux lancements (~/.zero/services/<projet>/…) ; Redis est éphémère.
RabbitMQ n'est pas géré en local (Erlang + configuration trop dépendants de la distribution).
"""
from __future__ import annotations

import glob
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .util import log, warn, zero_home

PG_DIRS = [
    "/usr/lib/postgresql/*/bin",                       # Debian / Ubuntu
    "/opt/homebrew/opt/postgresql@*/bin", "/opt/homebrew/bin",     # macOS (Apple Silicon)
    "/usr/local/opt/postgresql@*/bin", "/usr/local/bin",           # macOS (Intel)
    "/Applications/Postgres.app/Contents/Versions/*/bin",
    "/usr/pgsql-*/bin",                                # RHEL / Fedora
]
SUPPORTED = ("redis", "postgres", "mongodb", "mysql")


@dataclass
class LocalProc:
    kind: str
    proc: subprocess.Popen
    stop_signal: int = signal.SIGTERM


def find_bin(name: str, extra_globs: list[str] | None = None) -> str | None:
    if found := shutil.which(name):
        return found
    for pattern in sorted(extra_globs or [], reverse=True):
        for d in sorted(glob.glob(pattern), reverse=True):      # version la plus récente d'abord
            cand = Path(d) / name
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
    return None


def _pg(name: str) -> str | None:
    return find_bin(name, PG_DIRS)


def available(kind: str) -> bool:
    if kind == "redis":
        return find_bin("redis-server") is not None
    if kind == "postgres":
        return _pg("postgres") is not None and _pg("initdb") is not None
    if kind == "mongodb":
        return find_bin("mongod") is not None
    if kind == "mysql":
        return _mysql_bins() is not None
    return False


def service_dir(project: str, kind: str) -> Path:
    # PostgreSQL refuse de tourner en root : sous root on utilise l'utilisateur « postgres »,
    # qui ne peut pas traverser /root → répertoire hors du HOME.
    base = Path("/tmp/zero-services") if _pg_needs_user() and kind == "postgres" else zero_home() / "services"
    d = base / project / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pg_needs_user() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _pg_runner() -> list[str] | None:
    """Préfixe de commande pour exécuter postgres : [] (utilisateur normal), ou runuser sous root."""
    if not _pg_needs_user():
        return []
    try:
        import pwd
        pwd.getpwnam("postgres")
    except (ImportError, KeyError):
        return None
    return ["runuser", "-u", "postgres", "--"] if shutil.which("runuser") else None


def _spawn(cmd: list[str], logfile: Path) -> subprocess.Popen:
    out = open(logfile, "ab")
    return subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)


def start(kind: str, port: int, project: str, creds: dict | None = None) -> LocalProc | None:
    """Démarre le service ; retourne None (avec un avertissement) si impossible."""
    d = service_dir(project, kind)
    logfile = zero_home() / "services" / project / f"{kind}.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "redis":
            return LocalProc(kind, _spawn([find_bin("redis-server"), "--port", str(port), "--bind", "127.0.0.1",
                                           "--save", "", "--appendonly", "no", "--dir", str(d)], logfile))
        if kind == "mongodb":
            return LocalProc(kind, _spawn([find_bin("mongod"), "--port", str(port), "--bind_ip", "127.0.0.1",
                                           "--dbpath", str(d)], logfile))
        if kind == "postgres":
            return _start_postgres(d, port, logfile, creds or {})
        if kind == "mysql":
            return _start_mysql(d, port, logfile, creds or {})
    except OSError as e:
        warn(f"{kind} local : démarrage impossible ({e})")
    return None


def _start_postgres(d: Path, port: int, logfile: Path, creds: dict | None = None) -> LocalProc | None:
    creds = creds or {}
    role, dbname = creds.get("POSTGRES_USER") or "zero", creds.get("POSTGRES_DB") or "app"
    runner = _pg_runner()
    if runner is None:
        warn("postgres local : exécuté en root et aucun utilisateur « postgres » disponible (runuser)")
        return None
    data, sock = d / "data", d / "sock"
    sock.mkdir(exist_ok=True)
    if runner:                                        # sous root : le dossier doit appartenir à postgres
        subprocess.run(["chown", "-R", "postgres:postgres", str(d)], check=False)
    if not (data / "PG_VERSION").exists():
        log("initialisation de la base PostgreSQL locale")
        r = subprocess.run(runner + [_pg("initdb"), "-D", str(data), "-U", "zero", "--auth=trust",
                                     "-E", "UTF8", "--no-locale"], capture_output=True, text=True)
        if r.returncode:
            warn(f"initdb a échoué : {(r.stderr or r.stdout).strip()[-200:]}")
            return None
    proc = _spawn(runner + [_pg("postgres"), "-D", str(data), "-p", str(port), "-c", "listen_addresses=127.0.0.1",
                            "-c", f"unix_socket_directories={sock}"], logfile)
    createdb = _pg("createdb")
    deadline = time.time() + 40
    while time.time() < deadline and proc.poll() is None:      # attend que le serveur accepte les connexions
        r = subprocess.run([createdb, "-h", "127.0.0.1", "-p", str(port), "-U", "zero", "app"],
                           capture_output=True, text=True)
        if r.returncode == 0 or "already exists" in r.stderr:
            _pg_custom_role(port, role, dbname)
            return LocalProc("postgres", proc, signal.SIGINT)   # SIGINT = « fast shutdown »
        time.sleep(0.5)
    if proc.poll() is None:
        proc.terminate()
    warn(f"postgres local n'a pas démarré (journal : {logfile})")
    return None


def _pg_custom_role(port: int, role: str, dbname: str) -> None:
    """Crée le rôle et la base déclarés par le dépôt (compose) ; sans effet pour zero/app. Échecs ignorés."""
    common = ["-h", "127.0.0.1", "-p", str(port), "-U", "zero"]
    if role != "zero" and _pg("createuser"):
        subprocess.run([_pg("createuser"), *common, "-s", role], capture_output=True, text=True)
    if dbname != "app" and _pg("createdb"):
        subprocess.run([_pg("createdb"), *common, "-O", role, dbname], capture_output=True, text=True)


def _mysql_bins() -> dict | None:
    """Serveur, client et outil d'initialisation de MariaDB ou de MySQL (Oracle)."""
    maria = find_bin("mariadbd")
    server = maria or find_bin("mysqld")
    client = find_bin("mariadb") or find_bin("mysql")
    install = find_bin("mariadb-install-db") or find_bin("mysql_install_db")
    if not server or not client:
        return None
    if maria and not install:
        return None
    return {"server": server, "client": client, "install": install if maria else None, "maria": bool(maria)}


def _mysql_user_args() -> list[str]:
    return ["--user=root"] if _pg_needs_user() else []         # mysqld refuse de tourner en root sans cette option


def _start_mysql(d: Path, port: int, logfile: Path, creds: dict | None = None) -> LocalProc | None:
    creds = creds or {}
    b = _mysql_bins()
    data, sock = d / "data", d / "sock"
    sock.mkdir(exist_ok=True)
    if not (data / "mysql").exists():
        log("initialisation de la base MySQL/MariaDB locale")
        if b["maria"]:
            cmd = [b["install"], "--no-defaults", f"--datadir={data}", "--auth-root-authentication-method=normal",
                   "--skip-test-db"] + _mysql_user_args()
        else:
            cmd = [b["server"], "--no-defaults", "--initialize-insecure", f"--datadir={data}"] + _mysql_user_args()
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            warn(f"initialisation MySQL échouée : {(r.stderr or r.stdout).strip()[-200:]}")
            return None
    proc = _spawn([b["server"], "--no-defaults", f"--datadir={data}", f"--port={port}", "--bind-address=127.0.0.1",
                   f"--socket={sock / 'mysql.sock'}", f"--pid-file={sock / 'mysql.pid'}", "--skip-name-resolve"]
                  + _mysql_user_args(), logfile)
    sockf = str(sock / "mysql.sock")
    admin = [b["client"], "-S", sockf, "-uroot", "--connect-timeout=3"]       # root@localhost via le socket Unix
    tcp = [b["client"], "-h", "127.0.0.1", "-P", str(port), "-uroot", "-pzero", "--connect-timeout=3"]
    setup = []
    for host in ("localhost", "127.0.0.1", "::1"):                           # mot de passe « zero » pour chaque hôte
        acct = f"'root'@'{host}'"
        setup.append(f"CREATE USER IF NOT EXISTS {acct} IDENTIFIED BY 'zero'")
        setup.append(f"ALTER USER {acct} IDENTIFIED VIA mysql_native_password USING PASSWORD('zero')" if b["maria"]
                     else f"ALTER USER {acct} IDENTIFIED BY 'zero'")
        setup.append(f"GRANT ALL ON *.* TO {acct} WITH GRANT OPTION")
    setup.append("CREATE DATABASE IF NOT EXISTS app")
    deadline = time.time() + 60
    while time.time() < deadline and proc.poll() is None:
        r = subprocess.run(tcp + ["-e", "CREATE DATABASE IF NOT EXISTS app"], capture_output=True, text=True)
        if r.returncode == 0:                           # 2e lancement : tout est déjà en place
            _mysql_custom_account(tcp, creds)
            return LocalProc("mysql", proc, signal.SIGTERM)
        if subprocess.run(admin + ["-e", "SELECT 1"], capture_output=True).returncode == 0:
            r = subprocess.run(admin + ["-e", "; ".join(setup)], capture_output=True, text=True)
            if r.returncode:
                warn(f"configuration MySQL échouée : {r.stderr.strip()[-200:]}")
                break
            _mysql_custom_account(tcp, creds)
            return LocalProc("mysql", proc, signal.SIGTERM)
        time.sleep(0.5)
    if proc.poll() is None:
        proc.terminate()
    warn(f"mysql local n'a pas démarré (journal : {logfile})")
    return None


def mysql_account_statements(creds: dict) -> list[str]:
    """SQL pour la base et l'utilisateur déclarés par le dépôt (compose) ; vide si rien de particulier."""
    db, user, pw = creds.get("MYSQL_DATABASE") or "app", creds.get("MYSQL_USER"), creds.get("MYSQL_PASSWORD")
    out = []
    if db != "app":
        out.append(f"CREATE DATABASE IF NOT EXISTS `{db}`")
    if user and pw:
        for host in ("localhost", "127.0.0.1", "::1", "%"):
            out.append(f"CREATE USER IF NOT EXISTS '{user}'@'{host}' IDENTIFIED BY '{pw}'")
            out.append(f"GRANT ALL ON *.* TO '{user}'@'{host}'")
    return out


def _mysql_custom_account(tcp: list[str], creds: dict) -> None:
    stmts = mysql_account_statements(creds)
    if stmts:
        r = subprocess.run(tcp + ["-e", "; ".join(stmts)], capture_output=True, text=True)
        if r.returncode:
            warn(f"compte MySQL du dépôt non créé : {r.stderr.strip()[-200:]}")


def stop(lp: LocalProc, timeout: float = 10.0) -> None:
    if lp.proc.poll() is not None:
        return
    try:
        os.killpg(lp.proc.pid, lp.stop_signal)
    except ProcessLookupError:
        return
    try:
        lp.proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(lp.proc.pid, signal.SIGKILL)
