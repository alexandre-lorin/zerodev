# Mission: validate ZeroDev (zero 0.26.1) on this real machine

You are a rigorous tester. You execute, you measure, you report the truth. **You never invent a result**: if you don't have
launched a command, the step is "untested", not "OK".

## Context

**ZeroDev** (`zero`) is a Python CLI (≥ 3.10, without dependency): `zero <dossier ou URL git>` detects the stack of a repository
(Node, Python, Rust, Go), install the correct runtime and dependencies, derive the launch command, start the services
(Redis/PostgreSQL/MySQL in container or locally) and launches the application. The project is in `zerodev.zip` (Git repository included).

The code was written and tested in a Linux sandbox **without**: macOS, Docker/Podman, GPU, Go, Rust, MySQL from Oracle, open Internet access.
Your job is to check **exactly what the sandbox couldn't check**, on this machine, and tell me what's broken.

Recent functions, never tested anywhere other than Linux without Docker:
1. `--sandbox` under **macOS** via `sandbox-exec` (generated profile, never launched on a Mac); under Linux via bubblewrap.
2. Image **container** `contrib/Dockerfile` + `contrib/zero-container.sh` (never built, no container launched).
3. Actual launches of **Go** and **Rust** (never done).
4. Command deduced from **README**, tiebreaker from **monorepos**, message for unmanaged ecosystems, command `zero report` (these four
   are verified on Linux; here we confirm on this machine).

## Mandatory rules

- **Do not modify any files in the repository** during steps 0 to 9. Fixes only come at step 10, on a branch.
- Do not publish anything (no `twine upload`, no `git push`). Do not send or copy anything off this machine.
- Runs **only** the synthetic repositories created by the project scripts, the examples from the `examples/` folder, and the three repositories
  `demo-real.sh` public files. **No other third party code.** Does not use large corpora (`benchmark/corpus.public*.txt`, `corpus.heldout.txt`) with `--full`.
- Do not install **any system packages** (apt, brew, dnf…) without asking me. If you can't ask, mark the step "untested" and write it
  installation command that would have been necessary.
- Never administer a test by modifying it or ignoring it. A red test reports as is.
- For each step: the **exact** command launched, the exit code, and in case of KO the **30 last lines** of raw output.
- Expected duration: 30 to 60 minutes; put a delay (`timeout`) on anything that can block. On macOS, `timeout` does not exist by default (`gtimeout` via coreutils);
  `demo.sh` uses it: if it's missing, note it (step 4 "untested demo.sh: missing timeout") instead of installing coreutils without asking me.
- Before sharing a text, reread it: hide what is personal (name, paths, tokens). `zero report` already hides home folder
  and username, but it's just a trickle.

## Steps

### 0. Setting up
```
unzip zerodev.zip && cd zerodev
./bin/zero --version            # attendu : zerodev 0.26.1
git status --short              # attendu : vide
python3 --version               # attendu : ≥ 3.10
uname -a ; (sw_vers 2>/dev/null)
```

### 1. Unit testing
```
python3 -m unittest discover -s tests
```
Expected: `OK`, 362 tests, at most 5 ignored (those that need `redis-server`, `postgres`, `mariadb` or `mysqld`). Note the exact number of tests and ignores.

### 2. Automatic validation (the heart of the work)
```
python3 scripts/validate_machine.py --out validate-report.txt
```
Create your own synthetic repositories, run zero on them, probe HTTP, stop everything. It prints a line `OK` / `KO` / `SKIP` per check:

| Verification | What it proves | A knockout means |
|---|---|---|
| `node`, `python-pyproject` | end-to-end installation + launch | runtime download, `uv`, `npm` |
| `go`, `rust` | **first real launch of Go and Rust** | **if KO: first checks manually that the synthetic repository of the script is correct** (these two checks have never worked) |
| `readme-run` | command deduced from README (`python serve_it.py`) | deduction does not trigger |
| `readme-utility-refused` | a tooling script is NOT supported for the application | false positive |
| `monorepo-readme` | `cd web` + `npm start` in the README → only `web` is launched | bad subproject |
| `monorepo-ambiguous` | without a clue, zero refuses and cites `--project` | he guesses wrongly |
| `foreign-hint` | Ruby repository: clear message + manual command | generic message |
| `report` | `zero report` hides home folder | escape from a path |
| `sandbox` | `--sandbox`: announces the backend and responds with HTTP, or clearly refuses | **on macOS: the most uncertain point** |
| `sandbox-blocks-home` | an isolated repository cannot read a file from `~` | **ineffective insulation: critical** |
| `container-wrapper` | zero in a container (SKIP if the image does not exist) | see step 5 |

If a check is KO, rerun it alone to reproduce it: `python3 scripts/validate_machine.py --only <nom> --timeout 300`.
Add `--keep-home` to reuse the cache of your `~/.zero` if the network is slow.

