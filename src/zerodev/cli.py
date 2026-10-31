"""CLI : zero [commande] [cible] — clone → zero → run."""
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from .plan import AmbiguousProject, detect_stacks
from .util import VERSION, ZeroError

COMMANDS = {
    "run": "installer + lancer (défaut)",
    "plan": "afficher le plan sans rien exécuter",
    "freeze": "écrire zero.lock.json (runtimes, versions, services, env, GPU)",
    "share": "créer un bundle .zeroshare.tgz reproductible",
    "down": "arrêter les services démarrés par zero",
    "fingerprint": "afficher l'empreinte du dépôt",
    "bench": "benchmark sur un corpus de dépôts",
    "doctor": "état de la machine (outils, conteneurs, GPU, réseau, disque) à joindre à un retour d'essai",
    "report": "un bloc à coller dans un retour d'essai : machine + plan du dépôt + derniers correctifs, sans chemins personnels",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zero", description="git clone && zero.",
        epilog="commandes :\n" + "\n".join(f"  {k:<12}{v}" for k, v in COMMANDS.items()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("command", nargs="?", default="run", help=argparse.SUPPRESS)
    p.add_argument("target", nargs="?", default=".",
                   help="dossier, URL git ou bundle .zeroshare.tgz (bench : fichier corpus)")
    p.add_argument("-p", "--project", help="monorepo : sous-dossier du projet à lancer")
    p.add_argument("--all", action="store_true", dest="all_stacks",
                   help="multi-stack : lancer ensemble toutes les stacks détectées (backend + frontend…) ; automatique pour un monorepo de 2-3 stacks de langages différents")
    p.add_argument("--cmd", help="impose la commande de lancement (court-circuite la détection)")
    p.add_argument("--no-recover", action="store_true", help="désactive la récupération automatique (V4)")
    p.add_argument("--no-services", action="store_true", help="ne démarre pas les services (V1)")
    p.add_argument("--services", choices=("auto", "container", "local"), default="auto",
                   help="où démarrer les services : conteneurs, binaires locaux (redis, postgres, mysql/mariadb, mongod) "
                        "ou auto = conteneur si disponible, sinon local (défaut)")
    p.add_argument("--no-lock", action="store_true", help="ignore zero.lock.json et le registre")
    p.add_argument("--full", action="store_true", help="bench : exécuter réellement chaque dépôt")
    p.add_argument("--timeout", type=int, default=90, help="bench --full : secondes avant arrêt (défaut 90)")
    p.add_argument("--jobs", type=int, default=4, help="bench : clones en parallèle (défaut 4)")
    p.add_argument("--workdir", default="zero-bench", help="bench : dossier de clonage")
    p.add_argument("--out", default="zero-bench.json", help="bench : fichier de rapport")
    p.add_argument("--sandbox", action="store_true",
                   help="isole l'installation et le lancement (bubblewrap sous Linux, sandbox-exec sous macOS) : ~ masqué, système en lecture seule, écriture limitée au dépôt et à ~/.zero")
    p.add_argument("--json", action="store_true", help="doctor : sortie JSON")
    p.add_argument("--no-network", action="store_true", help="doctor : ne teste pas l'accès réseau")
    p.add_argument("--version", action="version", version=f"zerodev {VERSION}")
    return p


def _terminate(signum, frame):
    raise KeyboardInterrupt


def install_signal_handlers() -> None:
    """SIGINT et SIGTERM déclenchent l'arrêt propre (superviseur, services).

    Indispensable : un shell non interactif lance les tâches de fond avec SIGINT ignoré, et Python n'installe alors
    pas son gestionnaire ; sans cela, `zero` ne réagirait plus à Ctrl-C/SIGINT et laisserait des orphelins."""
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, _terminate)


def split_run_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """`zero run dépôt -- --opt valeur` : tout ce qui suit le premier `--` est transmis tel quel à la commande lancée."""
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []


def main(argv: list[str] | None = None) -> int:
    install_signal_handlers()
    from .procs import become_subreaper
    become_subreaper()          # adopte les serveurs qui se détachent (--daemon) pour pouvoir les arrêter
    argv = list(sys.argv[1:] if argv is None else argv)
    argv, run_args = split_run_args(argv)
    # `zero ./plan` : si le 1er argument n'est pas une commande connue, c'est la cible
    if argv and not argv[0].startswith("-") and argv[0] not in COMMANDS:
        argv.insert(0, "run")
    args = build_parser().parse_intermixed_args(argv)   # options libres entre commande et cible
    if args.command not in COMMANDS:
        print(f"commande inconnue : {args.command}", file=sys.stderr)
        return 2
    args.run_args = run_args
    try:
        return dispatch(args)
    except ZeroError as e:
        print(f"\033[1;31m[zero] erreur :\033[0m {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def _cmd_doctor(args: argparse.Namespace) -> int:
    from . import doctor
    info = doctor.collect(network=not args.no_network)
    print(json.dumps(info, indent=2, ensure_ascii=False) if args.json else doctor.render(info))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from . import report
    print(report.build(None if args.target == "." and not (Path(".") / ".git").exists() else args.target, network=not args.no_network))
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    from .bench import run_bench
    out = Path(args.out)
    summary = run_bench(Path(args.target), Path(args.workdir), args.full, args.timeout, out, args.jobs)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"rapport détaillé : {out}")
    return 0


def _enable_sandbox(root: Path) -> None:
    from . import sandbox
    sandbox.enable(root)
    print(f"\033[1;36m[zero]\033[0m mode isolé ({sandbox.backend() or 'bubblewrap'}) : ~ masqué, système en lecture seule, écriture limitée à "
          f"{root.name}/ et ~/.zero ; réseau non isolé")


def _cmd_all_stacks(args: argparse.Namespace, root: Path) -> int:
    """`--all` : affiche le plan de chaque stack, puis les lance ensemble (sauf pour `plan`)."""
    from . import core
    if args.command not in ("run", "plan") or args.project or args.cmd:
        from .util import die
        die("--all s'utilise seul avec `run` ou `plan` (pas avec --project/--cmd)")
    ctxs = core.find_stacks(root, use_lock=not args.no_lock)
    for c in ctxs:
        print(f"\n\033[1m── stack « {c.name} »\033[0m", end="")
        core.print_plan(c)
    if args.command == "plan":
        return 0
    return core.run_stacks(root, ctxs, recover=not args.no_recover, with_services=not args.no_services, services_mode=args.services)


def _auto_all_stacks(args: argparse.Namespace, root: Path, e: AmbiguousProject) -> bool:
    """Monorepo dont les sous-projets sont de langages différents (backend + frontend…) : c'est une application, on lance tout ;
    au-delà de 3 stacks (ou avec --project/--cmd, ou pour une autre commande que run/plan) on demande de choisir."""
    if not (e.multistack and args.command in ("run", "plan") and not args.project and not args.cmd and len(detect_stacks(root)) <= 3):
        return False
    print("\033[1;36m[zero]\033[0m monorepo multi-stack détecté ("
          + ", ".join(n for n, _, _ in detect_stacks(root)) + ") : lancement de tous les stacks (équivalent de --all)")
    return True


def _cmd_project(args: argparse.Namespace, root: Path) -> int:
    """Une seule stack : plan, puis (selon la commande) affichage seul, gel, partage ou lancement."""
    from . import core
    ctx = core.make_plan(root, use_lock=not args.no_lock, project=args.project, cmd=args.cmd)
    if getattr(args, "run_args", None):
        core.append_run_args(ctx, args.run_args)
    core.print_plan(ctx)
    if args.command == "plan":
        return 0
    if args.command == "freeze":
        core.freeze_project(ctx)
        return 0
    if args.command == "share":
        core.share_project(ctx)
        return 0
    return core.run_project(ctx, recover=not args.no_recover, with_services=not args.no_services, services_mode=args.services)


def dispatch(args: argparse.Namespace) -> int:
    from . import core
    from .freeze import fingerprint
    from .services import down

    if args.command == "doctor":
        return _cmd_doctor(args)
    if args.command == "bench":
        return _cmd_bench(args)
    if args.command == "report":
        return _cmd_report(args)
    root = core.resolve_target(args.target)
    if args.command == "down":
        print(f"{down(root.name)} service(s) arrêté(s)")
        return 0
    if args.command == "fingerprint":
        print(fingerprint(root))
        return 0
    if getattr(args, "sandbox", False) and args.command in ("run",):
        _enable_sandbox(root)
    if args.all_stacks:
        return _cmd_all_stacks(args, root)
    try:
        return _cmd_project(args, root)
    except AmbiguousProject as e:
        if _auto_all_stacks(args, root, e):
            args.all_stacks = True
            return dispatch(args)
        raise


if __name__ == "__main__":
    sys.exit(main())
