# Mission : valider ZeroDev (zero 0.26.1) sur cette vraie machine

Tu es un testeur rigoureux. Tu exécutes, tu mesures, tu rapportes la vérité. **Tu n'inventes jamais un résultat** : si tu n'as pas
lancé une commande, l'étape est « non testé », pas « OK ».

## Contexte

**ZeroDev** (`zero`) est une CLI Python (≥ 3.10, sans dépendance) : `zero <dossier ou URL git>` détecte la stack d'un dépôt
(Node, Python, Rust, Go), installe le bon runtime et les dépendances, déduit la commande de lancement, démarre les services
(Redis/PostgreSQL/MySQL en conteneur ou en local) et lance l'application. Le projet est dans `zerodev.zip` (dépôt Git inclus).

Le code a été écrit et testé dans un bac à sable Linux **sans** : macOS, Docker/Podman, GPU, Go, Rust, MySQL d'Oracle, accès libre à Internet.
Ton travail est de vérifier **exactement ce que le bac à sable n'a pas pu vérifier**, sur cette machine, et de me dire ce qui casse.

Fonctions récentes, jamais éprouvées ailleurs que sur Linux sans Docker :
1. `--sandbox` sous **macOS** via `sandbox-exec` (profil généré, jamais lancé sur un Mac) ; sous Linux via bubblewrap.
2. Image **conteneur** `contrib/Dockerfile` + `contrib/zero-container.sh` (jamais construite, aucun conteneur lancé).
3. Lancements réels de **Go** et **Rust** (jamais faits).
4. Commande déduite du **README**, départage des **monorepos**, message pour écosystèmes non gérés, commande `zero report` (ces quatre-là
   sont vérifiées sur Linux ; ici on confirme sur cette machine).

## Règles impératives

- **Ne modifie aucun fichier du dépôt** pendant les étapes 0 à 9. Les corrections viennent seulement à l'étape 10, sur une branche.
- Ne publie rien (pas de `twine upload`, pas de `git push`). N'envoie ni ne copie hors de cette machine quoi que ce soit.
- Ne lance **que** les dépôts synthétiques créés par les scripts du projet, les exemples du dossier `examples/`, et les trois dépôts
  publics de `demo-real.sh`. **Aucun autre code tiers.** N'utilise pas les gros corpus (`benchmark/corpus.public*.txt`, `corpus.heldout.txt`) avec `--full`.
- N'installe **aucun paquet système** (apt, brew, dnf…) sans me demander. Si tu ne peux pas demander, marque l'étape « non testé » et écris la
  commande d'installation qu'il aurait fallu.
- Ne fais jamais passer un test en le modifiant ou en l'ignorant. Un test rouge se rapporte tel quel.
- Pour chaque étape : la commande **exacte** lancée, le code de sortie, et en cas de KO les **30 dernières lignes** de sortie brutes.
- Durée prévue : 30 à 60 minutes ; mets un délai (`timeout`) sur tout ce qui peut bloquer. Sous macOS, `timeout` n'existe pas par défaut (`gtimeout` via coreutils) ;
  `demo.sh` l'utilise : s'il manque, note-le (étape 4 « demo.sh non testé : timeout absent ») au lieu d'installer coreutils sans me demander.
- Avant de partager un texte, relis-le : masque ce qui est personnel (nom, chemins, jetons). `zero report` masque déjà le dossier personnel
  et le nom d'utilisateur, mais ce n'est qu'un filet.

## Étapes

### 0. Mise en place
```
unzip zerodev.zip && cd zerodev
./bin/zero --version            # attendu : zerodev 0.26.1
git status --short              # attendu : vide
python3 --version               # attendu : ≥ 3.10
uname -a ; (sw_vers 2>/dev/null)
```

### 1. Tests unitaires
```
python3 -m unittest discover -s tests
```
Attendu : `OK`, 362 tests, au plus 5 ignorés (ceux qui ont besoin de `redis-server`, `postgres`, `mariadb` ou `mysqld`). Note le nombre exact de tests et d'ignorés.

### 2. Validation automatique (le cœur du travail)
```
python3 scripts/validate_machine.py --out validate-report.txt
```
Crée ses propres dépôts synthétiques, lance zero dessus, sonde le HTTP, arrête tout. Il imprime une ligne `OK` / `KO` / `SKIP` par vérification :

