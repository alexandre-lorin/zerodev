#!/usr/bin/env python3
"""Reproduit la règle FIXE des corpus `corpus.public500.txt` et `corpus.public500b.txt` (spécification §15).

    python3 benchmark/build_corpus_rule.py --stars 500..3000 --per-language 100 --out /tmp/corpus.txt \\
        --exclude benchmark/corpus.public.txt benchmark/corpus.heldout.txt

Règle : API GitHub `search/repositories`, `language:<L> stars:<lo>..<hi> archived:false`, tri par date de mise à jour décroissante, les
`--per-language` premiers pour python, javascript, typescript, go et rust, doublons des fichiers `--exclude` retirés. L'API fonctionne sans jeton
mais à raison de 10 recherches par minute : le script attend 7 s entre deux requêtes. Les résultats dépendent de la date d'exécution (« mis à jour
récemment » change chaque jour) : un corpus regénéré ne sera pas identique, d'où les fichiers de corpus conservés dans ce dépôt.
Biais assumés : dépôts récemment actifs, popularité moyenne, beaucoup de bibliothèques ; les dépôts de plus de 300 Mo (champ `size` de l'API, historique complet)
sont écartés à l'évaluation, pas ici (le script les signale)."""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

API = "https://api.github.com/search/repositories"
LANGUAGES = ("python", "javascript", "typescript", "go", "rust")
BIG_KB = 300_000


def build_query(language: str, lo: int, hi: int) -> str:
    return f"language:{language} stars:{lo}..{hi} archived:false"


def parse_stars(text: str) -> tuple[int, int]:
    lo, _, hi = text.partition("..")
    return int(lo), int(hi)


def pick(items: list[dict], seen: set[str], limit: int) -> list[dict]:
    """Garde les `limit` premiers dépôts non déjà vus (comparaison insensible à la casse et au `/` final)."""
    out = []
    for it in items:
        url = it["html_url"]
        key = url.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
        if len(out) >= limit:
            break
    return out


def read_urls(paths: list[str]) -> set[str]:
    seen: set[str] = set()
    for p in paths:
        for line in Path(p).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                seen.add(line.lower().rstrip("/"))
    return seen


def fetch(language: str, lo: int, hi: int, per_page: int = 100) -> list[dict]:
    qs = urllib.parse.urlencode({"q": build_query(language, lo, hi), "sort": "updated", "order": "desc", "per_page": per_page})
    req = urllib.request.Request(f"{API}?{qs}", headers={"Accept": "application/vnd.github+json", "User-Agent": "zerodev-benchmark"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("items", [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stars", default="500..3000")
    ap.add_argument("--per-language", type=int, default=100)
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--languages", nargs="*", default=list(LANGUAGES))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    lo, hi = parse_stars(args.stars)
    seen = read_urls(args.exclude)
    rows: list[dict] = []
    for i, lang in enumerate(args.languages):
        if i:
            time.sleep(7)                               # 10 recherches/minute sans jeton
        rows += pick(fetch(lang, lo, hi, per_page=min(100, args.per_language * 2)), seen, args.per_language)
    header = (f"# Corpus généré le {date.today()} par benchmark/build_corpus_rule.py : « {build_query('<L>', lo, hi)} », tri par mise à jour décroissante,\n"
              f"# {args.per_language} premiers par langage ({', '.join(args.languages)}), doublons des corpus exclus retirés.\n"
              f"# Biais : récemment actifs, popularité moyenne, beaucoup de bibliothèques ; dépôts > {BIG_KB // 1000} Mo à écarter à l'évaluation.\n")
    Path(args.out).write_text(header + "\n".join(r["html_url"] for r in rows) + "\n")
    big = sum(1 for r in rows if r.get("size", 0) > BIG_KB)
    print(f"{args.out} : {len(rows)} dépôts ({big} de plus de {BIG_KB // 1000} Mo, à écarter à l'évaluation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
