#!/bin/sh
# Installe la commande `zero` pour l'utilisateur courant (sans droits administrateur) :
#     git clone <dépôt> && cd zerodev && ./install.sh
# Crée ~/.local/bin/zero, un lanceur vers ce dossier (le dossier doit rester en place).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
py="$(command -v python3 || true)"
[ -n "$py" ] || { echo "python3 introuvable : installez Python >= 3.10" >&2; exit 1; }
"$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Python >= 3.10 requis (trouvé : $("$py" -V 2>&1))" >&2; exit 1; }
bin="${ZERO_INSTALL_DIR:-$HOME/.local/bin}"
mkdir -p "$bin"
cat > "$bin/zero" <<WRAP
#!/bin/sh
exec "$py" "$here/bin/zero" "\$@"
WRAP
chmod +x "$bin/zero"
echo "zero installé : $bin/zero"
case ":$PATH:" in *":$bin:"*) ;; *) echo "attention : $bin n'est pas dans votre PATH (ajoutez : export PATH=\"$bin:\$PATH\")" ;; esac
"$bin/zero" --version
