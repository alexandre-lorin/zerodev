"""V1 : détection des services (DB, Redis, queues), démarrage, health checks, .env."""
from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import localsvc
from .util import dep_text, free_port, has_dep, log, port_open, read, warn

# kind → image par défaut, port, variables du conteneur, variable(s) d'URL exposées
KNOWN = {
    "postgres": dict(
        image="postgres:16", port=5432,
        container_env={"POSTGRES_USER": "zero", "POSTGRES_PASSWORD": "zero", "POSTGRES_DB": "app"},
        urls={"DATABASE_URL": "postgresql://zero:zero@localhost:{port}/app",
              # variables libpq : utilisées par les apps qui laissent l'hôte vide (Django, psql…)
              "PGHOST": "localhost", "PGPORT": "{port}", "PGUSER": "zero", "PGPASSWORD": "zero",
              "PGDATABASE": "app"},
        deps=("psycopg", "psycopg2", "psycopg2-binary", "asyncpg", "pg", "postgres", "postgresql",
              "tokio-postgres", "pgx", "lib/pq"),
        env_re=r"postgres(?:ql)?://",
    ),
    "mysql": dict(
        image="mysql:8", port=3306,
        container_env={"MYSQL_ROOT_PASSWORD": "zero", "MYSQL_DATABASE": "app"},
        urls={"DATABASE_URL": "mysql://root:zero@localhost:{port}/app"},
        deps=("mysql", "mysql2", "mysqlclient", "pymysql", "mysql-connector-python"),
        env_re=r"mysql://",
    ),
    "redis": dict(
        image="redis:7", port=6379, container_env={},
        urls={"REDIS_URL": "redis://localhost:{port}/0"},
        deps=("redis", "ioredis", "aioredis", "bull", "bullmq", "celery", "rq", "sidekiq", "go-redis"),
        env_re=r"redis://",
    ),
    "mongodb": dict(
        image="mongo:7", port=27017, container_env={},
        urls={"MONGODB_URI": "mongodb://localhost:{port}/app", "MONGO_URL": "mongodb://localhost:{port}/app"},
        deps=("mongoose", "mongodb", "pymongo", "motor", "mongo-driver"),
        env_re=r"mongodb(?:\+srv)?://",
    ),
    "rabbitmq": dict(
        image="rabbitmq:3", port=5672, container_env={},
        urls={"AMQP_URL": "amqp://guest:guest@localhost:{port}"},
        deps=("amqplib", "pika", "aio-pika", "kombu", "lapin", "amqp091-go"),
        env_re=r"amqp://",
    ),
}
IMAGE_KIND = {"postgres": "postgres", "postgis": "postgres", "mysql": "mysql", "mariadb": "mysql",
              "redis": "redis", "valkey": "redis", "mongo": "mongodb", "rabbitmq": "rabbitmq"}
REUSABLE = ("redis", "mongodb")  # pas d'identifiants à deviner : on peut réutiliser un service local
ENV_TEMPLATES = (".env.example", ".env.sample", ".env.template", ".env.dist")


@dataclass
class Service:
    kind: str
    image: str
    default_port: int
    port: int
    container_env: dict[str, str]
    urls: dict[str, str]
    sources: list[str] = field(default_factory=list)
    reuse: bool = False   # service déjà présent sur le port par défaut (sans authentification)

    def env(self) -> dict[str, str]:
        return {k: v.format(port=self.port) for k, v in self.urls.items()}


def _compose_images(root: Path) -> dict[str, str]:
    """kind → image:tag déclaré dans docker-compose (sans dépendance YAML)."""
    out: dict[str, str] = {}
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        text = read(root, name)
        if not text:
            continue
        for m in re.finditer(r"^\s*image:\s*[\"']?([\w./-]+(?::[\w.-]+)?)", text, re.M):
            image = m.group(1)
            base = image.split("/")[-1].split(":")[0].lower()
            if base in IMAGE_KIND:
                out.setdefault(IMAGE_KIND[base], image)
    return out


