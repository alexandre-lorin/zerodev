#!/bin/sh
# Lance zero DANS un conteneur podman/docker (isolation du dépôt : voir docs/CONTAINER.md).
#   contrib/zero-container.sh <dépôt> [options de zero]
# Variables : ZERO_CONTAINER_RUNTIME (podman|docker, défaut : le premier trouvé), ZERO_CONTAINER_IMAGE (défaut zerodev:latest),
#   ZERO_PORTS="3000 8000" (ports à publier sur l'hôte), ZERO_MEMORY (défaut 4g), ZERO_PIDS (défaut 1024),
#   ZERO_VOLUME_OPTS (ex. « :Z » sous SELinux/podman).
set -eu
usage() { echo "usage : $0 <dépôt> [options de zero]" >&2; exit 2; }
[ $# -ge 1 ] || usage
repo="$1"; shift
[ -d "$repo" ] || { echo "dossier introuvable : $repo" >&2; exit 2; }
rt="${ZERO_CONTAINER_RUNTIME:-}"
if [ -z "$rt" ]; then
  for c in podman docker; do
    if command -v "$c" >/dev/null 2>&1; then rt="$c"; break; fi
  done
fi
[ -n "$rt" ] || { echo "ni podman ni docker : installez l'un des deux" >&2; exit 1; }
repo="$(cd "$repo" && pwd)"
ports=""
for p in ${ZERO_PORTS:-}; do
  case "$p" in ''|*[!0-9]*) echo "ZERO_PORTS : « $p » n'est pas un numéro de port" >&2; exit 2 ;; esac
  ports="$ports -p $p:$p"
done
tty=""
if [ -t 0 ]; then tty="-t"; fi
# shellcheck disable=SC2086
exec "$rt" run --rm -i $tty \
  --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit "${ZERO_PIDS:-1024}" --memory "${ZERO_MEMORY:-4g}" \
  -v "$repo:/work${ZERO_VOLUME_OPTS:-}" -v "zerodev-home:/home/zero/.zero${ZERO_VOLUME_OPTS:-}" \
  -w /work $ports "${ZERO_CONTAINER_IMAGE:-zerodev:latest}" /work "$@"
