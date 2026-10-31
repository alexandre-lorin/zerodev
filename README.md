# ZeroDev

> **git clone && zero.**

`zero` analyse un dépôt Git, déduit son environnement (runtime, version, dépendances, services, variables
d'env, GPU), l'installe **dans un bac à sable sous `~/.zero`** (rien n'est installé sur le système), puis
lance le projet.

```bash
git clone https://github.com/org/repo && cd repo
zero
```

Python ≥ 3.10, **aucune dépendance** (stdlib uniquement). Linux et macOS. Langages : Node, Python, Rust, Go.

## Installation

Trois voies, toutes sans dépendance autre que Python ≥ 3.10 :

```bash
./bin/zero --help                 # 1. sans installation, depuis le dossier cloné
./install.sh                      # 2. commande `zero` pour l'utilisateur courant (~/.local/bin/zero ; le dossier doit rester en place)
python3 scripts/build_pyz.py      # 3. un exécutable unique dist/zero.pyz (63 Ko) : copiable ailleurs, ./zero.pyz run <dépôt>
pip install .                     #    ou : paquet pip (la commande `zero` ; la version vient du code)
```

`zero doctor` vérifie l'état de la machine (outils, Docker/Podman, GPU, réseau).

## Commandes

| Commande | Rôle |
|---|---|
| `zero [run] [cible]` | installer + lancer (défaut). Cible : dossier, URL git ou bundle `.zeroshare.tgz` |
| `zero plan` | afficher le plan sans rien exécuter |
| `zero freeze` | écrire `zero.lock.json` (V2) |
| `zero share` | créer un bundle `<nom>.zeroshare.tgz` (V3) |
| `zero down` | arrêter les services démarrés par zero |
| `zero fingerprint` | empreinte du dépôt (clé du registre) |
| `zero bench corpus.txt [--full]` | benchmark sur un corpus de dépôts |
| `zero run --sandbox <dépôt>` | installation et lancement isolés (bubblewrap sous Linux, `sandbox-exec` sous macOS — **non éprouvé sur un vrai Mac**) : `~` masqué, système en lecture seule, écriture limitée au dépôt et à `~/.zero` ; réseau non isolé. Refuse de continuer si aucun des deux n'est utilisable |
| `zero run <dépôt> -- <arguments>` | tout ce qui suit `--` est transmis à la commande lancée (outils en ligne de commande ; npm : `--` inséré) |
| `python3 scripts/validate_machine.py` | **validation automatique sur votre machine** : dépôts synthétiques (Node, Python, Go, Rust, README, monorepos…), lancement réel, sonde HTTP, isolation ; tableau OK/KO/SKIP + rapport sans chemins personnels |
| `zero report [dépôt] [--no-network]` | **un seul bloc à coller dans un retour d'essai** : machine (doctor) + plan du dépôt + derniers correctifs automatiques ; chemins personnels et nom d'utilisateur masqués, ne lance rien |
| `zero doctor [--json] [--no-network]` | état de la machine : outils, Docker/Podman, services locaux, GPU, accès réseau, disque (à joindre à un retour d'essai) |

Options :

| Option | Effet |
|---|---|
| `-p, --project DIR` | monorepo : lancer le sous-projet `DIR` |
| `--all` | multi-stack : lancer ensemble backend + frontend (voir ci-dessous) |
| `--cmd "…"` | impose la commande de lancement (quand `zero` refuse de deviner) |
| `--no-recover` | désactive la récupération V4 |
| `--no-services` | ne démarre pas les services V1 |
| `--services auto\|container\|local` | où démarrer les services (défaut `auto` : conteneur si podman/docker, sinon binaires locaux) |
| `--no-lock` | ignore `zero.lock.json` et le registre |
| `--sandbox` | installation et lancement isolés (bubblewrap sous Linux, sandbox-exec sous macOS), voir la section Sécurité |
| `-- <arguments>` | (après la cible) arguments transmis tels quels à la commande lancée |

**Principe : `zero` préfère refuser que deviner faux.** S'il y a plusieurs points d'entrée plausibles
(plusieurs `cmd/*` en Go, plusieurs binaires Rust, plusieurs sous-projets d'un monorepo), il les liste et
s'arrête au lieu de lancer au hasard : `zero --cmd "go run ./cmd/gh"` ou `zero -p apps/web`.
Deux exceptions, chacune avec ses limites (voir `docs/CHANGELOG.md`) : un point d'entrée est choisi seulement s'il est
**le seul appuyé par une preuve** (`ENTRYPOINT`/`CMD` d'un Dockerfile, commande-cible du README) ; un sous-projet de monorepo est choisi seulement s'il est **le seul visé** par un script `dev`/`start` du `package.json` racine ou par un `cd <dossier>` d'un bloc de code du README **suivi d'une vraie commande de lancement** (pas de test/lint) et sans autre commande de lancement ailleurs dans le README (sans cela, ou à égalité, zero demande `--project`) ; un monorepo de 2 ou 3 stacks
de **langages différents** (`backend/` + `frontend/`, aussi sous `src/`, `app/`, `apps/`) est lancé tout seul comme avec `--all`.
En dernier recours (après le Makefile), zero reprend une commande de lancement d'un bloc de code du README **seulement si elle se vérifie sur le dépôt** (`python app.py` avec `app.py` présent, `uvicorn main:app` avec uvicorn déclaré et `main.py` présent, `streamlit run`, `flask run`, `node server.js`) ; placeholders, pipes, `cd` et scripts d'outillage (`scripts/`, `tests/`, `migrate.py`, `reset-admin.js`…) sont écartés, et le plan signale la déduction.
Le plan dit toujours d'où vient une commande ou une version déduite.

## Variables d'environnement

| Variable | Effet |
|---|---|
| `ZERO_HOME` | dossier de travail de zero (défaut `~/.zero` : runtimes, environnements, services, journaux) |
| `ZERO_REGISTRY` | registre partagé (dossier en lecture/écriture, ou `https://…` en lecture) |
| `contrib/zero-container.sh <dépôt>` | lance zero **dans un conteneur** podman/docker (isolation plus forte que `--sandbox`, notamment sous macOS) — écrit mais **jamais exécuté avec un vrai Docker** : voir `docs/CONTAINER.md` |
| `ZERO_NO_RUNTIME_HINT=1` | n'utilise pas la version déduite du Dockerfile/de la CI (revient au défaut) |
| `ZERO_BENCH_CLEANUP=1` | benchmark `--full` : supprime clone, venv et caches après chaque dépôt et surveille le disque |
| `PORT` | si défini (environnement ou `.env`), zero n'attribue pas de port à cette stack |

## Architecture

```
Repository → Detectors → Dependency/Env Planner → Resolver → Sandbox Runtime → Services → Process Supervisor
              plan.py        core.py (make_plan)   runtimes.py   ~/.zero          services.py   supervisor.py
```

| Module | Contenu |
|---|---|
| `plan.py` | détecteurs Node / Python / Rust / Go, monorepos, Procfile, détection des libs IA |
| `runtimes.py` | Node (tarball officiel, repli npm, shims pnpm/yarn), Python (uv), Rust (rustup), Go (go.dev), tous isolés |
| `services.py` | Postgres, MySQL, Redis, MongoDB, RabbitMQ : détection, conteneurs podman/docker, health checks, `.env` |
| `localsvc.py` | repli sans conteneur : `redis-server`, `postgres` (initdb + base `app`), MySQL/MariaDB, `mongod` ; reprend les identifiants du compose |
| `supervisor.py` / `procs.py` | multi-process (Procfile), logs préfixés, arrêt propre ; sous-reaper Linux qui adopte et arrête les démons |
| `report.py` | `zero report` : bloc de retour d'essai avec masquage du dossier personnel et du nom d'utilisateur |
| `sandbox.py` | `--sandbox` : bubblewrap (Linux) ou sandbox-exec (macOS) autour de l'installation et du lancement |
| `doctor.py` | `zero doctor` : état de la machine |
| `recovery.py` | V4 : diagnostic → correctif → retry, journalisé |
| `freeze.py` / `share.py` | V2 / V3 |
| `registry.py` | registre facultatif |
| `gpu.py` | CUDA / ROCm / Vulkan / Metal, fichiers modèles |
| `bench.py` | benchmark public |

## Ce que fait chaque version

**V0** — détecte langage et version (`.nvmrc`, `.node-version`, `.python-version`, `runtime.txt`,
`rust-toolchain(.toml)`, `.tool-versions`, `engines`, `requires-python`), installe un runtime isolé,
installe les dépendances (npm/pnpm/yarn, uv, cargo), devine la commande principale, lance.

**V1** — services déduits de `docker-compose`, des dépendances et de `.env.example` ; démarrés en conteneurs
(port libre si le port par défaut est pris) ; health check TCP ; URLs injectées (`DATABASE_URL`, `REDIS_URL`…) ;
`.env` créé depuis le template (secrets générés, valeurs à fournir listées) ; `Procfile` (web, worker, release).
Un `.env` existant n'est jamais écrasé, et ses variables ne sont pas surchargées.

**V2 `zero freeze`** — `zero.lock.json` : runtime et version exacte, gestionnaire de paquets, services (image,
port), clés d'env (jamais les valeurs), ports, paquets système cités (Dockerfile, CI, README), besoins GPU,
hash des manifestes. Au run suivant, la version est épinglée et la dérive est signalée.

**V3 `zero share`** — bundle = code (fichiers suivis/non ignorés) + lock + template d'env. Les secrets (`.env`,
`*.pem`, `*.key`, `.npmrc`…) ne sont jamais embarqués. Le destinataire fait `zero projet.zeroshare.tgz`.
Les bundles sont validés à l'extraction (pas de chemin hors destination).

**V4 recovery** — erreur → règles déterministes → correctif → relance (4 tentatives au lancement, 8 tours à
l'installation ; chaque correctif n'est tenté qu'une fois) : module Python/Node manquant (installé dans l'environnement isolé, avec
table d'alias `cv2→opencv-python`…), port occupé (`PORT` libre), et, ajoutés version après version (détail et mesures dans
`docs/CHANGELOG.md`) : repli de la version de Python (3.13/3.9/3.8 selon l'erreur ou les roues disponibles), psycopg2 → binaire,
serveur Python absent (`gunicorn`…), `pip install -e .` facultatif, plafonds de versions pour les anciennes API (Jinja, Werkzeug,
SQLAlchemy, WTForms…), copie d'un modèle de configuration (`local_settings_example.py`), `npm ci` → `npm install`, scripts
d'installation ignorés, pnpm 10+ (`strict-dep-builds`), corepack via le registre npm, version imposée pour setuptools-scm,
migrations Django. Outils/bibliothèques système et variables manquantes : **jamais appliqués automatiquement**, affichés comme
action manuelle. Chaque correctif est affiché et journalisé (`~/.zero/logs/<projet>.jsonl`). Pas d'IA dans la boucle.
Les correctifs de dernier recours peuvent s'écarter du lockfile ou du dépôt : le plan et le journal le disent.

**Go** — `go.mod` (`toolchain`, `go`), `.go-version`, `.tool-versions` ; `go run .` si un `package main` est à la
racine, sinon `go run ./cmd/<nom>` quand le nom correspond au dépôt/module (suffixe `/vN` ignoré) ou qu'il n'y en a
qu'un ; sinon refus explicite. Runtime téléchargé depuis go.dev (repli : Go du système).

**Monorepos** — si la racine n'a pas de commande, `zero` cherche des projets exécutables (profondeur ≤ 2). Un seul
→ il le lance ; plusieurs → il liste et demande `--project`. Il ne descend **pas** dans un sous-dossier quand la
racine est déjà reconnue (bibliothèque Go), quand elle est Ruby/PHP/Java (le `package.json` n'est que du front), ni
quand elle contient des scripts `.py` sans manifeste : zero déduit alors les dépendances des `import` et propose les scripts comme points d'entrée
(le sous-projet reste accessible par `--project`).

**Services sans conteneur** — sans podman/docker (ou avec `--services local`), `zero` démarre les binaires locaux :
`redis-server` (éphémère), `postgres` (cluster initialisé avec `initdb`, utilisateur `zero`, base `app`, données
**conservées** dans `~/.zero/services/<projet>/postgres`), `mongod`, `mariadbd`/`mysqld` (MariaDB ou MySQL ; utilisateur `root`, mot de passe `zero`, base `app`, données
**conservées** dans `~/.zero/services/<projet>/mysql`). Il cherche les binaires dans le PATH puis dans les
emplacements usuels (Debian `/usr/lib/postgresql/*/bin`, Homebrew, Postgres.app, RHEL). Sous root, PostgreSQL est exécuté
via `runuser -u postgres` (il refuse de tourner en root). Arrêt propre à la sortie. **RabbitMQ n'a pas de repli
local** : sans conteneur, `zero` le signale. Testé en réel : Redis, PostgreSQL 16 et **MariaDB** (création, redémarrage avec
conservation des données, arrêt propre). Non testés ici : `mongod` et MySQL d'Oracle (mêmes commandes, variante `--initialize-insecure`).

**Multi-stack (`--all`)** — un dépôt avec au moins deux langages *différents* exécutables (racine, `backend/`,
`frontend/`, `server/`, `client/`, `api/`, `web/`, `app/`, `ui/`, `worker/`) est signalé dans le plan. `zero --all` :
installe chaque stack dans son propre runtime, partage **un seul** jeu de services (un Postgres pour tout le dépôt),
branche le `.env` de chaque stack et lance tout sous un superviseur, avec des logs préfixés par stack :

```
backend | backend ready on :8000
frontend| frontend ready on :3000 (backend : http://localhost:8000)
```

Sans `--all` : si la racine n'a aucune commande et qu'il y a 2 ou 3 stacks de langages différents (aussi sous `src/`, `app/`, `apps/`),
zero lance tout seul comme avec `--all` ; si la racine a déjà une commande, il ne lance qu'un côté et le dit. Une racine du même langage qu'un sous-dossier est ignorée
(c'est un orchestrateur : le workspace JS qui lance `frontend/` ne doit pas démarrer le frontend deux fois).
En mode `--all`, la récupération automatique du lancement n'est pas appliquée (la phase d'installation, si).
Chaque stack reçoit un `PORT` distinct (3000 Node, 8000 Python, 8080 Go/Rust, incrémenté si occupé), sauf si `PORT` est
déjà défini dans l'environnement ou le `.env` de la stack. Les programmes qui ignorent `PORT` gardent leur port par défaut.
Si le dépôt a une stack `backend`/`server`/`api` (avec un `PORT` attribué par zero) et une stack `frontend`/`client`/`web`/`ui`/`app`,
le frontend reçoit l'URL du backend dans `BACKEND_URL`, `API_URL`, `VITE_API_URL`, `VITE_BACKEND_URL`, `NEXT_PUBLIC_API_URL`
et `REACT_APP_API_URL` (sans écraser l'environnement ou le `.env`). C'est une convention : elle n'a d'effet que si le
frontend lit l'une de ces variables et que le backend lit `PORT`. Vérifié uniquement sur `examples/multistack-app`.
Si une stack s'arrête, les autres sont arrêtées.

**Récupération à l'installation** — si une dépendance exige une version de Node plus récente que le `.nvmrc`
(pnpm `ERR_PNPM_UNSUPPORTED_ENGINE`, yarn « incompatible »), `zero` monte de version dans la sandbox et réessaie
une fois, sans toucher au dépôt.

**Registre facultatif** — après un run réussi, l'environnement est enregistré par empreinte dans
`~/.zero/registry`. `ZERO_REGISTRY=/chemin/partagé` (écriture/lecture) ou `https://…` (lecture) pour partager.
Local par défaut, aucun cloud requis.

**GPU / IA** — détection de torch, tensorflow, jax, llama-cpp-python, vllm…, `uv pip --torch-backend=auto`
(CUDA/ROCm/CPU), `CMAKE_ARGS` pour llama.cpp, avertissement sur les modèles à télécharger.

## Sécurité

- Un lock ou une entrée de registre **n'épingle que des versions** : les commandes sont toujours recalculées
  depuis le dépôt, donc un lock malveillant ne peut pas injecter de commande.
- `zero run` exécute les scripts du dépôt (npm install, build.rs, setup.py…) : comme `git clone` + install
  manuel, ne le lancez que sur du code auquel vous faites confiance. L'environnement de `~/.zero` isole les versions
  et dépendances, **pas** les privilèges (ce n'est pas un conteneur de sécurité) : pour limiter les dégâts d'un projet douteux, voir `--sandbox` ci-dessous.

**Mode `--sandbox`** (Linux : bubblewrap ; macOS : `sandbox-exec`, profil généré par `sandbox.seatbelt_profile`, **jamais lancé sur un vrai Mac**) : le dossier personnel est masqué (clés SSH, jetons, profils de navigateur invisibles), le système est
en lecture seule, l'écriture est limitée au dépôt, à `~/.zero` et à un `/tmp` privé, les processus sont isolés (PID/IPC). **Le réseau n'est pas
isolé** (un serveur de développement doit rester joignable ; le code du dépôt peut donc émettre des requêtes) et les fichiers lisibles du système
(`/etc`, `/usr`) restent lisibles. C'est une limitation des dégâts d'un projet douteux, **pas une garantie** contre un code qui exploiterait le noyau.
Sous macOS, le profil refuse l'écriture hors dépôt/`~/.zero`/dossiers temporaires et la lecture du dossier personnel, mais n'offre ni `/tmp` privé ni espace de noms PID/IPC ; `sandbox-exec` est déprécié par Apple. Sans backend utilisable, `--sandbox` refuse de lancer plutôt que de s'exécuter sans protection.

## Benchmark

> **Chiffre à retenir : 57,5 % de dépôts avec une commande détectée (473 sur 823), dont 53,5 % sans aucune heuristique de dernier
> recours** (440 sur 823 ; le reste vient du Makefile, d'une preuve du README/Dockerfile ou des imports déduits, tous de confiance
> plus faible). Mesure du code 0.20 sur 1000 dépôts GitHub sélectionnés par une règle fixe (`benchmark/corpus.public500.txt` +
> `corpus.public500b.txt`, détection seule, 176 gros dépôts écartés ; 823 évalués). Les 71,9 % et 67,6 % plus bas viennent de corpus choisis ou
> réglés à la main et **surestiment d'une quinzaine de points**. En lancement réel, sur quelques dizaines de dépôts jugés « exécutables »,
> environ **un sur quatre** sert effectivement une page HTTP (beaucoup sont des outils en ligne de commande ou des bibliothèques). Détails et limites : `docs/CHANGELOG.md`.

```bash
zero bench benchmark/corpus.public.txt                     # détection seule (rapide, 96 dépôts réels)
zero bench benchmark/corpus.sample.txt --full --timeout 90 # build + lancement réels
GITHUB_TOKEN=… python benchmark/build_corpus.py --per-query 100   # générer un corpus de 500–1000 dépôts
```

Chaque dépôt reçoit un statut : `runnable` (commande trouvée), `no_run_command` (bibliothèque…),
`ambiguous_entrypoint`, `ambiguous_monorepo`, `unsupported`, `clone_failed`.

### Résultats mesurés

**Détection sur 96 dépôts publics réels** (`benchmark/results/public-v3.json`) — *aucun code exécuté* :

| Statut | Dépôts | Sens |
|---|---:|---|
| `runnable` | 69 | une commande de lancement a été trouvée |
| `no_run_command` | 13 | bibliothèques ou collections : **refus correct** |
| `ambiguous_entrypoint` | 4 | plusieurs binaires plausibles : `zero` liste et demande `--cmd` |
| `ambiguous_monorepo` | 4 | plusieurs sous-projets : `zero` liste et demande `--project` |
| `unsupported` | 6 | Java, PHP, Ruby, C, Python sans manifeste… |
| `clone_failed` | 0 | — |

Taux « commande trouvée » : **72 %** (69/96). Par langage détecté :
python 17/19 · node 21/26 · rust 17/22 · go 14/19 · hors périmètre/ambigus 10.

**Lancement réel sur 5 petits dépôts** (`benchmark/results/live-v1.json`, sandbox sans conteneurs mais avec redis et postgresql locaux) :

| Dépôt | Résultat | Détail |
|---|---|---|
| streamlit/streamlit-example | ✅ démarre | sans intervention |
| typicode/json-server | ✅ démarre | sans intervention (après correction du PATH pnpm) |
| nestjs/typescript-starter | ✅ démarre | 1 correctif automatique : port 3000 occupé → relance avec `PORT=8000` |
| sveltejs/realworld | ✅ démarre | 1 correctif automatique : `.nvmrc` dit Node 20, une dépendance exige ≥ 22.12 |
| miguelgrinberg/microblog | ✅ démarre | sans intervention, avec le repli Redis local (gunicorn + worker). **Avant le repli : ❌** (pas de conteneur dans ce sandbox) |

**5/5** démarrent, mais lisez la condition : `redis-server` était installé localement pour ce test (je l'ai installé
moi-même avec apt). Sans conteneur ni Redis local, microblog échoue comme avant. Ce test a **trouvé 3 bugs de `zero`** (pnpm absent du PATH au lancement, repli Node sur un tag
npm inexistant, pas de récupération pendant l'installation) : tous corrigés. 5 dépôts, c'est une démonstration,
pas une statistique.

### Comment lire ces chiffres

- **« runnable » veut dire « une commande a été devinée », pas « ça démarre ».** Seul `--full` mesure le démarrage.
- Le corpus de 96 dépôts a été **choisi à la main** (l'API de recherche n'était pas utilisable sans token). Il
  est volontairement varié (apps, CLI, monorepos, bibliothèques, langages hors périmètre) mais pas aléatoire :
  ne le présentez pas comme un échantillon représentatif de GitHub.
- Un statut `no_run_command` sur une bibliothèque (requests, click, axum) est **correct**, pas un échec.
- Le taux est passé de 86 % à 72 % en deux audits manuels successifs du détecteur : à chaque fois, des
  commandes fausses gonflaient le chiffre. Audit 1 : Ruby/PHP pris pour Node, `go run ./cmd/gen-docs`, un exemple
  au hasard parmi des dizaines, descente dans `ui/`. Audit 2 : le fichier `main` de bibliothèques Node (express,
  fastify, koa) lancé comme un programme, `build.go` de syncthing (`//go:build tools`) pris pour le binaire, un
  `template/base` pris pour le projet, `--bin fd-find` au lieu de `fd`. Baisser le chiffre était la bonne décision.
- **Un audit s'arrête quand on arrête de regarder** : j'ai relu les 74 commandes à la main, pas les ~20 000 d'un
  corpus de 1000 dépôts. Attendez-vous à d'autres faux positifs à plus grande échelle.
- `benchmark/results/public-v3.json` contient le détail par dépôt.

### Corpus hors-échantillon (`benchmark/corpus.heldout.txt`)

39 dépôts **jamais utilisés pour régler les heuristiques** (rapport : `benchmark/results/heldout-v1.json`) :
25 « exécutables » sur 37 clonés (**67,6 %**), contre 71,9 % sur le corpus réglé à la main : l'écart est faible,
mais le lot est petit. Relecture manuelle des 25 commandes (jugement, **sans les avoir lancées**) :

- 16 sont de vrais programmes : 6 binaires Rust, 6 binaires Go, Home Assistant (`hass`), Docusaurus, husky, fastify-cli.
- 9 sont discutables : bibliothèques ou outils qui exigent des arguments, ou scripts `dev` qui ne font que surveiller
  un build (gradio, pelican, mkdocs, fastapi, flask, weasyprint, next.js, vuejs/core, astro).
- 1 faux positif corrigé : `etcd` (Procfile `goreman` visant `bin/etcd`, qui n'existe qu'après compilation) ; un
  Procfile qui référence un exécutable local absent est désormais ignoré.

Taux « commande réellement utile » estimé : environ 16/37 (≈ 43 %), très inférieur au taux brut. Ne citez pas le 72 %
sans cette nuance.

### Vieux projets (§13 de la spécification) — essais réels

`benchmark/results/live-v2-old-repos.json` : 4 dépôts anciens/Heroku lancés pour de vrai dans un sandbox (pas une statistique) :

| Dépôt | Résultat |
|---|---|
| heroku/node-js-getting-started | lancé, sans intervention |
| heroku/python-getting-started | lancé, **HTTP 200 vérifié** (Django, Python 3.14) après 3 correctifs : commentaire dans `.python-version`, IPv6 indisponible, `collectstatic` |
| miguelgrinberg/flasky (2017) | installé et démarré après correctifs automatiques ; s'arrête sur `SERVER_NAME` (configuration à fournir) |
| mdn/express-locallibrary-tutorial | installé ; exige un MongoDB (absent du sandbox) |

Second lot (`benchmark/results/live-v3-batch2.json`, 6 dépôts, Redis/Postgres locaux) : **5 lancés sur 6**.
« Lancé » = processus encore vivant à la fin du délai, sans vérification HTTP (sauf `python-getting-started`, vérifié par curl).
Seul échec : `sahat/hackathon-starter`, qui exige MongoDB (`mongod` indisponible ici). Bug réel trouvé et corrigé :
`runtime.txt` épingle Python `3.8.1`, que `uv` ne propose pas (il ne garde que le dernier correctif de chaque
version mineure) → repli automatique sur `3.8`.

Récupérations automatiques ajoutées (toutes journalisées dans `~/.zero/logs/<projet>.jsonl`, dépôt jamais modifié) :
- **Échelle Python** : `imp`/`distutils`/`six.moves` → Python 3.11 ; `getargspec` → 3.10 ; alias `collections.*` → 3.9. Chaque palier une seule fois ; l'environnement est recréé.
- **psycopg2** sans libpq (`pg_config`) → `psycopg2-binary` dans un requirements temporaire (`-r` développés), puis sans le pin si aucun binaire n'existe pour cette version.
- `pkg_resources` → `setuptools<81`.
- **Version Python introuvable** (`3.8.1`) → même version mineure (`3.8`).
- **IPv6 indisponible** (Docker, certains sandboxes) alors que `gunicorn.conf.py` lie `[::]` → `GUNICORN_CMD_ARGS="--bind 0.0.0.0:<port>"` (prioritaire sur le fichier de config).
- **Django + `STATIC_ROOT`** : `collectstatic --noinput` est ajouté aux étapes d'installation (sinon HTTP 500 « Missing staticfiles manifest entry »).
- **Erreur fatale d'un serveur resté vivant** (gunicorn relance ses workers en boucle) : le superviseur la traite comme un échec pour déclencher la récupération.
- **Signaux** : `SIGINT` et `SIGTERM` arrêtent proprement `zero` et ses enfants, même lancé avec `SIGINT` ignoré (shell non interactif). Cela corrigeait un bug réel : le benchmark `--full` laissait des processus orphelins.
Aucune version « ancienne » n'est devinée sans symptôme : sans erreur, la version par défaut reste la plus récente.

## Démo

`./demo-real.sh` : trois vrais dépôts publics (Node, Python/Django, Flask + Redis + PostgreSQL), lancés puis sondés en HTTP avec un verdict (réseau requis ; voir `docs/VALIDATION.md`). Puis :
`./demo.sh` : cinq dépôts très différents (Node, Python avec dépendance oubliée, Procfile + services, Rust, et le
multi-stack lancé avec `--all`).

## Tests

```bash
python -m unittest discover -s tests -v     # ~185 tests, sans réseau ; des tests d'intégration réels (redis, postgres, mariadb) s'ignorent s'ils sont absents
```

## Limites connues

- Les bibliothèques à console_script et les dépôts Python avec un `package.json` d'outillage (ex. gradio) peuvent être comptés « exécutables » à tort (les CLI de framework connues qui n'affichent que leur aide sont écartées ; une sortie rapide qui affiche un usage donne le message « outil en ligne de commande »).
- **Dépôts multi-stack** : sans `--all`, `zero` lance le premier écosystème runnable (Node > Python > Rust > Go)
  et le signale. Avec `--all`, seuls les dossiers conventionnels (backend, frontend, server, client, api, web, app,
  ui, worker) sont explorés : une stack nommée autrement (`packages/api`, `client/` dans un sous-sous-dossier)
  n'est pas trouvée. Sur le corpus public, la détection propose 3 dépôts multi-stack sur 96 (mealie,
  full-stack-fastapi-template, gogs) ; **le lancement `--all` n'a été vérifié que sur l'exemple fourni**,
  pas sur ces dépôts réels (ils exigent des services et du temps).
- Ports : en `--all`, zero attribue des ports distincts (`PORT`) et donne l'URL du backend au frontend ; une app qui ignore `PORT` peut encore entrer en conflit.
- Python : `requirements/<base|common|main|…>.txt` est reconnu ; pour les dépôts rangés par variante matérielle (`requirements/full/requirements_cpu_only.txt`, `_amd`…), zero choisit d'après le matériel détecté (jamais éprouvé sur un vrai GPU). Sans aucun manifeste, les dépendances sont déduites des `import` (nom PyPI supposé).
- Pas de Java, Ruby, PHP, .NET (détectés comme `unsupported`, sans lancer quoi que ce soit de faux).
- Services : conteneur (podman/docker) ou binaires locaux pour Redis, Postgres, MySQL/MariaDB et MongoDB. RabbitMQ
  exige un conteneur ; sans lui `zero` le signale et continue (le projet échouera probablement à se connecter).
  Les images de conteneur n'ont pas pu être testées ici (pas de podman/docker dans mon sandbox).
- Postgres local : authentification `trust` sur 127.0.0.1 uniquement, pensé pour le développement, jamais pour exposer
  une base.
- Les modèles IA ne sont pas téléchargés.
- Pas de Windows natif.
- Le benchmark `--full` (lancement réel) a été exécuté sur plus d'une centaine de dépôts, en petits échantillons dans un sandbox, pas sur
  des centaines d'un coup : il lance du code tiers arbitraire et demande une machine dédiée (et de la place disque : `ZERO_BENCH_CLEANUP=1`).

## Documentation

- `docs/05-zerodev.md` : spécification d'origine.
- `docs/CHANGELOG.md` : journal des versions et des mesures (0.10.2 → aujourd'hui), avec leurs réserves.
- `benchmark/README.md` : corpus, fichiers de résultats et comment les lire (réserves comprises).
- `docs/VALIDATION.md` : checklist à dérouler sur une vraie machine (Docker/Podman, macOS, démos, MySQL d'Oracle).
