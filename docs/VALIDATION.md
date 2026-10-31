# Validation sur une vraie machine

Ce que le sandbox de développement n'a **jamais** pu vérifier : Docker/Podman, macOS, MySQL
d'Oracle, et les démos avec un accès complet à Internet. Chaque étape donne la commande, le
résultat attendu et quoi noter en cas d'écart. Prévoir ~20 min. Prérequis : Python ≥ 3.10, git.

Notez pour chaque étape : OK / KO, OS et architecture (`uname -sm`), `zero --version`, et
collez la fin de la sortie en cas de KO.

## Avant de commencer : l'état de votre machine

    ./bin/zero doctor > doctor.txt        # système, outils, Docker/Podman, services locaux, GPU, accès réseau, disque

Plus simple, **une seule commande pour tout le retour** : `./bin/zero report <votre-dépôt> > retour.txt` (machine + plan du dépôt +
derniers correctifs, chemins personnels masqués ; relisez-le avant de le partager), puis complétez la dernière ligne (« ce qui s'est passé »).

Sinon, joignez `doctor.txt` à votre retour (aucune donnée personnelle : pas de nom de machine ni d'adresse ; seuls figurent
l'utilisateur système, les versions d'outils et l'espace libre). `./bin/zero doctor --json` donne la même chose en JSON.

## Le plus rapide : validation automatique

    python3 scripts/validate_machine.py --out validate-report.txt

Crée de petits dépôts synthétiques (Node, Python, **Go, Rust**, README seul, monorepos, Ruby…), lance zero dessus, sonde le HTTP et imprime
`OK` / `KO` / `SKIP` par vérification (dont `--sandbox`, l'isolation du dossier personnel et le conteneur si l'image existe). Il ne lance que ce
qu'il crée lui-même ; le rapport écrit masque le dossier personnel. Les vérifications `go` et `rust` n'ont jamais tourné chez l'auteur. Les étapes
ci-dessous restent utiles pour ce que le script ne couvre pas (démos sur de vrais dépôts, services, MySQL).

## 0. Installation et tests (toute machine)

    git clone <votre copie> && cd zerodev      # ou dézipper zerodev.zip
    ./bin/zero --version                        # attendu : zerodev <version> (celle du zip ou du dossier cloné)
    ./install.sh                                # facultatif : installe la commande `zero` dans ~/.local/bin
    python3 -m unittest discover -s tests       # attendu : OK (des tests peuvent être ignorés
                                                # si redis-server / postgres / mariadb sont absents)

## 1. Démo intégrée (≈ 2 min, réseau pour télécharger Node/Python/Rust)

    ./demo.sh

Attendu : les 5 exemples démarrent, chacun est arrêté après 15 s, sans erreur Python.
Sur macOS : relever le premier exemple qui échoue (téléchargement de runtime, `uv`, `cargo`).

## 2. Démo avec de vrais dépôts (spécification §16)

    ./demo-real.sh                              # ≈ 4 min : lancements l'un après l'autre

Trois dépôts très différents (Node ; Python/Django ; Flask + Redis + PostgreSQL) sont clonés,
lancés, sondés en HTTP puis arrêtés. Attendu : trois lignes « OK  HTTP 200 … » et
« 3/3 dépôts répondent en HTTP sans édition manuelle » (code de sortie 0). Le troisième
(`microblog`) a besoin de Redis et PostgreSQL : conteneurs si Docker/Podman, sinon binaires
locaux ; sans aucun des deux il s'arrête avec un message (« ÉCHEC »), ce qui est à noter.
Le détail est dans les fichiers `log.txt` / `report.json` indiqués en dernière ligne.

## 3. Conteneurs (Docker ou Podman)

    docker --version        # ou podman --version
    ./bin/zero run --services container examples/fullstack-app

Attendu : un conteneur `zero-…` Redis/PostgreSQL démarre, l'app s'y connecte, et à l'arrêt
(Ctrl-C) `docker ps` n'affiche plus de conteneur `zero-…`. À noter : si le conteneur reste en vie,
le port, et la sortie de `docker ps`.

## 4. Services locaux (sans conteneur)

Installer au moins un serveur (Linux : `apt install redis-server postgresql` ; macOS :
`brew install redis postgresql@16`), puis :

    ./bin/zero run --services local examples/fullstack-app

Attendu : « postgres prêt », « redis prêt », l'app démarre, et rien ne reste après Ctrl-C
(`pgrep -fa "postgres -D|redis-server"` vide). Sur macOS, noter si `initdb` est trouvé
(chemins Homebrew `/opt/homebrew/opt/postgresql@*/bin`).

## 5. MySQL / MariaDB local

MariaDB a été testé ; **MySQL d'Oracle jamais**. Avec un des deux installés :

    python3 -m unittest tests.test_zerodev.TestRealMysqlCompose -v

Attendu : OK (et non « skipped »). Si MySQL d'Oracle : noter la version (`mysqld --version`) et
l'erreur éventuelle d'initialisation (`--initialize-insecure`).

## 5 bis. Isolation `--sandbox` (Linux : bubblewrap ; macOS : sandbox-exec)

    ./bin/zero run --sandbox examples/node-app

Attendu sous Linux avec bubblewrap (`apt install bubblewrap`) : la ligne « mode isolé (bubblewrap) » puis l'exemple
qui répond en HTTP. Sans bubblewrap, ou si le noyau interdit les espaces de noms utilisateur, **zero doit refuser de
lancer** avec un message clair (jamais s'exécuter sans protection).

**Sous macOS** (0.25.0, jamais lancé sur un vrai Mac) : `zero doctor` doit afficher « sandbox-exec (macOS) utilisable » ; puis
`./bin/zero run --sandbox examples/node-app` doit afficher « mode isolé (sandbox-exec) » et l'exemple doit répondre en HTTP.
Si l'installation ou le lancement échoue avec « Operation not permitted », collez la ligne exacte : le profil est trop strict
(l'outil en cause — nvm, Homebrew, `~/Library`… — est à ajouter aux lectures autorisées). Vérifiez aussi qu'un dépôt qui tente
de lire `~/.ssh` ou d'écrire dans `~` échoue bien : `./bin/zero run --sandbox --cmd "cat ~/.ssh/id_rsa" <dépôt>` ne doit rien afficher.
Vérifié jusqu'ici sur un seul noyau : notez le vôtre (`uname -r`) et si `zero doctor` affiche « bubblewrap utilisable ».

## 6. Un dépôt à vous

    ./bin/zero plan <dossier ou URL git>        # affiche le plan sans rien lancer
    ./bin/zero run  <dossier ou URL git>
    ./bin/zero run --sandbox <dossier ou URL git>   # si le dépôt vous est peu connu (Linux)

Noter : commande détectée vs commande réelle, première erreur, et si un correctif automatique
(« correctif automatique : … ») a été appliqué. C'est le test le plus utile pour la suite.

## 7. Option : benchmark réel (petit)

    ZERO_BENCH_CLEANUP=1 ./bin/zero bench benchmark/corpus.demo.txt --full --timeout 120 --out /tmp/bench.json

Lance les 3 dépôts de la démo et écrit un rapport ; `ZERO_BENCH_CLEANUP=1` supprime chaque clone et ses dépendances ensuite.
Attendu : un résumé avec `launched` et `http_ok`. Joindre `/tmp/bench.json` si possible. **N'utilisez pas les gros corpus**
(`corpus.heldout.txt`, `corpus.public*.txt`) avec `--full` sur votre machine : ils exécutent des dizaines ou des centaines de dépôts
tiers (heures, plusieurs Go, code arbitraire) ; ils servent en détection seule (sans `--full`).

## Modèle de retour à me renvoyer

    zero doctor : (coller doctor.txt)

    0. tests unitaires      : OK / KO (n tests, ignorés ?)
    1. demo.sh              : OK / KO — premier exemple en échec :
    2. demo-real.sh         : x/3 — lignes « OK/ÉCHEC » collées :
    3. conteneurs           : OK / KO / non testé (docker ou podman ?) — conteneur resté en vie ? :
    4. services locaux      : OK / KO / non testé
    5. MySQL / MariaDB      : OK / KO / non testé (laquelle ?)
    5b. --sandbox           : OK / refus clair / KO — noyau (uname -r) ou macOS (sw_vers) :
    6. mon dépôt            : URL ou nom, commande détectée vs réelle, première erreur, correctif automatique appliqué ?
    7. benchmark réel       : (facultatif) joindre /tmp/bench.json

Une ligne par étape suffit ; en cas de KO, collez les 30 dernières lignes de sortie.
