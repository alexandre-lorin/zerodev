#!/usr/bin/env python3
"""Construit un corpus de benchmark à grande échelle via l'API de recherche GitHub.

    GITHUB_TOKEN=ghp_... python benchmark/build_corpus.py --per-query 100 --out benchmark/corpus.generated.txt

Sans token, l'API est limitée à 10 recherches/minute et le quota partagé est souvent épuisé : utilisez un token
(aucun droit particulier requis). Les dépôts sont filtrés (non archivés, taille raisonnable, pas des forks) et
répartis par langage ET par type (application vs bibliothèque via les topics), pour que le taux de détection
ne soit pas gonflé par un seul profil de dépôt.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com/search/repositories"

# (étiquette, requête GitHub). `size` est en Ko : on évite les très gros dépôts (clone shallow lent).
QUERIES = [
    (f"{lang}/{kind}", f"language:{lang} {topic} stars:{lo}..{hi} size:<30000 fork:false archived:false")
    for lang in ("python", "javascript", "typescript", "rust", "go")
    for kind, topic in (("webapp", "topic:webapp"), ("cli", "topic:cli"), ("bot", "topic:bot"),
                        ("api", "topic:api"), ("self-hosted", "topic:self-hosted"))
    for lo, hi in ((50, 500), (501, 5000))
]


def parse_items(payload: dict) -> list[dict]:
    """Extrait l'essentiel d'une réponse de l'API de recherche."""
    out = []
    for it in payload.get("items", []):
        if it.get("archived") or it.get("fork") or not it.get("clone_url"):
            continue
        out.append({"url": it["html_url"], "language": it.get("language"), "stars": it.get("stargazers_count", 0),
                    "size_kb": it.get("size", 0), "name": it["full_name"]})
    return out


def search(query: str, per_page: int, token: str | None) -> dict:
    url = f"{API}?{urllib.parse.urlencode({'q': query, 'per_page': per_page, 'sort': 'stars'})}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "zerodev-corpus"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-query", type=int, default=30, help="résultats par requête (max 100)")
    ap.add_argument("--out", default="benchmark/corpus.generated.txt")
    ap.add_argument("--limit", type=int, default=0, help="nombre total maximal de dépôts (0 = illimité)")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    delay = 2.5 if token else 7          # sans token : 10 recherches/min
    seen: dict[str, dict] = {}
    for label, q in QUERIES:
        try:
            items = parse_items(search(q, min(args.per_query, 100), token))
        except urllib.error.HTTPError as e:
            print(f"✗ {label}: HTTP {e.code} ({'quota API épuisé : définissez GITHUB_TOKEN' if e.code in (403, 429) else e.reason})")
            if e.code in (403, 429):
                break
            continue
        new = 0
        for it in items:
            if it["url"] not in seen:
                seen[it["url"]] = {**it, "label": label}
                new += 1
        print(f"✓ {label}: {len(items)} résultats, {new} nouveaux (total {len(seen)})")
        if args.limit and len(seen) >= args.limit:
            break
        time.sleep(delay)

    rows = list(seen.values())[: args.limit or None]
    with open(args.out, "w") as f:
        f.write(f"# Corpus généré le {time.strftime('%Y-%m-%d')} via l'API de recherche GitHub — {len(rows)} dépôts\n")
        for r in rows:
            f.write(f"{r['url']}  # {r['label']} ★{r['stars']}\n")
    print(f"{len(rows)} dépôts écrits dans {args.out}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