### 3. Machine Status and Report
```
./bin/zero doctor > doctor.txt
./bin/zero report examples/node-app > report.txt     # relis-le avant de le joindre
```
Joins `doctor.txt` and `report.txt`. Note in particular: “usable bubblewrap” (Linux) or “usable sandbox-exec (macOS)” (Mac),
Docker/Podman detected, GPU detected.

### 4. Demos
```
./demo.sh          # 5 exemples, ~2 min, 15 s chacun
./demo-real.sh     # 3 vrais dépôts publics (Node ; Python/Django ; Flask + Redis + PostgreSQL), ~4 min
```
Expected: `demo.sh` without Python error; `demo-real.sh` ends with "3/3 repositories respond in HTTP without manual editing." The third deposit
(`microblog`) needs Redis and PostgreSQL: containers (Docker/Podman) or local binaries; without either it fails with a message
(“FAIL”), note. Joins `log.txt` / `report.json` indicated in the last line.

### 5. Containers — only if `docker` or `podman` is present
a) Container services:
```
timeout -s INT 30 ./bin/zero run --services container examples/fullstack-app      # (macOS : `gtimeout`, ou Ctrl-C à la main)
docker ps -a --filter name=zero-       # (ou podman) attendu : AUCUN conteneur zero-… restant
```
b) **Zero-image-in-a-container (never built)**:
```
docker build -f contrib/Dockerfile -t zerodev:latest .          # (ou podman build)
docker run --rm zerodev:latest --version                         # attendu : zerodev 0.26.1
ZERO_PORTS=3000 timeout -s INT 90 contrib/zero-container.sh examples/node-app &
sleep 45; curl -s localhost:3000                                # attendu : hello from node-demo
python3 scripts/validate_machine.py --only container-wrapper --timeout 300
```
c) **Isolation**: `contrib/zero-container.sh examples/node-app --cmd "ls ~/.ssh ; ls /home"` should not show **anything** from your actual personal file.
If the build fails, it's probably a system package missing from the image: note the exact error (don't fix it yet).

### 6. Local services (without container) — only if `redis-server` and `postgres`/`initdb` are installed
```
timeout -s INT 30 ./bin/zero run --services local examples/fullstack-app          # arrêt après 30 s
pgrep -fa "postgres -D|redis-server"                             # attendu : VIDE après l'arrêt
python3 -m unittest tests.test_zerodev.TestRealMysqlCompose -v   # attendu : OK, pas « skipped » (si mysqld ou mariadbd présent ; note la version)
```

### 7. Sandbox, additional manual checks
```
./bin/zero run --sandbox examples/node-app          # attendu : « mode isolé (<backend>) » puis HTTP 200 sur :3000
./bin/zero run --sandbox examples/python-app
echo SECRET > ~/.zero-codex-test ; ./bin/zero run --sandbox --cmd "cat ~/.zero-codex-test" examples/node-app ; rm ~/.zero-codex-test
```
Expected: `SECRET` content **never** appears. On macOS, if you see “Operation not permitted”, copy the exact line and **the tool concerned**
(nvm, Homebrew, `~/Library`…): the profile is probably too strict.

### 8. An additional real deposit (optional, with my explicit agreement)
Ask me for a deposit of my own. Otherwise, jump. Then: `./bin/zero plan <dépôt>` (command detected), `./bin/zero run <dépôt>`, note the first error and if
an “automatic fix” has been applied.

### 9. Building the package (without publishing)
```
python3 -m venv /tmp/v && /tmp/v/bin/pip install build twine
/tmp/v/bin/python -m build --outdir /tmp/dist .
/tmp/v/bin/twine check /tmp/dist/*                              # attendu : PASSED pour les deux
python3 -m venv /tmp/v2 && /tmp/v2/bin/pip install /tmp/dist/*.whl && /tmp/v2/bin/zero --version    # attendu : zerodev 0.26.1
```

### 10. Corrections (only after finishing steps 0 to 9)
For each **reproducible** knockout for which you understand the cause:
1. `git switch -c codex-fixes` (single branch).
2. First write a test that fails, then the **minimal** correction, then rerun `python3 -m unittest discover -s tests` (everything should stay green).
3. One commit per fix, message: “fix: <symptom> (<step>)”.
4. If the cause comes from your environment (tool missing, filtered network, rights), it is **not** a zero bug: don't touch it, note it.
Useful files: `src/zerodev/sandbox.py` (Linux/macOS isolation), `plan.py` (detection, README, monorepos), `runtimes.py` (Node/Go/Rust/uv download),
`core.py` (orchestration), `services.py` / `localsvc.py` (Redis/PostgreSQL), `doctor.py`, `report.py`, `contrib/` (container), `docs/VALIDATION.md`, `docs/CONTAINER.md`.
Does not change the messages in French or the behavior outside of the corrected symptom.

## Format of the final report (file `RAPPORT_CODEX.md`, one line per step)

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

Attached: `RAPPORT_CODEX.md`, `validate-report.txt`, `doctor.txt`, `report.txt`, and `git log --oneline` / `git diff` of `codex-fixes`.