| Vérification | Ce qu'elle prouve | Un KO veut dire |
|---|---|---|
| `node`, `python-pyproject` | installation + lancement de bout en bout | téléchargement de runtime, `uv`, `npm` |
| `go`, `rust` | **premier vrai lancement Go et Rust** | **si KO : vérifie d'abord à la main que le dépôt synthétique du script est correct** (ces deux vérifications n'ont jamais tourné) |
| `readme-run` | commande déduite du README (`python serve_it.py`) | la déduction ne se déclenche pas |
| `readme-utility-refused` | un script d'outillage n'est PAS pris pour l'application | faux positif |
| `monorepo-readme` | `cd web` + `npm start` dans le README → seul `web` est lancé | mauvais sous-projet |
| `monorepo-ambiguous` | sans indice, zero refuse et cite `--project` | il devine à tort |
| `foreign-hint` | dépôt Ruby : message clair + commande manuelle | message générique |
| `report` | `zero report` masque le dossier personnel | fuite d'un chemin |
| `sandbox` | `--sandbox` : annonce le backend et répond en HTTP, ou refuse clairement | **sur macOS : le point le plus incertain** |
| `sandbox-blocks-home` | un dépôt isolé ne peut pas lire un fichier de `~` | **isolation inefficace : critique** |
| `container-wrapper` | zero dans un conteneur (SKIP si l'image n'existe pas) | voir étape 5 |

Si une vérification est KO, relance-la seule pour la reproduire : `python3 scripts/validate_machine.py --only <nom> --timeout 300`.
Ajoute `--keep-home` pour réutiliser le cache de ton `~/.zero` si le réseau est lent.

### 3. État de la machine et rapport
```
./bin/zero doctor > doctor.txt
./bin/zero report examples/node-app > report.txt     # relis-le avant de le joindre
```
Joins `doctor.txt` et `report.txt`. Note en particulier : « bubblewrap utilisable » (Linux) ou « sandbox-exec (macOS) utilisable » (Mac),
Docker/Podman détecté, GPU détecté.

### 4. Démos
```
./demo.sh          # 5 exemples, ~2 min, 15 s chacun
./demo-real.sh     # 3 vrais dépôts publics (Node ; Python/Django ; Flask + Redis + PostgreSQL), ~4 min
```
Attendu : `demo.sh` sans erreur Python ; `demo-real.sh` se termine par « 3/3 dépôts répondent en HTTP sans édition manuelle ». Le troisième dépôt
(`microblog`) a besoin de Redis et PostgreSQL : conteneurs (Docker/Podman) ou binaires locaux ; sans aucun des deux il échoue avec un message
(« ÉCHEC »), à noter. Joins `log.txt` / `report.json` indiqués à la dernière ligne.

### 5. Conteneurs — seulement si `docker` ou `podman` est présent
a) Services en conteneur :
```
timeout -s INT 30 ./bin/zero run --services container examples/fullstack-app      # (macOS : `gtimeout`, ou Ctrl-C à la main)
docker ps -a --filter name=zero-       # (ou podman) attendu : AUCUN conteneur zero-… restant
```
b) **Image zero-dans-un-conteneur (jamais construite)** :
```
docker build -f contrib/Dockerfile -t zerodev:latest .          # (ou podman build)
docker run --rm zerodev:latest --version                         # attendu : zerodev 0.26.1
ZERO_PORTS=3000 timeout -s INT 90 contrib/zero-container.sh examples/node-app &
sleep 45; curl -s localhost:3000                                # attendu : hello from node-demo
python3 scripts/validate_machine.py --only container-wrapper --timeout 300
```
c) **Isolation** : `contrib/zero-container.sh examples/node-app --cmd "ls ~/.ssh ; ls /home"` ne doit montrer **rien** de ton dossier personnel réel.
Si le build échoue, c'est probablement un paquet système manquant dans l'image : note l'erreur exacte (ne corrige pas encore).

### 6. Services locaux (sans conteneur) — seulement si `redis-server` et `postgres`/`initdb` sont installés
```
timeout -s INT 30 ./bin/zero run --services local examples/fullstack-app          # arrêt après 30 s
pgrep -fa "postgres -D|redis-server"                             # attendu : VIDE après l'arrêt
python3 -m unittest tests.test_zerodev.TestRealMysqlCompose -v   # attendu : OK, pas « skipped » (si mysqld ou mariadbd présent ; note la version)
```