def _compose_vars(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    """Variables d'environnement littérales déclarées dans docker-compose (liste `- K=v` ou map `K: v`).

    Les valeurs interpolées (${VAR}) sont ignorées, sauf `${VAR:-défaut}` qui donne son défaut.
    """
    out: dict[str, str] = {}
    alt = "|".join(names)
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        text = read(root, name)
        if not text:
            continue
        for m in re.finditer(rf"^\s*(?:-\s*)?({alt})\s*[:=]\s*(.+?)\s*$", text, re.M):
            val = m.group(2).split(" #")[0].strip().strip("\"'")
            d = re.fullmatch(r"\$\{[A-Za-z_]\w*:?-([^}]*)\}", val)
            if d:
                val = d.group(1)
            if val and not val.startswith("$") and re.fullmatch(r"[\w.@-]+", val):
                out.setdefault(m.group(1), val)
    return out


def _compose_postgres_creds(root: Path) -> dict[str, str]:
    return _compose_vars(root, ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"))


def _compose_mysql_creds(root: Path) -> dict[str, str]:
    return _compose_vars(root, ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"))


def _apply_mysql_creds(cenv: dict, urls: dict, creds: dict) -> tuple[dict, dict]:
    """Utilisateur applicatif et base du dépôt. Le mot de passe root reste celui de zero."""
    if not creds:
        return cenv, urls
    cenv = {**cenv, **creds}
    db = cenv["MYSQL_DATABASE"]
    if cenv.get("MYSQL_USER") and cenv.get("MYSQL_PASSWORD"):
        user, pw = cenv["MYSQL_USER"], cenv["MYSQL_PASSWORD"]
    else:
        user, pw = "root", "zero"
    return cenv, {**urls, "DATABASE_URL": f"mysql://{user}:{pw}@localhost:{{port}}/{db}"}


def _apply_pg_creds(cenv: dict, urls: dict, creds: dict) -> tuple[dict, dict]:
    """Remplace l'utilisateur/mot de passe/base par défaut de zero par ceux du dépôt."""
    if not creds:
        return cenv, urls
    cenv = {**cenv, **creds}
    user, pw, db = cenv["POSTGRES_USER"], cenv["POSTGRES_PASSWORD"], cenv["POSTGRES_DB"]
    urls = {**urls,
            "DATABASE_URL": f"postgresql://{user}:{pw}@localhost:{{port}}/{db}",
            "PGUSER": user, "PGPASSWORD": pw, "PGDATABASE": db}
    return cenv, urls


def detect_services(root: Path) -> list[Service]:
    text = dep_text(root)
    env_text = "\n".join(read(root, t) or "" for t in ENV_TEMPLATES).lower()
    images = _compose_images(root)
    found: list[Service] = []
    for kind, spec in KNOWN.items():
        sources = []
        if kind in images:
            sources.append("compose")
        if has_dep(text, *spec["deps"]):
            sources.append("dépendances")
        if re.search(spec["env_re"], env_text):
            sources.append(".env.example")
        if not sources:
            continue
        reuse = kind in REUSABLE and port_open(spec["port"])
        cenv, urls = dict(spec["container_env"]), dict(spec["urls"])
        if kind == "postgres" and "compose" in sources:
            cenv, urls = _apply_pg_creds(cenv, urls, _compose_postgres_creds(root))
        if kind == "mysql" and "compose" in sources:
            cenv, urls = _apply_mysql_creds(cenv, urls, _compose_mysql_creds(root))
        found.append(Service(
            kind=kind, image=images.get(kind, spec["image"]), default_port=spec["port"],
            port=spec["port"] if reuse else free_port(spec["port"]),
            container_env=cenv, urls=urls,
            sources=sources, reuse=reuse,
        ))
    return found


def container_cli() -> str | None:
    return shutil.which("podman") or shutil.which("docker")


def _name(project: str, kind: str) -> str:
    return f"zero-{re.sub(r'[^a-z0-9_.-]', '-', project.lower())}-{kind}"


def wait_healthy(port: int, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.5)
    return False


class ServiceManager:
    """Démarre les services (conteneurs, ou binaires locaux en repli) et garantit leur arrêt.

    mode : auto (conteneur si podman/docker, sinon local) | container | local
    """

    def __init__(self, project: str, services: list[Service], mode: str = "auto"):
        self.project, self.services, self.mode = project, services, mode
        self.started: list[str] = []                      # conteneurs
        self.local: list[localsvc.LocalProc] = []         # processus locaux
        self.cli = container_cli()

    def _backend(self, svc: Service) -> str | None:
        want_container = self.mode in ("auto", "container") and self.cli
        if want_container:
            return "container"
        if self.mode in ("auto", "local") and localsvc.available(svc.kind):
            return "local"
        return None

    def start(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for svc in self.services:
            if svc.reuse:
                log(f"{svc.kind} déjà disponible sur localhost:{svc.default_port}")
                env.update(svc.env())
                continue
            backend = self._backend(svc)
            if backend is None:
                hint = ("ni podman ni docker, et pas de binaire local" if svc.kind in localsvc.SUPPORTED
                        else "ni podman ni docker (pas de repli local pour ce service)")
                warn(f"{svc.kind} requis mais {hint} — démarrez-le sur localhost:{svc.default_port}")
                continue
            ok = self._start_container(svc) if backend == "container" else self._start_local(svc)
            if ok:
                env.update(svc.env())
        return env

    def _start_container(self, svc: Service) -> bool:
        name = _name(self.project, svc.kind)
        cmd = [self.cli, "run", "-d", "--rm", "--name", name, "-p", f"{svc.port}:{svc.default_port}"]
        for k, v in svc.container_env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append(svc.image)
        log(f"démarrage de {svc.kind} ({svc.image}) sur le port {svc.port}")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            warn(f"{svc.kind} n'a pas démarré : {r.stderr.strip()[:200]}")
            return False
        self.started.append(name)
        return self._wait(svc)

    def _start_local(self, svc: Service) -> bool:
        log(f"démarrage de {svc.kind} en local (sans conteneur) sur le port {svc.port}")
        lp = localsvc.start(svc.kind, svc.port, self.project, svc.container_env)
        if lp is None:
            return False
        self.local.append(lp)
        return self._wait(svc)

    @staticmethod
    def _wait(svc: Service) -> bool:
        if wait_healthy(svc.port):
            log(f"{svc.kind} prêt")
            return True
        warn(f"{svc.kind} ne répond pas après 60 s")
        return False

    def stop(self) -> None:
        for name in self.started:
            subprocess.run([self.cli, "stop", "-t", "2", name], capture_output=True)
        for lp in self.local:
            localsvc.stop(lp)
        self.started, self.local = [], []


def down(project: str) -> int:
    cli = container_cli()
    if not cli:
        return 0
    out = subprocess.run([cli, "ps", "-aq", "--filter", f"name=zero-{project.lower()}-"],
                         capture_output=True, text=True).stdout.split()
    for cid in out:
        subprocess.run([cli, "rm", "-f", cid], capture_output=True)
    return len(out)


# ───────────────────────────── .env ─────────────────────────────

SECRET_KEY_RE = re.compile(r"(SECRET|SALT|APP_KEY|ENCRYPTION_KEY|SIGNING_KEY|JWT)", re.I)
EXTERNAL_RE = re.compile(r"(API_KEY|TOKEN|PASSWORD|CLIENT_ID|CLIENT_SECRET|ACCESS_KEY|DSN)", re.I)
PLACEHOLDER_RE = re.compile(r"^(|changeme|change_me|your[-_\w]*|xxx+|<.*>|todo|\.\.\.|secret|replace.*)$", re.I)


def fill_env(root: Path, service_env: dict[str, str]) -> dict:
    """Crée .env depuis un template, remplit ce qui peut l'être. N'écrase jamais un .env existant.

    Retourne {created, source, generated, from_services, unresolved}.
    """
    res = {"created": False, "source": None, "generated": [], "from_services": [], "unresolved": []}
    if (root / ".env").exists():
        return res
    tpl = next((t for t in ENV_TEMPLATES if (root / t).is_file()), None)
    if not tpl:
        return res
    lines_out = []
    for line in (root / tpl).read_text(errors="ignore").splitlines():
        m = re.match(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not m:
            lines_out.append(line)
            continue
        prefix, key, value = m.groups()
        raw = value.strip().strip("\"'")
        if key in service_env:
            value = service_env[key]
            res["from_services"].append(key)
        elif PLACEHOLDER_RE.match(raw) or (SECRET_KEY_RE.search(key) and len(raw) < 12):
            if SECRET_KEY_RE.search(key) and not EXTERNAL_RE.search(key.replace("SECRET", "")):
                value = secrets.token_hex(32)
                res["generated"].append(key)
            elif PLACEHOLDER_RE.match(raw):
                res["unresolved"].append(key)
        lines_out.append(f"{prefix}{key}={value}")
    (root / ".env").write_text("\n".join(lines_out) + "\n")
    res.update(created=True, source=tpl)
    return res


def report_env(res: dict) -> None:
    if not res["created"]:
        return
    log(f".env créé depuis {res['source']}")
    if res["from_services"]:
        log(f"  branché sur les services : {', '.join(res['from_services'])}")
    if res["generated"]:
        log(f"  secrets générés : {', '.join(res['generated'])}")
    if res["unresolved"]:
        warn(f"valeurs à fournir vous-même : {', '.join(res['unresolved'])}")
