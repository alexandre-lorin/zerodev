# Journal des versions et mesures

Déplacé du README (sections ajoutées version après version, de la 0.10.2 à aujourd'hui). Le mode d'emploi est dans `README.md` ;
les chiffres à retenir sont rappelés dans la section « Benchmark » du README.

## Validation automatique sur une vraie machine (sans changement de version)

- `scripts/validate_machine.py` : 13 vérifications portables (Linux/macOS) sur des dépôts synthétiques qu'il crée lui-même — Node, Python (pyproject), **Go**, **Rust**,
  commande déduite du README, script d'outillage refusé, monorepo départagé par le README, monorepo ambigu refusé, message Ruby, `zero report` sans fuite de chemin,
  `--sandbox` (backend annoncé, ou refus clair), isolation du dossier personnel, conteneur (SKIP sans image). Lancement réel + sonde HTTP + arrêt du groupe de processus.
- Vérifié ici : 9 OK + 2 SKIP (pas de backend d'isolation, pas de Docker) ; `go` et `rust` KO ici (ni Go ni Rust, téléchargements bloqués) — **ces deux vérifications n'ont
  jamais tourné avec un vrai toolchain**. **Contrôle négatif** : en cassant volontairement le code dans une copie, le script a signalé KO sur la déduction README, le message
  Ruby et la fuite de chemin (ce dernier contrôle a d'abord échoué : le script imposait un `ZERO_HOME` temporaire qui cachait la fuite ; corrigé).
- `docs/CODEX_PROMPT.md` : message complet à donner à un agent (Codex) pour exécuter toute la validation sur la machine de l'utilisateur et rapporter OK/KO.

## Message clair pour les écosystèmes non gérés (0.26.1)

Un dépôt Ruby, PHP, Java/Kotlin, Elixir, C/C++ ou .NET recevait « aucun projet Node, Python, Rust ou Go détecté », sans nom de son langage. Il reçoit maintenant
« écosystème non supporté : Ruby (Gemfile) — zero gère Node, Python, Rust et Go. À la main : bundle install, puis souvent `bin/rails server`… ; voir le README »
(`FOREIGN_HINTS` dans `plan.py` : indication générale par écosystème, pas une garantie pour ce dépôt). Même ajout quand un `package.json` n'est que l'outillage
front d'un projet étranger. Un dossier sans aucun manifeste garde le message générique. +4 tests (362 au total). Aucun langage n'est ajouté : voir la mesure ci-dessous.

## Mesure : quels langages manquent ? (docs seulement)

Sur les 45 dépôts classés `unsupported` en 0.20, 40 étaient clonables : **30 n'ont rien d'exécutable** (listes « awesome », skills, documentation,
données) — « non supporté » est la bonne réponse ; **10** ont un écosystème étranger : **Ruby 4** (Gemfile), **Java/Kotlin 3** (pom.xml, build.gradle*),
**PHP 2** (composer.json), **C/C++ 1**. Rapporté aux 824 dépôts du corpus, chaque langage ajouté couvrirait **au mieux 0,5 %** (Ruby) ; Java/Kotlin 0,4 %,
PHP 0,2 %. Ajouter l'un d'eux demande de brancher le langage dans `runtimes.py`, `core.py`, `doctor.py` et la détection, sans pouvoir tester un seul lancement
réel ici (ni Ruby, ni PHP, ni Maven/Gradle, sites de téléchargement bloqués). **Décision : ne pas l'ajouter sans demande explicite de l'utilisateur et sans
validation sur sa machine** ; le gain mesuré ne justifie pas du code non testé.

## `zero report` (0.26.0)

- Nouvelle commande : `zero report [dépôt]` imprime **un seul bloc à coller dans un retour d'essai** : version et plateforme, `doctor`, plan du dépôt
  (ou l'erreur, sans planter), 5 derniers correctifs automatiques, et une ligne « ce qui s'est passé » à compléter. Ne lance rien. Le dossier personnel
  devient `~`, le nom d'utilisateur `<user>` (ignoré s'il est de moins de 3 lettres, `root` ou `user`), les codes couleur sont retirés. Les valeurs d'environnement
  n'y figurent jamais (le plan n'affiche que les noms des clés). Raison d'être : réduire à une commande l'effort de retour que tout le reste demande.
  Vérifié : exécution réelle sur un dépôt de test (aucun `/root` dans la sortie), +4 tests (358 au total). Le masquage est un filet, pas une garantie :
  relisez le bloc avant de le partager.

## Isolation par conteneur : zero dans un conteneur (contrib, sans changement de version)

- Pas de backend conteneur dans `--sandbox` : zero télécharge des runtimes pour la plateforme de l'hôte et inscrit leurs chemins dans les commandes ;
  ils ne tourneraient pas dans un conteneur Linux depuis un Mac. À la place : `contrib/Dockerfile` + `contrib/zero-container.sh` font tourner **zero
  lui-même** dans le conteneur (`--cap-drop ALL`, `no-new-privileges`, limites processus/mémoire, dépôt monté en `/work`, volume `zerodev-home`).
- **Vérifié** : syntaxe du script (`sh -n`), construction de la commande avec un faux `docker` (3 tests, 354 au total), refus d'un port non numérique,
  message sans podman/docker, accepte `zero <dépôt> --options`. **Non vérifié** : la construction de l'image et tout lancement réel (pas de Docker ici).
  Limites et checklist dans `docs/CONTAINER.md`.

## Lecture du README : deux défauts corrigés (0.25.2)

Cas limites éprouvés à la main (fins de ligne Windows, chemins avec espaces/accents, `../` et chemins absolus, README de 500 000 lignes) : OK, sauf
deux défauts réels, corrigés avec un test chacun (+4 tests, 351 au total) :
- les blocs de code **indentés de 4 espaces** (README sans clôtures ```) n'étaient jamais lus : les lignes étaient jointes caractère par caractère ;
- les clôtures **`~~~`** n'étaient pas reconnues.
La même lecture de README sert aussi au départage des points d'entrée et des monorepos : ils en profitent. Limite connue : au-delà de 2000 lignes
de code dans le README, la suite est ignorée (volontaire).

## Mesure des entrées ambiguës (docs seulement)

70 des 77 dépôts classés `ambiguous_entrypoint` en 0.20 étaient clonables ; avec le code 0.25.1, **68 restent ambigus, 2 se résolvent**. Les 68 sont
de vrais projets à plusieurs binaires (44 Rust, 20 Go, 4 Python) : `cmd/client` + `cmd/server`, `cargo run -p cli` + `-p daemon`, `download.py` +
`fetch.py`… Aucune preuve ne désigne « le » programme à lancer (pas de `default-run`, pas de Dockerfile ni de README qui tranche). Deviner (par
exemple toujours `server`) serait faux souvent : demander reste le bon comportement, et le plan liste les choix. Aucun changement de code.

## Correction après mesure sur de vrais dépôts (0.25.1)

Mesure : les **99 dépôts clonables** (< 150 Mo) parmi les 228 que la mesure 0.20 classait `ambiguous_monorepo` ou `no_run_command`, version 0.24.7
contre 0.25.0. Résultat : **6 changements, dont 4 douteux ou faux** — `python test-suite/run_manifest.py` (lanceur de tests),
`node scripts/reset-admin.js` (utilitaire d'administration), et deux monorepos mal départagés : `mycelium` (le `cd fastapi-backend` du README mène à
`pytest`/`ruff`) et `hoop` (le vrai lancement est `make run-dev` à la racine ; zero avait choisi l'interface web seule).
Corrections, chacune avec un test tiré du cas réel (+5 tests, 347 au total) :
- README d'un monorepo : le `cd <dossier>` doit être suivi, dans le même bloc, d'une **commande de lancement** (`npm run dev`, `make run`,
  `uvicorn`, `cargo run`…) et non de test/lint/build/installation ; chaque bloc recommence à la racine ; **toute autre commande de lancement du README**
  (racine ou dossier non candidat) rend la preuve ambiguë → on redemande `--project`.
- README seul : les scripts d'outillage sont exclus (dossiers `scripts/`, `tests/`, `tools/`, `examples/`… ; noms contenant reset, migrate, seed,
  setup, build, admin, manifest…).
- Après correction : **2 changements sur 99** — `abrignoni/iLEAPP` (`python ileappGUI.py`, interface graphique : lancement plausible, non vérifié) et
  `quiltdata/quilt` (`catalog/`, d'après « Run catalog locally » : `cd catalog`, `npm start`). **Gain réel : environ 2 % de ces catégories d'échec,
  et aucune mesure du fait que ces commandes démarrent.** C'est modeste ; les catégories sont surtout des bibliothèques sans commande à lancer.
- Leçon : la première version de 0.25.0 passait ses tests et un contrôle sur 30 dépôts sans différence, mais les tests étaient écrits à partir de
  cas imaginés ; seule la mesure ciblée sur les dépôts réellement concernés a montré les erreurs.

## Contrôle de publication PyPI (docs seulement, sans changement de version)

- `python -m build` : sdist + roue OK ; `twine check` : PASSED ; roue installée dans un venv vierge : `zero --version` et `zero plan` OK.
  Noms `zerodev`, `zero-dev`, `zerodev-cli` libres sur PyPI le 27/10/2026. Procédure et réserves dans `docs/PUBLISHING.md`. **Rien publié.**

## README, monorepos, macOS (0.25.0)

- **Commande déduite du README** : en dernier recours (après le Makefile), la première commande de lancement d'un bloc de code du README qui se
  vérifie sur le dépôt : `python x.py` / `python -m mod` (fichier ou paquet présent), `uvicorn|gunicorn|hypercorn mod:app` (outil déclaré +
  module présent), `streamlit run f.py`, `flask run` (flask déclaré + `app.py`/`wsgi.py`), `node f.js`. Écartés : placeholders (`<…>`, `your`,
  `path/to`), pipes, `&&`, variables, `setup.py`, `test*.py`, `manage.py`, `pip`/`venv`/`pytest`/`http.server`. Le langage du plan doit correspondre.
  Une simple mention en prose ne compte pas. Le plan signale la déduction (« rien d'autre ne la confirme »). Vérifié : dépôt synthétique avec
  seulement un README → HTTP 200.
- **Départage des monorepos** : parmi plusieurs sous-projets exécutables, un seul est retenu s'il est **le seul visé** par un script `dev`/`start`/
  `serve`/`develop`/`run` du `package.json` racine (`cd api && …`, `--prefix`, `--filter`, `-w`, `./api/…`) = preuve 3, ou par un `cd <dossier>`
  (y compris `cd ../dossier`) d'un bloc de code du README = preuve 2. Égalité (README avec `cd api` ET `cd web`) → on redemande `--project`.
  Jamais appliqué à un monorepo multi-stack (langages différents), qui garde le lancement `--all` automatique. Vérifié : monorepo synthétique
  api/web + README « cd web » → web lancé, note dans le plan.
- **`--sandbox` sous macOS** : `sandbox-exec` avec un profil SBPL généré (`sandbox.seatbelt_profile`) : écriture refusée sauf dépôt, `~/.zero`,
  `/private/tmp`, `/private/var/folders` ; lecture du dossier personnel refusée sauf dépôt et `~/.zero` ; caches (uv, npm, pip, yarn, pnpm)
  redirigés dans `~/.zero/cache`. `zero doctor` indique le backend. **Non éprouvé sur un vrai Mac** : seuls la génération du profil et la
  sélection du backend sont testées (sous Linux). Limites connues : pas de `/tmp` privé ni d'espace de noms PID/IPC ; outils installés sous
  `~` (nvm, `~/.cargo`) illisibles ; `sandbox-exec` est déprécié par Apple. Checklist ajoutée à `docs/VALIDATION.md` (§5 bis).
- Tests : 323 → 342.

## Vérification HTTP du benchmark (0.10.2)

`zero bench --full` ne se contente plus de « processus vivant » : à la fin du délai il
liste les ports TCP en écoute de l'arbre de processus (lecture de `/proc`, Linux) et
sonde chacun en HTTP. Le rapport contient `listening_ports`, `http` et `http_ok`
(un code 404/500 compte : le serveur parle HTTP). Un worker sans port n'est pas
compté. Premier essai : node-js-getting-started → 200 ; express-locallibrary →
non lancé (MongoDB absent).

### Lot 3 de vieux dépôts (avec sonde HTTP)

8 dépôts, 8 clonés : 5 exécutables, 4 construits, 1 lancé, 0 réponse HTTP (sandbox sans
Redis/PostgreSQL). Rejoué avec les services locaux installés : **microblog → HTTP 200**.
Échecs restants, tous hors correctif automatique pour l'instant :
- `pallets/flask` : la commande détectée (`flask` sans argument) affiche l'aide et sort en code 2 (dépôt de bibliothèque).
- `full-stack-fastapi-template` : le script `dev` appelle `bun`, runtime non géré.
- `sahat/megaboilerplate` : `npm install` échoue (dépendances très anciennes, Node récent).
- `django/djangoproject.com` : lancé, mais `make scss` échoue et aucun port HTTP n'écoute.
- `heroku/ruby-getting-started` : Ruby non supporté ; `expressjs/express`, `gin-gonic/examples` : pas de commande de lancement.

## Bun et CLI nues (0.10.3)

- **bun** : détecté via `bun.lock` / `bun.lockb`, `packageManager: bun`, ou un script `package.json` qui appelle `bun run|x|install`. Installation `bun install`, lancement `bun run dev|start`. Le binaire vient du repli npm de `ensure_pm`. Vérifié : `full-stack-fastapi-template` → frontend HTTP 200 (port 5173).
- **CLI sans argument** : un script console qui n'affiche que son aide (`flask`, `django-admin`, `celery`, `uvicorn`, `pytest`…) n'est plus pris pour une commande de lancement (liste `NEEDS_ARGS_CLIS` dans `plan.py`). `pallets/flask` passe donc de « commande fausse, code 2 » à « aucune commande principale trouvée ».
- Limite : sur le template FastAPI, seul le frontend est lancé ; le backend (Docker Compose) ne l'est pas. La liste de CLI est faite à la main.

## npm compatible avec les vieux Node (0.10.4)

Quand `nodejs.org` est inaccessible, zero se rabat sur le paquet npm `node`, qui ne fournit
que le binaire : c'est alors le `npm` récent du système qui tournait sous un vieux Node
(`Cannot find module 'node:path'`). zero installe désormais à côté un npm compatible
(Node ≤ 6 → npm 3, < 12 → npm 6, < 18 → npm 8, sinon rien) et crée les liens `npm`/`npx`.
Vérifié sur `sahat/megaboilerplate` (Node 6.1.0) : le bon npm est sélectionné (3.10.10).
Non vérifié de bout en bout : dans le sandbox de test, Node 6 rejette le certificat du
proxy (`SELF_SIGNED_CERT_IN_CHAIN`), donc l'installation des paquets n'a pas pu aboutir.
Ce chemin ne sert que sans accès à nodejs.org ; avec accès, le npm fourni avec Node est utilisé.

## Variables libpq pour PostgreSQL (0.10.5)

En plus de `DATABASE_URL`, zero expose `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` et
`PGDATABASE` pour le service PostgreSQL (jamais par-dessus l'environnement ou le `.env`
existants). Les apps qui laissent l'hôte vide (Django, `psql`) joignent ainsi la base de
zero au lieu de chercher un socket Unix. Constaté sur `django/djangoproject.com` : l'erreur
« socket introuvable » disparaît.
Limite connue : ce dépôt fixe en dur le rôle `djangoproject` (et lit ses secrets dans un
fichier), que zero ne crée pas (`role "djangoproject" does not exist`). Piste : reprendre
`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` du `docker-compose.yml` du dépôt.

## Identifiants PostgreSQL du docker-compose (0.10.6)

Si le `docker-compose.yml` du dépôt déclare `POSTGRES_USER`, `POSTGRES_PASSWORD` ou
`POSTGRES_DB` en littéral (`- VAR=x` ou `VAR: x`, ou `${VAR:-défaut}`), zero les utilise
pour le conteneur **et** pour `DATABASE_URL` / `PGUSER` / `PGPASSWORD` / `PGDATABASE`. Avec le
PostgreSQL local (sans conteneur), il crée ce rôle (superutilisateur) et cette base. Les
valeurs non littérales (`${SECRET}`) sont ignorées et les valeurs par défaut de zero
(`zero` / `zero` / `app`) restent pour le reste. PostgreSQL uniquement pour l'instant.
Constaté sur `django/djangoproject.com` : le serveur Django démarre (l'erreur
`role "djangoproject" does not exist` disparaît). Non vérifié : une requête HTTP ; le dépôt
signale 93 migrations non appliquées, que zero n'exécute pas.

## Migrations Django automatiques (0.10.7)

Avant le lancement, zero exécute `manage.py migrate --noinput` quand : le projet est Django,
**zero gère lui-même une base** (PostgreSQL ou MySQL, conteneur ou local) et aucune commande du
dépôt (Procfile compris) ne contient déjà `migrate`. SQLite et les bases externes ne sont jamais
touchées. Un échec de migration avertit sans interrompre le lancement. Le mode `--all` applique la
même règle stack par stack (0.10.9).
Constaté sur `django/djangoproject.com` : les 93 migrations s'appliquent et l'avertissement
« unapplied migrations » disparaît ; le serveur répond en HTTP (code 400 sur `127.0.0.1`,
vraisemblablement un `ALLOWED_HOSTS` du dépôt, non investigué).

## Identifiants MySQL/MariaDB du docker-compose (0.10.8)

Même principe que pour PostgreSQL : `MYSQL_USER`, `MYSQL_PASSWORD` et `MYSQL_DATABASE`
littéraux du `docker-compose.yml` alimentent `DATABASE_URL` et le conteneur. Avec le serveur
local (MariaDB ou MySQL), zero crée la base et le compte applicatif (tous droits, pour
`localhost`, `127.0.0.1`, `::1` et `%`), de façon idempotente. Le mot de passe **root** reste
celui de zero (`zero`) : un `MYSQL_ROOT_PASSWORD` du dépôt n'est pas repris. Vérifié en réel
avec MariaDB (connexion avec le compte du dépôt, deux démarrages de suite). Non testé :
MySQL d'Oracle ; `MYSQL_USER=root` (refusé par l'image officielle) n'est pas traité à part.

### Migrations en mode `--all` (0.10.9)

Chaque stack Django qui dépend d'une base gérée par zero est migrée avant le lancement
commun. Vérifié sur un mini dépôt (backend Django + PostgreSQL local, frontend Node) :
migrations appliquées, backend sur 8000, frontend sur 3000.

## Validation sur machine réelle

La checklist de ce que le développement n'a pas pu vérifier (Docker/Podman, macOS, MySQL
Oracle, démos complètes) est dans `docs/VALIDATION.md`.

## Lot 4 et correctifs psycopg2 (0.10.10)

Huit dépôts publics (Go, Flask, Node, Django), sonde HTTP active. Avant correctifs :
`sample-nodejs`, `render flask-hello-world`, `render express-hello-world` → **HTTP 200**
(3/3 lancés). Échecs et suites :
- `gothinkster/flask-realworld-example-app` : `psycopg2` ne compile pas (en-tête `pg_config.h`
  absent alors que `pg_config` existe). Le diagnostic ne le voyait pas : **`run_tee` ne gardait
  que les 200 dernières lignes** et l'erreur était plus haut. Il garde désormais aussi les 150
  premières, et la détection couvre `pg_config.h` / `libpq-fe.h` / `postgres_ext.h`. Résultat :
  substitution par `psycopg2-binary`, gunicorn écoute sur 8000.
- `digitalocean/sample-django` : `psycopg2-binary==2.9.3` n'a pas de wheel pour Python 3.12.
  Si le fichier est déjà en `-binary`, zero passe directement au retrait du pin. Résultat : le
  serveur Django démarre (sans requête HTTP vérifiée).
- `miguelgrinberg/flask-video-streaming` : requirements insatisfaisables dans le dépôt
  (`flask==2.0.2` exige `jinja2>=3`, le fichier épingle `jinja2==2.11.3`). Non corrigé.
- `gothinkster/golang-gin-realworld-example-app` : Go introuvable, `go.dev` bloqué dans le sandbox
  de test (non évaluable ici). `docker/getting-started` : aucune commande de lancement.

## Lot 5 et deux correctifs (0.10.11)

Huit dépôts Python/Node. Avant correctifs : `digitalocean/sample-flask` (8080),
`sample-expressjs` (3000) et `render nextjs-hello-world` (3000) → **HTTP 200** ; deux dépôts
Render (`fastapi-hello-world`, `django-hello-world`) ont échoué au clonage (introuvables) ;
`Flask-SocketIO-Chat` : aucune commande de lancement. Deux correctifs :
- **Serveur Python absent des requirements** (`flask-boilerplate` : Procfile `gunicorn …`, mais
  gunicorn n'est pas dans `requirements.txt`, Heroku l'installe lui-même) : la récupération
  installe `gunicorn`, `uvicorn`, `hypercorn`, `daphne`, `waitress`, `granian` ou `flask` dans le
  venv quand la commande répond « not found ». Le dépôt n'est pas modifié.
- **`pip install -e .` qui échoue sur un dépôt d'application** (`microblog-api` : pyproject
  d'outillage, hatchling ne trouve pas de paquet) : si une étape `-r requirements` a déjà réussi,
  cette étape est ignorée et l'appli est lancée depuis ses sources. Résultat : gunicorn écoute sur 8000.
Reste non corrigé : `flask-boilerplate` démarre mais échoue au chargement
(`ImportError: TextField` : le code utilise une API retirée de WTForms 3).

## Pipenv (0.11.0)

Un dépôt avec `Pipfile` mais sans `requirements.txt` est maintenant détecté (il ne l'était pas) :
- paquets : `Pipfile.lock` (versions exactes, sans entrées git/chemin local) sinon `Pipfile` ;
  `*` devient « dernière version », les extras sont conservés ;
- version de Python : `[requires] python_full_version` / `python_version` ;
- installation : un `uv pip install` avec les paquets en arguments (aucun fichier écrit) ;
- un `requirements.txt` présent reste prioritaire ; le Pipfile compte aussi pour les monorepos.
Vérifié sur une mini app Flask Pipenv : Python 3.12, page « pipenv ok » sur le port 5000.
Limites : seule la section `[packages]` est installée (pas `[dev-packages]`) ; les correctifs
psycopg2 par fichier ne s'appliquent pas encore à ce mode ; essai réel sur un seul dépôt synthétique.

## Lot 6 : Pipenv / poetry réels (0.11.1)

Quatre dépôts. `postmanlabs/httpbin` (Pipfile + `setup.py`, Python 3.6 demandé) a révélé deux
trous, corrigés :
- **Python trop ancien pour uv** : `uv` ne fournit plus 3.6/3.7. Le repli automatique passe maintenant
  à 3.8 (le plus ancien disponible) pour toute version < 3.8, en plus du repli « 3.8.1 → 3.8 ».
- **Versions épinglées du `Pipfile.lock` inutilisables** (flask 1.0.2, gevent 1.3.4… ne s'installent
  pas sur Python 3.8) : si le dépôt a aussi un `setup.py`/`pyproject.toml`, l'étape « lock » est
  ignorée et les dépendances du projet suffisent (`Plan.soft_steps`).
Résultat : httpbin **s'installe** mais ne démarre pas : `ImportError: BaseResponse` (API retirée de
Werkzeug ≥ 2.1, non traitée : ce serait une table de plafonds de versions à entretenir).
Autres dépôts : `responder` lance une CLI qui n'affiche que son aide (liste `NEEDS_ARGS_CLIS`,
non étendue cas par cas) ; `fastapi-realworld-example-app` (poetry) et `python-socketio` : aucune
commande de lancement trouvée.

## Remesure de la détection après 0.10.2 → 0.11.1

Mêmes corpus, détection seule (`benchmark/results/public-v4.json`, `heldout-v2.json`) :
- corpus réglé à la main : 69/96 (71,9 %) → **68/96 (70,8 %)** ;
- hors-échantillon : 25/37 (67,6 %) → **24/37 (64,9 %)** des dépôts clonés.
Un seul dépôt change, dans les deux : `pallets/flask`, qui comptait comme « exécutable » à cause de la
commande `flask` nue (elle n'affiche que son aide ; écartée depuis la 0.10.3). Ce recul de 1 est
voulu : la mesure est plus honnête, aucune autre régression. Les dépôts clonés sont ceux d'aujourd'hui,
pas ceux de la mesure d'origine. Une première passe avait montré 32 « clone_failed » : disque du
sandbox plein, pas un défaut de zero ; rejouée après nettoyage.

## Démo §16 et spécification (0.11.2)

- La spécification d'origine est conservée dans `docs/05-zerodev.md`.
- `demo-real.sh` réalise le §16 : trois dépôts publics très différents (`node-js-getting-started`,
  `python-getting-started`, `microblog`), lancés puis **sondés en HTTP automatiquement** ; le script
  affiche un verdict par dépôt et sort en code 0 seulement si les trois répondent. Corpus :
  `benchmark/corpus.demo.txt`. Exécuté ici de bout en bout : 3/3 en HTTP 200 (Redis et PostgreSQL
  locaux, sans conteneur).
- Limite du §16 : aucun des trois n'est un projet *abandonné*. Les vieux projets essayés échouent :
  `heroku/python-sample` (Flask 0.9, `wsgiref` réservé à Python 2, non installable en Python 3),
  `heroku/node-js-sample` (Node 4.0.0 introuvable dans le repli npm du sandbox, `nodejs.org` bloqué ;
  non évaluable ici). `flasky` (2017) démarre mais demande `SERVER_NAME`.
- Faux positif connu : un script qui lance son serveur web avec `--daemon` (`flask-by-example` :
  `heroku.sh`) se détache de zero ; zero ne le voit ni ne l'arrête, et le rapport indique « lancé »
  alors que seul un worker tourne.

## 0.12.0 : démons, Makefile, corpus de 500 dépôts

**Corpus de 500 dépôts (spécification §15)** : `benchmark/corpus.public500.txt`, constitué par une
règle fixe et non à la main (API GitHub, `language:<L> stars:500..3000 archived:false`, tri par date de
mise à jour, 100 par langage python/javascript/typescript/go/rust, doublons des autres corpus retirés).
98 dépôts dont la taille API dépasse 300 Mo sont écartés (un seul clone pèse jusqu'à 1,8 Go) : **402
évalués**, détection seule (`benchmark/results/public500-v1.json`) :

| | dépôts | exécutables | taux |
|---|---|---|---|
| Node | 127 | 98 | 77 % |
| Go | 80 | 49 | 61 % |
| Python | 62 | 32 | 52 % |
| Rust | 73 | 35 | 48 % |
| autres / sans langage | 60 | 0 | — |
| **Total** | **402** | **214** | **53,2 %** (51,5 % hors Makefile) |

Les deux corpus réglés à la main donnaient 71 % et 65-68 % : ils **surestimaient d'une quinzaine de
points** ; 53 % est le chiffre à retenir. Beaucoup de ces dépôts sont des bibliothèques (rien à lancer),
donc ce taux n'est pas un « taux d'échec » de zero. Détection seule : on ne sait pas combien
démarreraient. Biais : dépôts récemment actifs, popularité moyenne, pas de géants. Toujours loin des 1000.

**Corrigé grâce à ce corpus** : un `Cargo.toml` avec `members = ["."]` (motif glob invalide) faisait
planter zero ; `safe_glob` couvre ces motifs. Le benchmark ne s'arrête plus sur une exception d'un
détecteur (statut `detector_error`, 0 sur ce corpus). Le benchmark en détection seule traite les dépôts en
flux et **supprime chaque clone** après classement (le disque du sandbox s'était rempli : 261 faux
« clone_failed »).

**Repli Makefile (§2)** : sans autre commande, une cible `run`/`dev`/`start`/`serve`/`server` non
vide du Makefile devient la commande (`make run`), notée « déduite du Makefile ». Effet : 7 dépôts sur 402,
dont la plupart douteux (`make run` d'opérateurs Kubernetes comme kubeai ou stackrox). Ils sont comptés à
part (`inferred_from_makefile`, `detection_rate_strict_of_cloned`).

**Démons** : zero se déclare « sous-reaper » du noyau (Linux) : un serveur lancé avec `--daemon` ou par
double fork est adopté par zero, visible de la sonde HTTP, et arrêté avec le reste (SIGTERM puis SIGKILL).
Vérifié par test unitaire (un `sleep` détaché est adopté puis arrêté). **Non prouvé sur un vrai dépôt** :
le `gunicorn --daemon` de `flask-by-example` échoue de son côté (aucun port), donc le cas réel reste à voir.

## 0.12.1 : lancement réel d'un échantillon du corpus 500

Tirage au hasard (graine 42) parmi les dépôts « exécutables » de `public500-v1.json`, Node et Python
seulement (toolchains Go/Rust inaccessibles ici). Prévu : 30. **Évalués : 22** (15 Node, 7 Python) : le disque
du sandbox s'est saturé (`node_modules`, roues Python lourdes) et a interrompu l'expérience
(`benchmark/results/live-v10-sample500.json`, 4 clonages tués par le disque écartés).

| 22 dépôts « exécutables » | construits | lancés (processus vivant) | **répondent en HTTP** |
|---|---|---|---|
| Node (15) | 10 | 6 | 4 (200) |
| Python (7) | 5 | 3 | 1 (503) |
| **Total** | **15 (68 %)** | **9 (41 %)** | **5 (23 %)** |

À lire avec prudence : 22 dépôts, échantillon interrompu, plutôt les plus légers. « Répond en HTTP » est un
mauvais critère pour une CLI ou un worker (plusieurs « lancés » sans HTTP sont des outils en ligne de
commande). En clair : **sur ces 22 dépôts que zero déclare lançables, environ un sur quatre sert effectivement
une page**, et le 53 % de détection du corpus 500 ne dit rien de ce taux. Échecs fréquents : installation de
dépendances (`npm ci`, roues), versions de Node/outils trop récentes, services externes.

Benchmark : le mode `--full` est désormais séquentiel et en flux (clone → lancement → nettoyage), avec
`ZERO_BENCH_CLEANUP=1` pour supprimer clone, venv et runtimes Node de repli après chaque dépôt ; le rapport
est sauvegardé (écriture atomique) après chaque dépôt, donc une interruption ne perd plus rien.

## 0.12.2 : causes d'échec de l'échantillon réel

Lecture des 13 échecs de l'échantillon de 22 dépôts (0.12.1), par cause :
- **Outils en ligne de commande pris pour des serveurs** (citgm, dario, NUR, datacontract-cli, bub…) : ils
  affichent leur aide puis quittent. Le benchmark les classe maintenant à part (`cli_tool`, `cli_tools`) au lieu
  de les compter comme des échecs ou des serveurs. Non résolu côté détection : zero lance toujours la commande.
- **Installations lentes coupées par le délai** (probo, takt, ScienceClaw, saleor-dashboard) : ce n'étaient pas des
  échecs. Chaque ligne porte maintenant `phase` (`install_failed`, `install_timeout`, `run`) et le résumé compte
  `install_timeout`. À refaire avec un délai plus long (ou `--timeout 180`).
- **Aucune roue pour Python 3.14** (`pose2sim` : `opensim` publie cp311 à cp313 seulement) : zero lit la liste des
  ABI dans le message d'uv, et replie sur le plus récent Python couvert (ici 3.13), même quand `plan.version`
  n'est qu'une contrainte (`>=3.11`). Vérifié : le repli se déclenche sur `pose2sim` ; l'installation complète n'a pas
  pu être menée à terme (le disque du sandbox s'est rempli avec les roues d'`opensim`), donc non confirmé de bout en bout.
- **Non traités** : build qui échoue (`kaos-tools`), `npm ci` qui échoue (`ing-bank/lion`), dépendances
  ESM/Node à l'exécution (`brightdata-mcp`, `DefiLlama-Adapters`), services externes (`wildduck`).

## 0.12.3 : repli de `npm ci`

Si `npm ci` échoue, zero choisit un remplacement d'après l'erreur (chacun une seule fois, journalisé) :
lockfile désynchronisé de `package.json` (« can only install packages when… in sync », « Missing … from lock
file ») → `npm install` ; conflit de pairs (`ERESOLVE`) → `npm install --legacy-peer-deps`. Les autres erreurs
(réseau, etc.) ne déclenchent rien. Vérifié sur un mini projet au lockfile volontairement désynchronisé : repli,
installation, démarrage. **Non vérifié sur `ing-bank/lion`**, le dépôt de l'échantillon qui échouait sur `npm ci`
(très gros, disque du sandbox) : sa cause exacte n'a pas été conservée, ce n'est donc pas prouvé qu'il relève de
ce cas. `npm install` peut écrire `package-lock.json` dans le dépôt cloné.

## 0.12.4 : second échantillon, garde-fou disque, `--ignore-scripts`

**Correction d'un constat précédent** : le manque de disque du sandbox venait surtout du **magasin global de
pnpm (4,1 Go)** et du cache de bun (~1 Go), que le benchmark alimentait sans jamais les vider, et non d'une limite
incompressible (`node_modules` et roues seuls ne l'expliquent pas). Après nettoyage : 5,8 Go libres. Le nettoyage
automatique (`ZERO_BENCH_CLEANUP=1`) vide désormais ces caches et le benchmark s'arrête proprement, avec rapport partiel
(`stopped_disk_low`, `not_run`), si l'espace reste sous 900 Mo. Les résultats de l'échantillon de la 0.12.1 (22 dépôts)
ont pu être faussés par ce manque d'espace : à lire avec réserve.

**Second échantillon** (graine 7, 8 Node + 8 Python, dépôts différents du premier, délai 90 s, sans incident disque ;
`benchmark/results/live-v11-sample2.json`) : 16 dépôts, **10 construits, 6 lancés, 2 répondent en HTTP (404 : un
serveur de développement sans page à la racine), 5 outils en ligne de commande, 1 installation encore en cours au
délai**. Autrement dit : très peu de vrais serveurs web dans ce tirage, beaucoup d'outils CLI/agents.

**Repli `--ignore-scripts`** : si un script de cycle de vie (`postinstall`…) fait échouer `npm ci|install`,
`pnpm install` ou `yarn`, zero relance la même commande avec `--ignore-scripts` (une fois, journalisé, dernier
recours : les modules natifs à compiler ne fonctionneront alors pas). Vérifié sur `Orkas-AI/Orkas`, dont un
postinstall télécharge un modèle d'embedding : l'installation passe et l'app se lance. Non vérifié sur
`juspay/xyne-spaces` (monorepo pnpm énorme : il a rempli le disque pendant l'essai).

Échecs restants du second tirage : `uv sync --frozen` qui échoue à la construction (`cutile-python`, `avibe`),
`sglang-omni` (PyTorch, `--torch-backend=auto`), `xyne-spaces` ; non analysés (trop lourds ou causes non relevées).

## 0.12.5 : version calculée depuis git (setuptools-scm, hatch-vcs)

Un projet dont la version est calculée depuis git (`setuptools-scm`, `hatch-vcs`, `vcs-versioning`) échoue à la
construction quand l'historique manque : clone `--depth 1` (celui du benchmark), archive sans `.git`. Zero le
détecte dans l'erreur et relance avec `SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0` (et ses variantes), une fois,
journalisé. Vérifié sur un projet `setuptools-scm` sans dépôt git : installation puis lancement. Le nombre de
tours de correctifs d'installation passe de 4 à 6 (plusieurs correctifs peuvent s'enchaîner).
Sur `avibe-bot/avibe` (hatch-vcs), le correctif fait avancer le build mais le dépôt exige ensuite `ui/dist`
(interface à construire avant : `force-include` de hatch) : échec non traité, c'est un prérequis du dépôt.
Conséquence pour la mesure : les échecs `uv sync --frozen` des échantillons réels venaient au moins en partie des
clones superficiels, pas des dépôts.

## 0.12.6 : troisième échantillon réel, Node par plage, étapes facultatives

**Troisième échantillon** (graine 11, 12 Node + 12 Python, jamais vus, délai 75 s, sans incident disque ;
`benchmark/results/live-v12-sample3.json`, mesuré **avant** les correctifs ci-dessous) : 24 dépôts, **17 construits,
7 lancés, 4 répondent en HTTP** (gale, phanpy, sveltia-cms : 200 ; gloomberb : 404), **4 outils CLI**, 5 échecs
d'installation, 2 installations encore en cours au délai. Avec le second tirage (16 dépôts) : 40 dépôts, 6 qui
répondent en HTTP (15 %), dont presque tous des applications Node de type Vite. Petits échantillons, à ne pas
extrapoler.

**Version de Node par plage** : un `engines.node` de la forme `>=20.0.0` était lu comme « exactement 20.0.0 » (la
borne basse) : Next.js, qui exige 20.9, refusait de démarrer (`wind-comic`). Un petit évaluateur de plages semver
(`>=`, `>`, `<`, `^`, `~`, jokers, `||`) choisit maintenant la **LTS la plus récente qui convient** (en ligne : via
`index.json` ; hors-ligne : majeures LTS 24/22/20/18…). Une version exacte ou partielle reste respectée (`20.11.0`,
`20` → dernier 20.x). Vérifié hors-ligne : `>=20.0.0` → Node 24.21.0.

**Étapes facultatives** : `manage.py collectstatic` n'empêche plus le lancement s'il échoue (`overmind` : l'installation
entière était bloquée) ; il avertit et continue (`Plan.optional_steps`). **`bun install`** est couvert par le repli
`--ignore-scripts` (`better-sqlite3` de `oh-my-agent`).

Non traités dans ce tirage : `yarn install` (`MatrixMedia`), `-e .` qui échoue (`dd-trace-py`, `forge3d`), serveurs
Electron/TUI sans écran (`token-monitor`, `selkies`), CLI sans argument (`pynguin`, `loushang`).

## 0.12.7 : rejeu des 24 dépôts avant/après, nouvelle tentative après échec disque

Mêmes 24 dépôts qu'en 0.12.6, rejoués avec les correctifs (`benchmark/results/live-v13-sample3-replay.json`) :

| | avant | après |
|---|---|---|
| construits | 17 | 19 |
| lancés (processus vivant) | 7 | 9 |
| répondent en HTTP | 4 | 4 |
| outils CLI | 4 | 5 |
| échecs d'installation | 5 | 3 |

Trois dépôts changent, chacun grâce à un correctif précis : `oh-my-agent` (échec `bun install` → lancé, repli
`--ignore-scripts`), `overmind` (échec `collectstatic` → il démarre, c'est un outil CLI), `wind-comic` (Node 20.0.0
refusé par Next.js → Node 24, construit et lancé ; Next compile encore au bout des 75 s, donc pas de réponse HTTP).
Les 21 autres sont inchangés. **Le nombre de réponses HTTP n'a pas bougé** : ces correctifs réparent des
installations mais ne transforment pas des CLI/agents en serveurs.

Le rejeu groupé avait d'abord classé `wind-comic` en échec d'installation : disque plein (`ENOSPC`) au mauvais moment,
pas le dépôt. Le benchmark réessaie maintenant **une fois** après avoir tout vidé quand l'échec d'installation vient
du disque (`retried_after_disk_failure`) ; `wind-comic` rejoué seul est dans le rapport (note incluse). Un dépôt Next.js
a besoin de plus de 1,5 Go : le seuil de 900 Mo n'évite pas tous les cas.
Limite : 24 dépôts, comparaison avant/après sur le même échantillon (pas indépendant des correctifs qui en sont issus).

## Quatrième échantillon réel, indépendant (Node, graine 23)

Tirage de 24 dépôts Node jamais vus parmi les 62 « exécutables » restants du corpus 500, lancés avec les correctifs
0.12.7 (`benchmark/results/live-v14-sample4-node.json`). **22 évalués** (le benchmark s'est arrêté avant les 2 derniers,
disque saturé ; rapport partiel conservé). Aucun correctif n'a été conçu à partir de ces dépôts.

| 22 dépôts Node | |
|---|---|
| construits | 12 |
| lancés (processus vivant) | 9 |
| **répondent en HTTP** | **6** (5 × 200, 1 × 401) |
| outils CLI | 1 |
| installations encore en cours au délai de 75 s | 6 |
| échecs d'installation | 4 (3 × `pnpm install`, 1 × `npm ci`) |

Soit **27 % de réponses HTTP** sur les dépôts Node, du même ordre que le premier tirage (4/15). Les 6 « install_timeout »
sont de gros monorepos (xen-orchestra, waveboxapp…) : la mesure sous-estime ce taux, un délai plus long serait nécessaire.
**Pas de test indépendant pour Python** : il ne restait que 3 dépôts Python exécutables non utilisés ; les chiffres Python
disponibles viennent d'échantillons déjà exploités pour trouver des correctifs. Les échecs `pnpm install` (3 sur 4) sont
le cas le plus fréquent non traité : causes non analysées.

## 0.12.8 : analyse des 4 échecs d'installation du tirage Node

Aucun des quatre n'était un défaut du dépôt qu'un correctif général aurait réparé, sauf un :
- **`pnpm install` ×3 (`agentconnect`, `gsd-pi`, `cohub`) : disque plein**, pas le dépôt. `agentconnect` rejoué seul avec
  1,7 Go libres épuise encore l'espace (`ENOSPC` sur `@resvg/resvg-js`) ; `cohub` et `gsd-pi` laissent des fichiers
  temporaires pnpm coupés. Ma lecture précédente (« échecs `pnpm install` fréquents ») était donc **fausse** : ce sont des
  artefacts du sandbox. Le benchmark reconnaît mieux le disque plein (`database or disk is full` en plus d'`ENOSPC`) et
  classe l'échec **`disk_full`** (compté à part dans `disk_full`) quand il persiste après une nouvelle tentative.
- **`npm ci` sur `MyAgents` : `EBADDEVENGINES`.** Le dépôt déclare `devEngines.packageManager` = npm ≥ 11.15.0, alors que le
  Node choisi livre npm 10.9.7. Zero lit la plage exigée dans l'erreur, installe ce npm dans un dossier dédié
  (`~/.zero/runtimes/npm-<plage>`), le place en tête du `PATH` pour l'installation **et** le lancement, puis réessaie.
  Vérifié sur un mini projet (exige npm ≥ 11 : installation, puis démarrage). **Non vérifié sur MyAgents** : dépôt trop
  gros, il a rempli le disque pendant l'essai.
Conséquence : le taux de 27 % de réponses HTTP du tirage Node ne change pas, mais ses « échecs d'installation » réels
tombent de 4 à 1 (réparé), et 3 sont à ranger sous « disque » plutôt que sous « dépôt ».

## 0.12.9 : monorepos lents rejoués à 240 s, lockfile inutilisable

Les 6 dépôts Node dont l'installation n'avait pas fini à 75 s, rejoués avec un délai de 240 s
(`benchmark/results/live-v15-slow6-240s.json`) : plus aucun « install_timeout ». **3 construits, 2 lancés, 0 réponse
HTTP, 3 échecs d'installation** (2 × `npm ci`, 1 × `yarn install`). Le délai de 75 s sous-estimait donc surtout le temps,
pas la réussite.

Les deux `npm ci` (`lxserver`, `sandbase-harness`) : le lockfile pointe vers des **miroirs de registre** (Tencent,
npmmirror) ; ici npm refuse ces URL (`EALLOWREMOTE`, config `allow-remote=none` du sandbox : propre à cet environnement)
et, avec `--replace-registry-host=always`, les versions n'existent que sur le miroir (404). Nouveau repli : `npm ci`
→ **`npm install --no-package-lock`** quand l'erreur est `EALLOWREMOTE` ou `E404` (les conflits de pairs et lockfiles
désynchronisés gardent la priorité). Les versions peuvent alors différer de celles du lockfile. Vérifié sur `lxserver` :
installation puis serveur à l'écoute (port 9527). Non rejoué sur `sandbase-harness` (même erreur). Non traité :
`xen-orchestra` (`yarn install`, monorepo à espaces de travail), `waveboxapp` (`scandir` d'un dossier absent).

## 0.13.0 : dépendances par variante matérielle (spécification §10)

Plans lus sur de vrais projets d'IA (clones superficiels, **aucune installation ni lancement**, ils pèsent plusieurs Go) :
`ComfyUI` et `stable-diffusion-webui` donnaient déjà un plan cohérent (`--torch-backend=auto`, roues CPU signalées sans GPU,
fichiers modèles à télécharger). `oobabooga/text-generation-webui` échouait : ses dépendances sont rangées par variante
(`requirements/full/requirements{,_amd,_apple_silicon,_cpu_only}.txt`, `requirements/portable/…`).

Zero choisit maintenant la variante d'après le matériel détecté (`gpu.pick_requirements_variant`) quand il n'y a pas de
`requirements.txt` ni de jeu « base/common/main… » : groupe `full` (sinon `main`, `base`, `default`, `all`, sinon le premier),
puis NVIDIA → fichier de base, AMD → `_amd`, Apple Silicon → `_apple_silicon`, Mac Intel → `_apple_intel`, Vulkan →
`_vulkan` ou CPU, **aucun GPU → `_cpu_only`** (sinon la base). Le choix est signalé en note avec le moyen de le changer.
Sur ce sandbox (sans GPU), text-generation-webui donne `requirements/full/requirements_cpu_only.txt` et `python server.py`.

**Corrigé au passage** : l'empreinte du dépôt ignorait `requirements/**/*.txt` ; un dépôt dont les seuls manifestes sont
là avait l'empreinte d'une chaîne vide (`e3b0c442…`), la même que tous les autres. Elle inclut désormais ces fichiers
(toutes variantes, indépendante du matériel). Conséquence : un `zero.lock.json` ou une entrée de registre existants pour
de tels dépôts seront vus comme « dérivés » une fois.

Limites : **choix jamais éprouvé sur du vrai matériel** (pas de GPU ici) ni par une installation complète ; il suit des
conventions de nommage (`_cpu_only`, `_amd`, `_apple_silicon`…) vues sur un seul projet. `karpathy/nanoGPT` (aucun
manifeste, dépendances dans le README) reste sans plan : « scripts Python à la racine mais aucun manifeste reconnu ».

## 0.14.0 : scripts Python sans manifeste (dépendances déduites des `import`, §2)

Un dépôt de scripts Python à la racine **sans aucun manifeste** (`karpathy/nanoGPT`, dépendances seulement dans le
README) ne donnait qu'une erreur. Zero lit maintenant les `import` des scripts racine (analyse syntaxique, sans les
exécuter), retire la bibliothèque standard, les modules locaux (fichiers et dossiers de la racine) et des noms trop
génériques (`utils`, `config`, `model`, `lib`… : risque d'installer un homonyme PyPI sans rapport), puis installe le reste
(table `PY_IMPORT_MAP` : `cv2` → `opencv-python`, `yaml` → `pyyaml`…, sinon le nom du module avec `_` → `-`).
Point d'entrée : l'unique script avec garde `if __name__ == "__main__"`, sinon l'unique script que personne n'importe ;
**s'il y en a plusieurs, zero propose les choix au lieu d'en deviner un**. La note du plan dit que les dépendances sont
déduites. Sur nanoGPT : `numpy, tiktoken, torch, transformers, wandb` + `--torch-backend=auto`, et quatre scripts proposés
(`bench`, `configurator`, `sample`, `train`).

Limites : nom PyPI **supposé** égal au nom du module (un module dont le paquet porte un autre nom échouera, la récupération
installera alors par import) ; seuls les scripts de la racine sont lus (nanoGPT importe aussi `datasets`, `tqdm` depuis un
sous-dossier : non vus) ; installation et lancement complets non faits (PyTorch, plusieurs Go). Un cas existant change :
un dépôt avec un `server.py` et un sous-projet Node n'est plus rejeté, il reçoit un plan Python déduit (le sous-dossier
reste ignoré, `--project` fonctionne).
Empreinte : pour un dépôt sans aucun manifeste, les scripts racine entrent dans l'empreinte (sinon tous ces dépôts avaient
celle d'une chaîne vide, donc le même verrou de registre) ; avec un manifeste, le code source n'y entre toujours pas.
Un test de la suite avait échoué de façon intermittente : voir « Test des signaux » ci-dessous.

## Test des signaux : cause probable de l'échec intermittent, et test devenu creux

`test_ignored_sigint_still_cleans_children` cherchait des restes avec `ps | grep app.py` sur **toute la machine** : un autre
`zero`, un benchmark ou une commande contenant « app.py » le faisait échouer (cause probable des échecs isolés, jamais
reproduits en 12 passes propres). En le corrigeant j'ai constaté qu'il pouvait aussi **réussir sans rien vérifier** : si zero
ne lançait pas le script (nom d'entrée inconnu), il n'y avait rien à nettoyer. Il utilise désormais un nom de script
unique, lance le script via `--cmd`, **vérifie que le script a démarré**, puis qu'aucun processus portant ce nom ne reste
(0,7 s au lieu de ~90 s d'attente à vide). Aucun changement de code du produit.

## Corpus de 1000 dépôts (spécification §15) : second lot et bilan cumulé

Second lot `benchmark/corpus.public500b.txt` (500 dépôts, même règle fixe, tranche **100 à 499 étoiles**, API GitHub du
2026-10-10, détection seule, `benchmark/results/public500b-v1.json`). 78 dépôts de plus de 300 Mo (taille API) sont écartés :
**422 évalués**, 0 clonage échoué, 0 erreur de détecteur. **240 exécutables = 56,9 %** (55,7 % hors commandes déduites du
Makefile). Par langage : Node 106/143 (74 %), Go 57/78 (73 %), Python 39/74 (53 %), Rust 38/70 (54 %).

**Bilan cumulé des deux lots : 824 dépôts évalués sur 1000 sélectionnés** (176 écartés pour leur taille) :

| | dépôts | exécutables | taux |
|---|---|---|---|
| Node | 270 | 204 | 75,6 % |
| Go | 158 | 106 | 67,1 % |
| Python | 136 | 71 | 52,2 % |
| Rust | 143 | 73 | 51,0 % |
| sans langage reconnu | 117 | 0 | — |
| **Total** | **824** | **454** | **55,1 %** (53,6 % hors Makefile) |

Statuts : 454 exécutables, 165 sans commande de lancement (bibliothèques pour la plupart), 88 points d'entrée ambigus, 63 monorepos
ambigus, 54 non supportés. **Lecture** : la détection d'une commande est stable autour de **54-55 %** d'un lot à l'autre (53,2 % puis
56,9 %), loin des 72 % des corpus choisis à la main. Détection seule : rien n'a été lancé sur ces 824 dépôts ; ce taux ne dit ni
que la commande est la bonne ni qu'elle démarre (voir les échantillons réels : environ un « exécutable » sur quatre sert une page).
Biais : dépôts récemment actifs, popularité modérée (100 à 3000 étoiles), dépôts de plus de 300 Mo exclus (donc surtout des
applications légères), cinq langages interrogés (le premier lot et le second ne se recoupent pas).

## 0.14.1 : vieux dépôts (§16) et Python 2

**Sélection** : GitHub, `pushed:<2019-01-01`, 300 à 4000 étoiles, Python et JavaScript, ≤ 200 Mo, 116 dépôts (derniers commits de 2015 à
2018). **Détection seule : 30/116 exécutables (26 %)**, 28 non supportés, 42 sans commande, 15 ambigus. **Lancement réel de 20 d'entre eux**
(tirage au hasard, graine 5, délai 90 s ; `benchmark/results/live-v16-old-repos-20.json`) : 8 construits, 2 lancés, **2 répondent en HTTP 200 sans
aucune édition** : `streamproc/MediaStreamRecorder` (dernier commit juillet 2018, serveur sur le port 9001) et `arscan/encom-boardroom`
(octobre 2017 ; la page répond, mais l'API GitHub qu'elle appelle refuse les requêtes sans authentification). **C'est le §16 atteint**, avec un
taux très faible : 2 sur 20 (10 %), tous deux des applications Node.

Causes des échecs (18 sur 20) : environ la moitié des projets Python sont du **Python 2** (`print` sans parenthèses, `cPickle`, `theano`,
`cudarray`), des dépendances introuvables (`meatier`, `RocketMap` : `npm install` ; `Vue-cnodejs` : `yarn install`), des ressources disparues
(`registry.bower.io`), Node récent face à du code de 2016 (`reapp`, `ttystudio` : `MODULE_NOT_FOUND`), une installation lente (`home-automation`).
Taille réduite, échantillon filtré sur ≤ 200 Mo et sur les dépôts où une commande est trouvée.

**Python 2 expliqué** : à l'échec de l'installation ou du lancement, une trace typique de Python 2 (`Missing parentheses in call to 'print'`, `No module
named cPickle/urllib2…`) déclenche un message clair (« ce projet semble écrit pour Python 2… à migrer avec `2to3` ou à lancer avec un Python 2 »). Dans la
déduction des dépendances sans manifeste, les modules propres à Python 2 (`cPickle`, `urllib2`, `ConfigParser`, `Tkinter`…) ne sont plus installés comme paquets
PyPI et sont signalés en note. Vérifié sur `fraser-hemp/gradify`. Zero ne fournit toujours pas Python 2 ni ne porte le code.

## 0.15.0 : `zero doctor`

Nouvelle commande `zero doctor [--json] [--no-network]` : système et architecture, Python, utilisateur (root ou non), IPv6 sur la
boucle locale, espace libre dans `ZERO_HOME`, versions de `git uv node npm pnpm yarn bun cargo go`, Docker/Podman (présence **et** démon
joignable), services locaux de repli (redis, postgres, MySQL/MariaDB, MongoDB), GPU, et accès réseau (HEAD, 5 s) à github.com, pypi.org,
registry.npmjs.org, nodejs.org, go.dev et static.rust-lang.org. But : joindre un diagnostic fiable à chaque retour d'essai sur une machine
réelle (modèle de retour ajouté à `docs/VALIDATION.md`). Aucune donnée personnelle collectée (ni nom de machine, ni adresse).
Sur ce sandbox elle reflète les limites déjà relevées (pas d'IPv6, `nodejs.org`/`go.dev`/`static.rust-lang.org` inaccessibles, ni Docker ni
GPU). Corrigé en passant : `go` n'a pas de `--version` (`go version`).

## 0.16.0 : outils en ligne de commande (arguments après `--`)

Environ un « exécutable » sur quatre seulement sert une page ; beaucoup d'autres sont des outils en ligne de commande qui, lancés sans argument,
affichent leur aide et quittent. Deux changements : (1) `zero run <dépôt> -- <arguments>` transmet tout ce qui suit `--` à la commande lancée (arguments
protégés ; pour `npm run|start|test`, zero insère `--` sinon npm consomme les options : défaut trouvé par un test de bout en bout ; ignoré avec un
avertissement pour un Procfile, refusé s'il n'y a pas de commande) ; (2) une sortie rapide (< 8 s) qui affiche un usage/une aide donne un message clair
au lieu d'un échec : « ressemble à un outil en ligne de commande… installé ; lancez-le avec vos arguments ». Même heuristique que le benchmark
(`recovery.CLI_HELP`). Vérifié sur un mini outil Node (usage sans argument, résultat avec `-- data.txt --verbose`). Limite : détection par texte
(« Usage: », « --help »…), donc un serveur qui imprime une aide au démarrage puis quitte serait aussi classé « outil ».

## 0.17.0 : distribution (trois modes d'installation)

Avant : `./bin/zero` depuis le dépôt, ou `pip install -e .`. Maintenant : (1) `install.sh` : lanceur `~/.local/bin/zero` vers le dossier cloné
(refuse un Python < 3.10, avertit si `~/.local/bin` n'est pas dans le `PATH`, `ZERO_INSTALL_DIR` pour changer de dossier) ; (2) `scripts/build_pyz.py` :
exécutable unique `dist/zero.pyz` (zipapp, 63 Ko, shebang `/usr/bin/env python3`), indépendant de l'arborescence source ; (3) `pip install .`.
**Défaut corrigé** : `pyproject.toml` annonçait la version `0.10.1` alors que le produit avançait ; la version vient désormais de `zerodev.util.VERSION`
(une seule source). Vérifié : `zero.pyz --version` et `doctor`, `pip install` dans un environnement vierge (commande `zero` et métadonnées
`0.16.0`), `install.sh` avec un faux dossier personnel, refus d'un Python trop ancien. **Non vérifié** : macOS, `pipx` (non installé ici), publication sur
PyPI (aucun paquet publié, aucun nom réservé), Windows (hors périmètre). « git clone && zero » sur une machine sans Python reste impossible.

## 0.18.0 : exécution isolée `--sandbox` (spécification §3)

`zero run --sandbox` enveloppe **chaque étape d'installation et chaque lancement** (`run_tee`, `Supervisor.spawn` ; aussi en `--all`) dans bubblewrap :
système en lecture seule (`--ro-bind / /`), dossier personnel remplacé par un tmpfs (secrets invisibles), `/tmp` privé, écriture uniquement dans le dépôt et
`~/.zero`, espaces de noms PID et IPC isolés, `--die-with-parent`. Les caches (`uv`, `npm`, `pip`, `yarn`, `pnpm`) sont redirigés vers `~/.zero/cache` (sinon ils iraient
dans le dossier personnel masqué et seraient perdus). Le réseau reste partagé (un serveur de développement doit rester joignable).
**Vérifié en réel** (bubblewrap 0.9.0, ce sandbox) : un faux projet dont le `postinstall` lit `~/.ssh` et écrit dans `~` et `/usr` : secret **invisible**, écriture dans `~` sans
effet sur l'hôte (tmpfs privé), `/usr` **refusé**, écriture dans le dépôt possible ; le serveur répond en HTTP **depuis l'hôte** ; aucun processus ni `bwrap` résiduel après l'arrêt ;
`npm install` fonctionne dans le sandbox. Tests : construction des arguments (ordre des montages), refus sans bubblewrap, et un test de confinement réel (ignoré si
bubblewrap est inutilisable). `zero doctor` indique si l'isolation est disponible.
**Limites, à ne pas minimiser** : pas de barrière contre un code exploitant le noyau ni contre les requêtes réseau sortantes ; les fichiers lisibles du système hors dossier personnel
restent lisibles ; les actions propres à zero (téléchargement des runtimes, conteneurs, services locaux) ne sont pas dans le sandbox ; **macOS non supporté** (`sandbox-exec` non utilisé) ;
**Docker/Podman comme alternative d'isolation non faite** ; testé sur un seul noyau (celui du sandbox : espaces de noms utilisateur autorisés — ce n'est pas le cas partout, d'où le refus explicite).

## 0.19.0 : départager les points d'entrée ambigus (README, Dockerfile, compose)

Sur les 824 dépôts évalués, 151 étaient ambigus : 63 monorepos et **88 points d'entrée multiples** (57 Rust, 28 Go, 3 Python). Zero ne retient maintenant un
choix que s'il est **le seul appuyé par une preuve textuelle** : `ENTRYPOINT`/`CMD` d'un Dockerfile (racine, `docker/`, `build/`, `deploy/`) ou `command`/`entrypoint` d'un compose
(poids 3), ou une commande de lancement du README dont le nom est la **cible** (`cargo run … --bin/-p NOM`, `./target/release/NOM`, `go run|build ./cmd/NOM`, `python NOM.py` ; poids 2).
Une mention en prose, un nom cité comme argument ou comme dossier (`--config NOM/config.json`) ne compte pas ; une égalité laisse la liste de choix. Le plan note la
source et les alternatives (`--cmd` pour corriger).
**Mesure** (les 88 cas, détection seule) : **13 départagés (15 %)**, 75 restent ambigus. Une première version, trop permissive, en départageait 20 dont des faux positifs que j'ai
trouvés en contrôlant les lignes de preuve (`yellowstone-grpc-geyser`, un plugin cité en argument ; `./` pris pour une preuve) : resserrée. **Contrôle manuel des 12 premiers** : 9 reposent
sur un `ENTRYPOINT`/`CMD` (solide), 3 sur une commande du README (plausible ; `oxideterm-cli` n'y est lancé qu'avec `doctor`). **Aucun n'a été lancé** : les toolchains Go et Rust sont
inaccessibles dans ce sandbox, donc « le bon point d'entrée » n'est pas prouvé. Les 63 **monorepos** ambigus ne sont pas traités. Non remesuré sur les 824 (le taux de détection de 55,1 %
monterait au plus d'environ 1,6 point). Bench : champ `entry_from_docs` et compteur `entry_from_docs`.

## 0.20.0 : monorepos multi-stack (sous `src/`, `app/`, `apps/`) lancés tout seuls

Sur les 63 monorepos ambigus des corpus, **aucun** n'était reconnu comme multi-stack : la détection ne cherchait `backend/`, `frontend/`, `api/`, `web/`… qu'à la racine, alors que beaucoup les
rangent sous `src/` ou `app/` (`src/backend` + `src/frontend`). Elle regarde maintenant aussi `src/`, `app/` et `apps/` (`app/` n'est un conteneur que s'il contient lui-même de tels
dossiers). Un monorepo dont les sous-projets sont de **langages différents** (≥ 2) et au plus **3** stacks est lancé tout seul, comme avec `--all` (message explicite, ports distincts,
URL du backend donnée au frontend) ; au-delà, ou avec `--project`/`--cmd`, zero demande toujours de choisir. **Bug trouvé par un test** : `AmbiguousProject` ne conservait pas son attribut
`multistack`. **Vérifié en réel** : un monorepo `src/backend` (Python) + `src/frontend` (Node) : backend sur 8000, frontend sur 3000 qui interroge le backend (`frontend -> backend ok`), aucun
processus résiduel.
**Effet réel sur les 63** : seulement **5 sont reconnus multi-stack** (`couchers`, `open-wearables`, `gradient`, `patchies`, `dex`), les 58 autres restent ambigus : monorepos de paquets du même langage,
bibliothèques, documentation, où « tout lancer » n'a pas de sens. Le lancement automatique de ces 5 n'a **pas** été testé sur les vrais dépôts (mobile Expo, MCP, daemons…) : seul le cas synthétique l'est.
Le benchmark classe toujours ces dépôts « ambiguous_monorepo » (champ `multistack` et compteur `multistack_monorepos`).

## 0.20.1 : remesure de la détection sur les 823 dépôts avec le code 0.20

Mêmes dépôts que le bilan 0.12 (clones d'aujourd'hui), `benchmark/results/public1000-remeasure-v0.20.json`. **473/823 = 57,5 % avec commande** (55,1 % avant) ;
**hors heuristiques de dernier recours : 440/823 = 53,5 %** (53,6 % avant : le noyau « sûr » n'a pas bougé). Les 33 dépôts gagnés viennent exclusivement des heuristiques ajoutées depuis :
**13** points d'entrée départagés par preuve (README/Dockerfile) + **12** commandes de Makefile (comptées dès 0.12) + **7** dépôts de scripts sans manifeste dont les dépendances sont déduites des `import`.
Changements de statut, tous expliqués : 13 ambigus → exécutables (départage), 7 non supportés → exécutables (imports déduits, dont un **plugin Calibre**, qui n'est pas lançable : faux positif
assumé de cette heuristique, d'où son comptage à part), 2 non supportés → ambigus, 1 exécutable → sans commande (`react-big-schedule` : son `package.json` n'a plus de script `dev`, changement du dépôt
et non de zero), 1 clonage échoué (dépôt devenu inaccessible). **Aucune régression de zero.**
Le rapport compte maintenant `deps_deduced` à part, et le taux « strict » exclut les trois heuristiques (Makefile, preuve README/Dockerfile, imports déduits).
Incident : en lançant 9 clonages en parallèle le disque est tombé à 239 Mo ; ajout d'une attente de disque pour la détection en parallèle (`wait_for_disk`, ≥ 700 Mo libres) et relance à 6 clonages en parallèle.

## Hygiène (sans changement de version) : analyse statique et tests par mutation

`pyflakes` sur `src`, `tests` et `scripts` : 5 avertissements bénins après vingt versions (imports et une variable inutilisés), corrigés ; le code est propre.
**Tests par mutation** sur trois comportements récents (on casse volontairement le code et on vérifie que les tests échouent) : le sandbox (ne plus masquer le dossier
personnel) et l'insertion de `--` pour npm sont bien détectés ; le départage des points d'entrée **survivait** à la suppression du seuil minimal de preuve (un seul choix analysable
sans aucune preuve était retenu). Un test a été ajouté, et la mutation rejouée est maintenant détectée. Trois mutations seulement : ce n'est pas une mesure de la qualité de toute la
suite (227 tests), seulement un contrôle ciblé après avoir déjà trouvé un test creux (test des signaux).

## Emballage : le zip contenait des artefacts et `build/` était suivi par git

En rejouant l'expérience d'un premier utilisateur (décompression du livrable dans un dossier vierge, tests, exemples), deux défauts d'emballage sont apparus, présents depuis plusieurs versions : (1) le zip était fait
depuis le **dossier de travail** et embarquait 54 fichiers superflus (`__pycache__`, `build/`) ; (2) `build/` (artefact de `pip install .`) avait été **commité par accident** avec un `git add -A` (18 fichiers suivis).
Corrigé : `build/` retiré du suivi et ignoré ; nouveau script `scripts/export_zip.py` qui construit le zip depuis un **export propre du dépôt** (fichiers suivis + historique), refuse un dépôt aux modifications non
validées et signale tout fichier suspect suivi (test du motif ajouté). Vérifié sur le livrable décompressé : 0 fichier superflu, 227 tests OK, `./bin/zero --version`, et les exemples `python-app` (HTTP 200 sur 8000),
`node-app` (3000) et `multistack-app` (8000) démarrent depuis ce dossier, sans processus résiduel. Au passage, j'ai de nouveau tué mon propre shell avec un `pgrep -f` dont le motif figurait dans ma commande.

## 0.21.0 : starters populaires (Next, Vite, Django, Flask) et trois correctifs

16 starters/templates choisis par l'API GitHub (par framework, par nombre d'étoiles, légers), lancés en réel (délai 100 s, `benchmark/results/live-v17-starters.json`, **seconde passe, après correctifs** ;
le rapport de la première passe a été supprimé par erreur de ma part par un `rm` trop large : seules ses grandes lignes m'en restent, cinq échecs `yarn install`/`pnpm install`). Seconde passe : **6 construits,
5 lancés, 3 répondent en HTTP** (`mantinedev/vite-template` 200, `jelmerdejong/flask-app-blueprint` 200, `django-react-boilerplate` 404), 2 monorepos ambigus, 3 sans commande, 1 installation encore en cours, 4 échecs
d'installation. Un échantillon aussi petit ne donne pas un taux ; ce sont surtout des défauts à corriger. Trouvés et corrigés :
- **pnpm ≥ 10 : `ERR_PNPM_IGNORED_BUILDS`** (scripts de dépendances non approuvés traités comme une erreur, version 12 comprise) touchait 3 starters Vite/Next. `--ignore-scripts` n'évite **pas** cette erreur
  (vérifié) ; zero relance avec `--config.strict-dep-builds=false` (comportement par défaut de pnpm : scripts non exécutés, sans erreur). Vérifié : `whylisa/vite-react-template-typescript` s'installe et démarre (port 3001).
- **Corepack ne joint pas `repo.yarnpkg.com`** (proxy d'entreprise, domaine filtré ; cas du sandbox) : `yarn install` échouait. Zero règle `COREPACK_NPM_REGISTRY` sur le registre npm (celui configuré s'il y en a un) et réessaie.
  Vérifié à la main (l'installation Yarn 4 avance) ; **la correction automatique n'a pas été rejouée sur un dépôt réel après son codage**, seulement testée en unitaire.
- **`manage.py` dans un sous-dossier** (`<projet>/manage.py`, `src/manage.py`) n'était pas vu (seule la racine l'était). Zero le cherche dans UN SEUL sous-dossier direct dont le contenu ressemble à Django ou Flask-Script
  (plusieurs candidats : rien) et lance `python <sous-dossier>/manage.py runserver` ; `collectstatic` et les migrations suivent. Vérifié : `flask-api-starter-kit` → `python src/manage.py runserver` ; `django-hackathon-starter` atteint
  l'installation, qui échoue pour une vraie raison : Django 1.7.6 de 2015, dépendances en syntaxe Python 2 (message explicite).
Restent sans traitement : `langchain-nextjs-template` (`yarn patch` : « cannot apply hunk »), `tedivms-flask` (installation Python), `Flask-User-starter-app` (Flask ancien face à Jinja récent), `fbone` (seulement un `wsgi.py` pour mod_wsgi),
monorepos `materio…` et `vite-templates`, `maomao1996/vitepress-nav-template` (échec `pnpm install` à retraiter, réseau instable).

## 0.22.0 : anciens projets Python (repli de version, casses d'API en cascade)

Suite du test des starters : `tedivm/tedivms-flask` (2020, Flask) a servi de fil rouge ; trois défauts de zero apparaissent l'un derrière l'autre, tous corrigés.
- **Ancien pin qui ne se construit pas** (`pyyaml==5.4` face à Cython 3, pas de roue pour Python 3.10+) : après l'échec de construction d'un paquet **épinglé** (hors en-têtes système manquants, hors code Python 2),
  zero essaie Python 3.9, puis 3.8, sans jamais descendre sous le plancher du projet (`>=3.10` → refus). Vérifié à la main : Python 3.9 installe ces dépendances, 3.10 et 3.11 non.
- **Bug trouvé en route : après une rétrogradation de Python, la phase d'installation oubliait ses correctifs déjà posés** (le plan est recalculé, le fichier psycopg2 temporaire disparaît) mais les croyait toujours
  appliqués, donc ne les rejouait pas. La phase de lancement le faisait déjà correctement ; l'installation aussi maintenant. Tours de correctifs d'installation : 6 → 8.
- **Casses d'API connues, en cascade** (`PY_API_BREAKS`, table courte à entretenir) : `jinja2` ≥ 3.1 (`escape`, `Markup`…), `markupsafe` ≥ 2.1 (`soft_unicode`), `werkzeug` ≥ 2.1 / 3 (`BaseResponse`, `url_quote`…), `flask` ≥ 2.3
  (`escape`, `Markup`), `itsdangerous` ≥ 2.1 (`json`), `sqlalchemy` ≥ 2 (`no attribute '__all__'`, `Engine.execute`), `wtforms` ≥ 3 (`TextField`). Si le Flask **installé** est ancien (< 2.2, lu dans le venv), zero pose d'un coup l'ensemble
  cohérent d'avant 2022 (`flask<2.1 werkzeug<2.1 jinja2<3.1 itsdangerous<2.1 markupsafe<2.1`) au lieu de plafonner un seul paquet, qui laisserait les autres casser un à un ; avec un Flask moderne, un seul plafond.
  Budget de correctifs au lancement : 2 → 4 tentatives (chaque correctif n'est tenté qu'une fois).
**Résultat réel sur `tedivms-flask`** : l'installation passe (Python 3.9, pin psycopg2 retiré) puis les trois correctifs s'enchaînent (ensemble Flask d'avant 2022, `sqlalchemy<2`) ; l'application échoue enfin sur **sa propre configuration**
(`Config setting SECRET_KEY is missing`) : une variable que l'utilisateur doit fournir, pas une dépendance. Il ne démarre donc pas sans intervention. **Limites** : table de plafonds à entretenir (un cas inconnu retombe à l'échec) ; un plafond
peut casser un projet qui utilisait en fait la version récente (chaque correctif est journalisé) ; vérifié en réel sur un seul dépôt ; `httpbin` (`BaseResponse`) et `Flask-User-starter-app` ne sont pas rejoués.

## 0.23.0 : vieux projets Flask rejoués (httpbin, Flask-User-starter-app) et configuration d'exemple

Rejeu des deux dépôts qui avaient motivé la table de casses d'API de la 0.22.0, avec les ports vérifiés libres avant chaque essai (un premier essai avait attribué à tort le serveur d'un test précédent,
resté vivant sur le port 8000, au dépôt suivant : erreur de méthode de ma part, refaite proprement).
- **`postmanlabs/httpbin`** (Pipfile + setup.py, Python 3.6 demandé) : Python 3.8, étape `Pipfile.lock` ignorée, `gunicorn` installé, puis `BaseResponse` → ensemble Flask d'avant 2022 : **HTTP 200** (il échouait sur `BaseResponse` en 0.11.1).
- **`lingthio/Flask-User-starter-app`** (2018) : Python 3.6 → 3.8, puis trois casses d'API enchaînées (`jinja2` ≥ 3.1, `werkzeug` ≥ 1.0 pour `from werkzeug import url_encode`, `sqlalchemy` ≥ 2), puis le module `app.local_settings` absent.
  Deux ajouts : un second ensemble de versions pour les très vieux Flask (`flask<1.1 werkzeug<1.0 jinja2<3.0 itsdangerous<1.2 markupsafe<2.0`, imports de `werkzeug` au niveau supérieur) et **la copie d'un modèle de configuration** :
  si le module de configuration absent a un modèle voisin unique (`local_settings_example.py`, `config_local.py.example`, `…_sample`, `…_template`, `….dist`), zero le copie (`cp -n` : jamais d'écrasement ; aucune copie s'il y a deux modèles ou si le module existe).
  Résultat : **HTTP 200** (`Running on http://127.0.0.1:5000/`).
**Le dépôt est modifié dans ce cas** : un nouveau fichier de configuration y est créé (généralement ignoré par git), c'est signalé dans la description du correctif. Limites : copie de la configuration d'exemple telle quelle (clés factices) ;
motif très général mais vérifié en réel sur un seul dépôt ; la table de casses d'API reste à entretenir.

## Rejeu de 10 dépôts Python qui avaient échoué (avec le code 0.23.0)

`benchmark/results/live-v18-python-replay.json`, délai 120 s, mêmes dépôts que les échantillons précédents (donc **pas** un échantillon indépendant). Résultat : **9 construits, 2 lancés, 1 en HTTP
(microblog, déjà en 200), 3 outils en ligne de commande, 1 installation encore en cours** (`aiavatarkit`, téléchargement de roues NVIDIA). Changements de statut : `kaos-tools` passe à « lancé » (une interface
en terminal), `datacontract-cli` et `NUR` sont désormais classés outils CLI ; les autres sont inchangés. **Gain réel faible** : les échecs restants ne viennent plus des dépendances mais de la nature des projets
(interface en terminal qui exige une invite, serveur de flux qui exige un écran, outil CLI, modèles ML à télécharger). Ce n'est pas un défaut de zero qu'un correctif général réparerait ; je ne cherche donc plus de gain de ce côté.

## 0.24.0 : version de Python/Node déduite du Dockerfile ou de la CI (spécification §2) : utile en théorie, **sans gain mesuré**

Quand rien ne fixe la version (ni `.python-version`, `runtime.txt`, `.tool-versions`, `requires-python`, `Pipfile`, ni `.nvmrc`, `.node-version`, `engines.node`), zero cherche la version que le projet utilise vraiment : `FROM python:3.9` /
`FROM node:20` d'un Dockerfile d'abord (c'est ce qui est livré), puis la CI (GitHub Actions `python-version` / `node-version`, GitLab `image:`, Travis `python:` / `node_js:`). Une matrice de versions → la plus récente (Node au plus la LTS
actuelle, Python au plus 3.14, jamais une version non stable) ; expressions `${{ }}`, pypy et nightly ignorés. La note du plan dit d'où vient la version (`déduit de Dockerfile…`). Désactivable : `ZERO_NO_RUNTIME_HINT=1`.
**Couverture** (240 dépôts Node/Python du corpus) : parmi ceux **sans version déclarée**, 58 % des projets Node (44/76) et 35 % des projets Python (7/20) reçoivent un indice, presque tous depuis `.github/workflows` (43 sur 51).
**Test A/B sur les mêmes 13 dépôts, avec puis sans l'indice** (`benchmark/results/live-v19-runtime-hint-ab.json`, lancements réels) : **12 identiques, 1 pire avec l'indice, 0 meilleur** (`obsidian-local-images` : Node 16 lu dans une CI ancienne
→ installation en échec, alors qu'il se lançait avec la LTS par défaut). Défaut corrigé : **les versions en fin de vie venant de la CI sont ignorées** (Node < 20, Python < 3.10) ; le Dockerfile n'est pas filtré. Second défaut trouvé par la
mesure : des matrices contenant `3.15` faisaient proposer une version Python pas encore stable ; plafonnées.
**Conclusion honnête** : aucun bénéfice démontré sur cet échantillon de 13 ; le défaut (la dernière version stable) fonctionne déjà dans la plupart des cas, et l'échelle de repli attrape les autres. Je garde la fonction (elle est conservatrice, désactivable,
et la spécification la demande), mais **elle ne doit pas être présentée comme une amélioration prouvée**. Limite : le filtre de fin de vie est une constante à mettre à jour (`NODE_OLDEST_FROM_CI`, `PYTHON_OLDEST_FROM_CI`).

## Rejeu de deux starters notés « non traités » (code 0.24.0)

- **`realpython/flask-boilerplate`** (jamais rejoué depuis l'ajout de la table de casses d'API) : `gunicorn` absent du fichier de dépendances → installé ; `ImportError: TextField` (WTForms 3) → `wtforms<3` ;
  **HTTP 200** sur le port 8000, ports vérifiés libres au départ. Il échouait sur `TextField` en 0.10.11.
- **`langchain-ai/langchain-nextjs-template`** : l'installation `yarn install` passe maintenant et Next.js démarre (« Ready in 555ms », port 3000 ; réponse HTTP non vérifiée par `curl`). Mon ancienne note « `yarn patch` : cannot apply hunk »
  désignait en réalité un échec de Yarn lui-même (téléchargement via corepack bloqué), corrigé en 0.21.0 par le registre npm : **ma lecture de la cause était fausse**.

## 0.24.1 : documentation et aide alignées sur le produit

Relecture de `zero --help` et du README face au comportement réel après vingt-cinq versions. Corrigé : l'aide de `--services` omettait MySQL/MariaDB (ajoutés en 0.9.0) ; l'aide de `--all` ne disait pas que les monorepos
de 2-3 stacks de langages différents sont lancés automatiquement ; le README ne documentait ni `--sandbox` ni `--` dans la table des options, ni les variables d'environnement (`ZERO_HOME`, `ZERO_REGISTRY`,
`ZERO_NO_RUNTIME_HINT`, `ZERO_BENCH_CLEANUP`, `PORT`), ni les modules `procs.py`, `sandbox.py`, `doctor.py`, et son « principe : refuser plutôt que deviner » ignorait les deux exceptions (point d'entrée appuyé par une preuve,
monorepo multi-stack). Aucun changement de comportement.

## Traçabilité du benchmark (sans changement de version)

Ajouts : `benchmark/README.md` (ce que mesure chaque champ, chaque corpus, chaque fichier de résultats, avec la version du code et les réserves ; les 27 fichiers aux noms voisins n'étaient pas expliqués) et
`benchmark/build_corpus_rule.py` (reproduit la règle fixe des deux corpus de 500 ; vérifié contre l'API en réel sur un petit tirage ; les résultats dépendent de la date, d'où les corpus conservés). Corrigé :
l'en-tête de `corpus.public.txt` affirmait que l'API GitHub est inutilisable sans jeton, ce qui n'était vrai qu'au moment de sa constitution. Le README principal renvoie vers `benchmark/README.md`.

## 0.24.2 : relecture et simplification du code (sans changement fonctionnel, un message corrigé)

Mesure d'abord (`radon`, `vulture`) : complexité cyclomatique **moyenne B (6,4)**, mais une fonction de rang **F (55) : `install_deps`**, suivie de `run_project` (41), `detect_node`/`detect_python` (35), `diagnose` (33), `summarize` (30) ;
presque aucun code mort (deux restes supprimés : `STATUSES`, `in_tty`).
**Refactorings faits**, chacun vérifié avant de continuer :
- **`install_deps` : 55 → 8.** La boucle de 8 tours reste ; chaque correctif devient une petite fonction (`_fix_corepack`, `_fix_psycopg2_swap`, `_fix_npm_ci`…) évaluée dans l'ordre de `INSTALL_FIXERS`, sur un état partagé (`InstallState`).
  Les subtilités sont conservées : l'échange psycopg2 sans effet tombe sur le retrait du pin dans le même tour, `devEngines` retombe sur les suivants s'il échoue, la rétrogradation de Python remet les correctifs à zéro.
  **Filet de sécurité écrit AVANT de toucher au code** : 14 tests de caractérisation (étapes shell qui échouent avec le bon message), passés sur l'ancien code puis sur le nouveau ; un test a été vérifié par mutation (il échoue si la remise à zéro est retirée).
  **Vérifié en réel après coup**, résultats identiques à avant : `tedivms-flask` (Python 3.9, psycopg2, ensemble Flask, SQLAlchemy, jusqu'à `SECRET_KEY`), `lxserver` (`npm ci` sans lockfile, serveur à l'écoute), starter pnpm (`strict-dep-builds`).
- **`summarize` (bench) : 30 → 18**, par table de compteurs. **Comparé à l'ancienne version sur les 124 résumés des vrais rapports : 0 différence** (clés, valeurs et ordre).
- **`diagnose` (récupération) : 33 → liste de 9 règles ordonnées** (`RULES`). **Comparé à l'ancienne version sur 552 cas** (23 sorties d'erreur × 6 plans × 2 états de Flask × 2 jeux de correctifs déjà tentés, dont 364 produisant un correctif) : **0 différence**.
**Un message trompeur corrigé** (il existait avant) : le passage à Python 3.9 pour un ancien paquet épinglé qui ne se construit pas (`pyyaml==5.4`) était annoncé « un module retiré de Python 3.12 est requis » ; il dit maintenant la vraie cause (test ajouté, trois raisons distinctes).
Un ancien test qui lisait le code source (jugé faible) est supprimé : le test de comportement correspondant le remplace. Complexité moyenne : B (6,4 → 6,1).
**Non fait, à dessein** : `run_project` (41), `detect_node`/`detect_python`/`detect_rust` (32-35), `make_plan` (29), `dispatch` (25) restent complexes. Les détecteurs sont des cascades de règles bien couvertes par les tests mais je n'ai pas de filet de caractérisation
équivalent pour `run_project` (services, supervision, récupération au lancement) : le refactorer sans lui serait un pari.

## 0.24.3 : `run_project` simplifié (41 → 7), même méthode

`run_project` (rang F, complexité 41) est découpé en `_prepare_environment`, `_setup_run_environment` (services, variables, PORT, migrations), `_supervise` (la boucle de lancement avec ses deux types de relance :
`_retry_with_other_python` et `_apply_run_fixes`), `_report_outcome` et `_record_success`. Complexité : **41 → 7** (la plus complexe des nouvelles fonctions : 10) ; moyenne du projet **6,04** (B).
Même méthode qu'en 0.24.2 : **15 tests de caractérisation écrits d'abord** (supervision, services, correctifs, PORT, .env, migrations, messages) en simulant tout ce qui touche au système, passés sur l'ancien code puis sur le nouveau ;
**4 mutations détectées** (remise à zéro des correctifs après rétrogradation de Python retirée, arrêt des services retiré, budget de relances ignoré, `.env` de l'utilisateur écrasé). Un détail préservé : l'environnement final (remplacé par la
rétrogradation de Python) sert à l'enregistrement du verrou.
**Vérifié en réel après le refactoring** : `fullstack-app` (PostgreSQL et Redis locaux démarrés, variables injectées, Procfile web + worker, services arrêtés proprement, ports libérés), `python-app` et `node-app` (HTTP 200, ports libres au départ),
et un monorepo `src/backend` + `src/frontend` (backend et frontend répondent, aucun processus résiduel). Un test de plus pour la 0.24.2 a servi de modèle : tests d'abord, refactoring ensuite, comparaison enfin.
**Reste complexe** (rang D/E) : `detect_node`, `detect_python`, `detect_rust` (32-35), `make_plan` (29), `dispatch` (25), `detect_stacks` (23), `node_satisfies` (23), `detect_go`, `entry_evidence`, `script_imports` (21-22), `run_stacks` (21).
Ce sont des cascades de règles de détection bien couvertes par les tests ; leur découpage demanderait une comparaison ancien/nouveau sur le corpus de clones (≈ 25 min de clonage) pour être sûr.

## 0.24.4 : détecteurs et `make_plan` simplifiés, avec une comparaison ancien/nouveau sur 298 dépôts

**Après une réinitialisation du sandbox** (le dossier de travail avait disparu ; le dépôt a été restauré depuis le zip, 303 tests OK, 5 ignorés faute de services), `detect_node`, `detect_python`, `detect_rust`, `detect_go` et `make_plan` ont été découpés en
petites fonctions (`_node_version`, `_node_package_manager`, `_node_run` ; `_python_manifest`, `_python_install_steps`, `_python_run` ; `_rust_toolchain`, `_rust_run_from_bins`, `_rust_run_from_workspace` ; `_go_version`, `_go_run_from_cmd_dir` ;
`_note_multistack`, `_fill_missing_command`, `_apply_lock_or_registry`). Complexités mesurées (`radon`) : `detect_node` 35 → 5, `detect_python` 35 → 12, `detect_rust` 32 → 8, `detect_go` 22 → 3, `make_plan` 29 → 10 ; la plus complexe des nouvelles fonctions : 16 (`_go_run_from_cmd_dir`) ; plus aucune fonction de rang E ou F ; **moyenne 5,77 (B)**.
**Le filet de sécurité (hors dépôt, dans `/tmp`, à recréer si besoin)** : des instantanés allégés de 298 dépôts de la liste (fichiers texte ≤ 100 Ko des types lus par les détecteurs, sans `.git` ni `node_modules`), le plan complet de chacun sérialisé par le code d'avant
(commit `716647b`, exporté dans `/tmp/ref_src`), puis comparé champ par champ après chaque refactoring. Mesure déterministe (deux exécutions du même code : 0 différence). **Résultat : 0 différence sur 298 plans** (245 plans complets, 53 erreurs attendues ; 52 plans Go et 49 plans Rust exercés).
**Faille du filet trouvée par mutation et réparée** : ma première version excluait les lockfiles des instantanés, donc la mutation `npm ci → npm install` n'était **pas détectée** (0 différence) alors que toutes les branches qui dépendent de la présence d'un lockfile (`pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`, `uv.lock`, `bun.lock`…)
n'étaient jamais exercées. Les lockfiles ont été recréés **vides** (seule leur existence compte ; 1 273 fichiers dans 298 dépôts) ; la même mutation est alors détectée sur 46 dépôts.
**Limites** : la comparaison appelle `make_plan` avec `use_lock=False`, donc `_apply_lock_or_registry` n'est couverte que par les tests unitaires existants ; les instantanés ne contiennent pas les fichiers de plus de 100 Ko ni les types non listés ; ce filet n'est pas dans le dépôt (outil jetable : `snap.py`, `locks.py`, `baseline.py` décrits ci-dessus).
**Reste de rang D** : `dispatch` (25), `node_satisfies` (23), `detect_stacks` (23), `entry_evidence` (22), `script_imports` (21), `run_stacks` (21).

## 0.24.5 : `detect_stacks`, `entry_evidence`, `script_imports` simplifiés (même filet, 0 différence)

Trois fonctions de rang D de plus, découpées : `detect_stacks` (23) → `_runnable`, `_conventional_stack_dirs` ; `entry_evidence` (22) → `_docker_command_lines`, `_readme_code_lines`, `_entry_score` ; `script_imports` (21) → `_imported_modules`. Chacune comparée à l'oracle (commit `716647b`,
298 plans réels) : **0 différence**, avec 7 plans à note multi-stack et 2 cas multi-stack ambigus, 6 plans à point d'entrée choisi par preuve et 18 à choix restants, 8 plans à dépendances déduites réellement exercés. 303 tests OK, `pyflakes` propre.
Complexité moyenne du projet : **5,68 (B)**. **Restent de rang D, non touchées** : `dispatch` (25, CLI), `node_satisfies` (23, plages semver), `run_stacks` (21, lancement `--all`) : l'oracle ne les couvre pas (elles ne sont pas appelées par `make_plan`) ;
les tests existants les couvrent partiellement ; les refactorer demanderait des tests de caractérisation écrits avant (méthode déjà appliquée à `install_deps` et `run_project`).

## 0.24.6 : `node_satisfies` et `dispatch` simplifiés

- **`node_satisfies` (23 → 7)** : la comparaison élémentaire devient `_comparator_ok`. Fonction pure, donc vérifiée par une **comparaison exhaustive ancien/nouveau : 18 126 couples version × plage, 0 différence** (34 % de résultats vrais, donc un échantillon qui discrimine ;
  les 159 plages incluent opérateurs, jokers, `||`, plages invalides, `None`), et `pick_node_major` identique sur les 159 plages.
- **`dispatch` (25 → 10)** : un aiguillage clair vers `_cmd_doctor`, `_cmd_bench`, `_enable_sandbox`, `_cmd_all_stacks`, `_auto_all_stacks`, `_cmd_project`. **11 tests de caractérisation écrits avant** (quelle commande appelle quoi, avec quelles options, ce qu'elle affiche, le basculement automatique en multi-stack et
  ses cas de refus), passés sur l'ancien puis le nouveau code ; **4 mutations détectées** (limite de 3 stacks retirée, sandbox actif pour `plan`, arguments après `--` ajoutés après l'affichage du plan, `--all` accepté avec `--cmd`). Contrôle réel via la CLI : `plan` puis `run` de `node-app` → HTTP 200 sur 3000 (ports libres au départ), aucun processus résiduel.
314 tests OK (5 ignorés dans ce sandbox faute de services), `pyflakes` propre. **Reste de rang D : `run_stacks` seule (21).**

## 0.24.7 : `run_stacks` simplifié ; plus aucune fonction de rang D, E ou F

`run_stacks` (mode `--all`, 21) est découpé en `_install_stacks`, `_shared_services` et `_wire_stacks` (ports, URL du backend, variables de service, migrations). Même méthode : **9 tests de caractérisation écrits avant** (installation par stack dans son runtime, un service
par type pour tout le dépôt, ports et URL annoncés, variables de service sans écraser le `.env` d'une stack ni l'environnement du processus, clés des commandes, migrations, code de sortie, arrêt des services), passés sur l'ancien puis le nouveau code ; deux de mes hypothèses de test étaient fausses
(l'environnement du processus fait partie de l'environnement copié ; sans service il n'y a pas de gestionnaire) : les tests décrivent maintenant le comportement réel. **4 mutations détectées** (un service par stack au lieu d'un par type, `.env` écrasé, services non arrêtés, interruption courte comptée comme succès) ;
la mutation « services non arrêtés » avait d'abord muté le mauvais `finally` (celui de `run_project`) et paraissait survivre : refaite sur le bon bloc, elle est détectée. Contrôle réel : monorepo `src/backend` + `src/frontend` : backend sur 8000, frontend sur 3000 interrogeant le backend, ports et URL annoncés, aucun processus résiduel.
323 tests OK (5 ignorés dans ce sandbox faute de services), `pyflakes` propre. **Bilan de la simplification (0.24.2 à 0.24.7) : aucune fonction de rang D, E ou F ; complexité moyenne 6,4 → 5,53 (B).** Méthode retenue : tests de caractérisation ou comparaison à un oracle écrits **avant**, refactoring ensuite, mutations pour prouver que le filet détecte, contrôle réel enfin.

## Vérification finale de la simplification (sans changement de version)

Après la réinitialisation du sandbox, la suite tournait avec 5 tests ignorés faute de services. Redis, PostgreSQL 16, MariaDB et bubblewrap ont été réinstallés (le dépôt apt nodesource, bloqué en 403, déplacé hors de `sources.list.d`) et la suite complète rejouée sur la 0.24.7 :
**323 tests, 0 ignoré, tous OK**, dont les tests d'intégration réels (MariaDB et PostgreSQL locaux, Redis, confinement bubblewrap, signaux), et aucun processus résiduel. Les refactorings de `install_deps`, `run_project`, `dispatch`, `run_stacks` et des détecteurs sont donc confirmés aussi face aux services réels.
