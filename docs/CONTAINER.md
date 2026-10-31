# Lancer zero dans un conteneur (isolation du dépôt)

**État : écrit et vérifié seulement avec un faux `docker`** (la commande construite est testée, `sh -n` OK). L'image n'a **jamais été
construite** et aucun conteneur n'a été lancé : pas de Docker ni de podman là où ce travail a été fait. À valider chez vous (§ Validation).

## Pourquoi pas un « backend conteneur » dans `--sandbox`

`--sandbox` enveloppe chaque commande (installation, lancement) pour l'exécuter sur l'hôte avec des droits réduits. Or zero télécharge
pour **la plateforme de l'hôte** les runtimes (Node, uv, Go…) dans `~/.zero` et inscrit leurs chemins dans les commandes. Sous macOS ces
binaires ne tournent pas dans un conteneur Linux ; sous Linux, cela ne marcherait qu'avec une image à la glibc compatible. Faire croire que
cela marche aurait demandé de réécrire la résolution des runtimes sans pouvoir la tester. À la place : **zero tourne lui-même dans le
conteneur** — il y installe ses runtimes Linux et lance le dépôt, sans rien savoir de la frontière.

## Utilisation

    docker build -f contrib/Dockerfile -t zerodev:latest .          # une fois (podman : même commande)
    contrib/zero-container.sh ~/code/projet-douteux                  # = zero ~/code/projet-douteux, mais dans un conteneur
    ZERO_PORTS="3000 8000" contrib/zero-container.sh ~/code/projet --services local

Le script passe au conteneur : `--cap-drop ALL`, `no-new-privileges`, limite de processus (`ZERO_PIDS`, 1024) et de mémoire (`ZERO_MEMORY`, 4g),
le dépôt monté en `/work` (**lecture/écriture** : `node_modules` et fichiers générés y atterrissent), un volume `zerodev-home` pour `~/.zero`
(runtimes et caches réutilisés d'un lancement à l'autre). Le reste de votre machine — `~`, clés SSH, autres dépôts — n'est pas visible.

## Limites (à connaître)

- **Réseau non coupé** : l'installation a besoin du réseau ; le projet peut donc émettre des connexions sortantes.
- **Ports** : publiez-les avec `ZERO_PORTS`, et l'application doit écouter sur `0.0.0.0`, pas `127.0.0.1` (sinon elle est injoignable de l'hôte).
- **Services** (Postgres, Redis…) : pas de Docker dans le conteneur, donc `--services local` obligatoire et les binaires correspondants doivent être
  présents dans l'image (ils ne le sont pas : ajoutez-les à `contrib/Dockerfile` au besoin, ou lancez les services sur l'hôte).
- **GPU** : non transmis. **SELinux** (Fedora, podman) : `ZERO_VOLUME_OPTS=":Z"`.
- Le dépôt monté en écriture reste modifiable par le projet : c'est le seul endroit où il peut écrire durablement.
- Un conteneur n'est pas une garantie absolue (noyau partagé) ; en plus de `--cap-drop ALL`, préférez podman sans droits (rootless).

## Validation (à faire, avec un dépôt de confiance d'abord)

1. `docker build -f contrib/Dockerfile -t zerodev:latest .` réussit ; `docker run --rm zerodev:latest --version` affiche la version.
2. `contrib/zero-container.sh examples/node-app` : l'exemple s'installe et répond (avec `ZERO_PORTS=<port>`).
3. Isolation : `contrib/zero-container.sh <dépôt> --cmd "ls ~/.ssh"` ne doit rien montrer de votre dossier personnel.
4. Collez ici la première erreur rencontrée : le plus probable est un paquet système manquant dans l'image.
