#!/usr/bin/env bash
# Démo du §16 de la spécification : trois vrais dépôts publics très différents, sans édition manuelle.
# Nécessite le réseau (git clone). Chaque dépôt est lancé, sondé en HTTP, puis arrêté proprement.
# microblog a besoin de Redis et PostgreSQL : zero les démarre en conteneur (docker/podman) ou, à défaut,
# avec des binaires locaux (redis-server, postgresql) s'ils sont installés ; sinon il s'arrête avec un message.
set -u
cd "$(dirname "$0")"
OUT="$(mktemp -d)"
PYTHONPATH="$PWD/src" python3 -m zerodev bench benchmark/corpus.demo.txt --full --timeout 70 --jobs 3 \
  --workdir "$OUT/repos" --out "$OUT/report.json" > "$OUT/log.txt" 2>&1
python3 - "$OUT/report.json" <<'PY'
import json, sys
rep = json.load(open(sys.argv[1]))
ok = 0
for r in rep["results"]:
    name = r["repo"].split("github.com/")[-1]
    h = r.get("http")
    verdict = f"OK  HTTP {h['status']} sur le port {h['port']}" if h else "ÉCHEC  " + ("lancé mais ne répond pas en HTTP" if r.get("launched") else (r.get("status") or "non lancé"))
    ok += bool(h)
    print(f"{name:40s} {verdict}")
print(f"\n{ok}/{len(rep['results'])} dépôts répondent en HTTP sans édition manuelle.")
sys.exit(0 if ok == len(rep["results"]) else 1)
PY
code=$?
echo "Détails : $OUT/log.txt et $OUT/report.json"
exit $code