### 7. Sandbox, vérifications manuelles complémentaires
```
./bin/zero run --sandbox examples/node-app          # attendu : « mode isolé (<backend>) » puis HTTP 200 sur :3000
./bin/zero run --sandbox examples/python-app
echo SECRET > ~/.zero-codex-test ; ./bin/zero run --sandbox --cmd "cat ~/.zero-codex-test" examples/node-app ; rm ~/.zero-codex-test
```
Attendu : le contenu `SECRET` n'apparaît **jamais**. Sur macOS, si tu vois « Operation not permitted », copie la ligne exacte et **l'outil concerné**
(nvm, Homebrew, `~/Library`…) : le profil est probablement trop strict.

### 8. Un dépôt réel supplémentaire (facultatif, avec mon accord explicite)
Demande-moi un dépôt à moi. Sinon, saute. Puis : `./bin/zero plan <dépôt>` (commande détectée), `./bin/zero run <dépôt>`, note la première erreur et si
un « correctif automatique » a été appliqué.

### 9. Construction du paquet (sans publier)
```
python3 -m venv /tmp/v && /tmp/v/bin/pip install build twine
/tmp/v/bin/python -m build --outdir /tmp/dist .
/tmp/v/bin/twine check /tmp/dist/*                              # attendu : PASSED pour les deux
python3 -m venv /tmp/v2 && /tmp/v2/bin/pip install /tmp/dist/*.whl && /tmp/v2/bin/zero --version    # attendu : zerodev 0.26.1
```

### 10. Corrections (seulement après avoir fini les étapes 0 à 9)
Pour chaque KO **reproductible** dont tu comprends la cause :
1. `git switch -c codex-fixes` (une seule branche).
2. Écris d'abord un test qui échoue, puis la correction **minimale**, puis relance `python3 -m unittest discover -s tests` (tout doit rester vert).
3. Un commit par correction, message : « fix: <symptôme> (<étape>) ».
4. Si la cause vient de ton environnement (outil absent, réseau filtré, droits), ce n'est **pas** un bug de zero : n'y touche pas, note-le.
Fichiers utiles : `src/zerodev/sandbox.py` (isolation Linux/macOS), `plan.py` (détection, README, monorepos), `runtimes.py` (téléchargement Node/Go/Rust/uv),
`core.py` (orchestration), `services.py` / `localsvc.py` (Redis/PostgreSQL), `doctor.py`, `report.py`, `contrib/` (conteneur), `docs/VALIDATION.md`, `docs/CONTAINER.md`.
Ne change pas les messages en français ni le comportement hors du symptôme corrigé.

## Format du rapport final (fichier `RAPPORT_CODEX.md`, une ligne par étape)

```
machine : <OS, version, architecture, noyau> — zero 0.26.1 — Python <x> — docker/podman : <oui/non>

0. mise en place            : OK / KO
1. tests unitaires          : OK / KO — <n tests, m ignorés>
2. validate_machine         : <x OK, y KO, z SKIP> — KO : <noms>
   node / python / go / rust / readme-run / readme-utility / monorepo-readme / monorepo-ambiguous / foreign-hint /
   report / sandbox / sandbox-blocks-home / container-wrapper : OK / KO / SKIP chacun
3. doctor / report          : joints — backend d'isolation : <bubblewrap | sandbox-exec | aucun>
4. demo.sh / demo-real.sh   : OK / KO — x/3 — lignes « OK/ÉCHEC » collées
5. conteneurs               : services : OK/KO/non testé — build image : OK/KO — lancement : OK/KO — isolation : OK/KO — conteneur resté en vie ? :
6. services locaux / MySQL  : OK / KO / non testé (version)
7. sandbox manuel           : OK / KO — « SECRET » apparu ? oui/non
8. dépôt réel               : <nom, commande détectée vs réelle, première erreur, correctif auto ?> / non testé
9. paquet                   : OK / KO
10. corrections             : <liste des commits de la branche codex-fixes> / aucune

Pour chaque KO : commande exacte, code de sortie, 30 dernières lignes brutes, ta lecture de la cause (zero ? environnement ? script ?).
En dernier : « ce que je n'ai pas pu tester et pourquoi ».
```

Joins : `RAPPORT_CODEX.md`, `validate-report.txt`, `doctor.txt`, `report.txt`, et les `git log --oneline` / `git diff` de `codex-fixes`.
