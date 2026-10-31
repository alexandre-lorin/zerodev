#!/usr/bin/env bash
# Démo : quatre dépôts très différents, lancés sans aucune édition manuelle.
# Chaque dépôt est copié dans un dossier temporaire, lancé 15 s puis arrêté proprement (Ctrl-C simulé).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp -r "$HERE/examples/." "$TMP/"

for app in node-app python-app fullstack-app rust-app multistack-app; do
  flags=""; [ "$app" = "multistack-app" ] && flags="--all"
  echo
  echo "════════════════ zero $app ════════════════"
  timeout -s INT 15 "$HERE/bin/zero" run $flags "$TMP/$app"
  echo "(code de sortie : $?)"
done
