# Version log and metrics

Moved from README (sections added version after version, from 0.10.2 to today). The instructions for use are in `README.md`;
the figures to remember are recalled in the “Benchmark” section of the README.

## Automatic validation on a real machine (without version change)

- `scripts/validate_machine.py`: 13 portable checks (Linux/macOS) on synthetic repositories that it creates itself — Node, Python (pyproject), **Go**, **Rust**,
  command deduced from README, tooling script refused, monorepo decided by README, ambiguous monorepo refused, Ruby message, `zero report` without path leak,
  `--sandbox` (backend announced, or clear refusal), isolation of home folder, container (SKIP without image). Actual launch + HTTP probe + process group shutdown.
- Checked here: 9 OK + 2 SKIP (no isolation backend, no Docker); `go` and `rust` KO here (neither Go nor Rust, downloads blocked) — **these two checks have
  never shot with a real toolchain**. **Negative check**: by deliberately breaking the code in a copy, the script reported KO on the README deduction, the message
  Ruby and the path leak (this last check initially failed: the script imposed a temporary `ZERO_HOME` which hid the leak; fixed).
- `docs/CODEX_PROMPT.md`: complete message to give to an agent (Codex) to execute all validation on the user's machine and report OK/KO.

## Clear message for unmanaged ecosystems (0.26.1)

A Ruby, PHP, Java/Kotlin, Elixir, C/C++ or .NET repository received "no Node, Python, Rust or Go projects detected", with no name of its language. He now receives
“unsupported ecosystem: Ruby (Gemfile) — zero supports Node, Python, Rust and Go. By hand: bundle install, then often `bin/rails server`…; see the README »
(`FOREIGN_HINTS` in `plan.py`: general indication by ecosystem, not a guarantee for this deposit). Same addition when a `package.json` is only the tooling
front of a foreign project. A folder without any manifest keeps the generic message. +4 tests (362 in total). No language is added: see measure below.

## Measurement: which languages ​​are missing? (docs only)

On the 45 repositories classified `unsupported` in 0.20, 40 were cloneable: **30 have nothing executable** (“awesome” lists, skills, documentation,
data) — “unsupported” is the correct answer; **10** have a foreign ecosystem: **Ruby 4** (Gemfile), **Java/Kotlin 3** (pom.xml, build.gradle*),
**PHP 2** (composer.json), **C/C++ 1**. Reported to the 824 corpus repositories, each added language would cover **at best 0,5 %** (Ruby); Java/Kotlin 0,4%,
PHP 0,2%. Adding one of them requires plugging language into `runtimes.py`, `core.py`, `doctor.py` and detection, without being able to test a single launch
real here (neither Ruby, nor PHP, nor Maven/Gradle, download sites blocked). **Decision: do not add it without explicit request from the user and without
validation on his machine**; the measured gain does not justify untested code.

## `zero report` (0.26.0)

- New command: `zero report [dépôt]` prints **a single block to paste in a test return**: version and platform, `doctor`, depot plan
  (or the error, without crashing), 5 latest automatic fixes, and a “what happened” line to complete. Don't throw anything. The personal file
  becomes `~`, username `<user>` (ignored if it is less than 3 letters, `root` or `user`), color codes are removed. Environmental values
  never appear there (the map only displays the names of the keys). Rationale: to reduce the return effort that everything else requires to one order.
  Checked: Actual execution on a test repository (no `/root` in output), +4 tests (358 in total). Masking is a net, not a guarantee:
  re-read the block before sharing it.

## Isolation per container: zero in a container (contrib, without version change)

- No container backend in `--sandbox`: zero downloads runtimes for the host platform and writes their paths to commands;
  they would not run in a Linux container from a Mac. Instead: `contrib/Dockerfile` + `contrib/zero-container.sh` run **zero
  itself** in the container (`--cap-drop ALL`, `no-new-privileges`, process/memory limits, repository mounted in `/work`, volume `zerodev-home`).
- **Checked**: script syntax (`sh -n`), construction of the command with a false `docker` (3 tests, 354 in total), refusal of a non-numeric port,
  message without podman/docker, accepts `zero <dépôt> --options`. **Unverified**: Building the image and any actual launch (no Docker here).
  Limits and checklist in `docs/CONTAINER.md`.

## Reading the README: two defects corrected (0.25.2)

Hand-tested edge cases (Windows line endings, paths with spaces/accents, `../` and absolute paths, README of 500 000 lines): OK, except
two real faults, fixed with one test each (+4 tests, 351 in total):
- code blocks **indented by 4 spaces** (README without ``` closings) were never read: lines were joined character by character;
- fences **`~~~`** were not recognized.
The same reading of README is also used to decide between entry points and monorepos: they benefit from it. Known limit: beyond 2000 lines
of code in the README, the rest is ignored (voluntary).

## Measuring ambiguous inputs (docs only)

70 of 77 deposits classified `ambiguous_entrypoint` in 0.20 were clonable; with code 0.25.1, **68 remains ambiguous, 2 resolves**. The 68 are
real multi-binary projects (44 Rust, 20 Go, 4 Python): `cmd/client` + `cmd/server`, `cargo run -p cli` + `-p daemon`, `download.py` +
`fetch.py`… No proof designates “the” program to launch (no `default-run`, no Dockerfile or README which decides). Guess (by
example always `server`) would often be wrong: asking remains the right behavior, and the plan lists the choices. No code changes.

## Correction after measurement on real deposits (0.25.1)

Measure: the **99 clonable repositories** (< 150 MB) among the 228 that the 0.20 measure classified `ambiguous_monorepo` or `no_run_command`, version 0.24.7
against 0.25.0. Result: **6 changes, including questionable or false 4** — `python test-suite/run_manifest.py` (test runner),
`node scripts/reset-admin.js` (administration utility), and two poorly separated monorepos: `mycelium` (the `cd fastapi-backend` in the README leads to
`pytest`/`ruff`) and `hoop` (the real launch is `make run-dev` at the root; zero had chosen the web interface only).
Corrections, each with a test taken from the real case (+5 tests, 347 in total):
- README of a monorepo: the `cd <dossier>` must be followed, in the same block, by a **launch command** (`npm run dev`, `make run`,
  `uvicorn`, `cargo run`…) and not test/lint/build/installation; each block starts again at the root; **any other README launch command**
  (root or non-candidate folder) makes the proof ambiguous → we ask again `--project`.
- README only: tooling scripts are excluded (folders `scripts/`, `tests/`, `tools/`, `examples/`…; names containing reset, migrate, seed,
  setup, build, admin, manifest…).
- After correction: **2 changes on 99** — `abrignoni/iLEAPP` (`python ileappGUI.py`, graphical interface: plausible launch, not verified) and
  `quiltdata/quilt` (`catalog/`, according to “Run catalog locally”: `cd catalog`, `npm start`). **Actual gain: approximately 2 % of these failure categories,
  and no measurement of whether these commands start.** This is modest; the categories are mainly libraries without commands to launch.
- Lesson: the first version of 0.25.0 passed its tests and a check on 30 repositories without difference, but the tests were written from
  imagined cases; only the measurement targeted at the deposits actually concerned showed the errors.

## PyPI release control (docs only, no version changes)

- `python -m build`: sdist + wheel OK; `twine check`: PASSED; wheel installed in a blank venv: `zero --version` and `zero plan` OK.
  Names `zerodev`, `zero-dev`, `zerodev-cli` free on PyPI on 27/10/2026. Procedure and reservations in `docs/PUBLISHING.md`. **Nothing published.**

## README, monorepos, macOS (0.25.0)

- **Command deduced from the README**: as a last resort (after the Makefile), the first command to launch a README code block which is
  checks on the repository: `python x.py` / `python -m mod` (file or package present), `uvicorn|gunicorn|hypercorn mod:app` (tool declared +
  module present), `streamlit run f.py`, `flask run` (flask declared + `app.py`/`wsgi.py`), `node f.js`. Discarded: placeholders (`<…>`, `your`,
  `path/to`), pipes, `&&`, variables, `setup.py`, `test*.py`, `manage.py`, `pip`/`venv`/`pytest`/`http.server`. The plan language must match.
  A simple mention in prose does not count. The plan reports the deduction (“nothing else confirms it”). Verified: synthetic deposit with
  only a README → HTTP 200.
- **Splitting of monorepos**: among several executable subprojects, only one is retained if it is **the only one targeted** by a script `dev`/`start`/
  `serve`/`develop`/`run` of root `package.json` (`cd api && …`, `--prefix`, `--filter`, `-w`, `./api/…`) = proof 3, or by a `cd <dossier>`
  (including `cd ../dossier`) of a code block from the README = proof 2. Equality (README with `cd api` AND `cd web`) → we ask for `--project` again.
  Never applied to a multi-stack monorepo (different languages), which keeps `--all` launching automatically. Verified: synthetic monorepo
  api/web + README “cd web” → web launched, note in the plan.
- **`--sandbox` under macOS**: `sandbox-exec` with a generated SBPL profile (`sandbox.seatbelt_profile`): write refused unless deposited, `~/.zero`,
  `/private/tmp`, `/private/var/folders` ; reading of the personal file refused unless deposited and `~/.zero`; caches (uv, npm, pip, yarn, pnpm)
  redirected to `~/.zero/cache`. `zero doctor` indicates the backend. **Not tested on a real Mac**: only profile generation and
  backend selection are tested (under Linux). Known limitations: no private `/tmp` or PID/IPC namespace; tools installed under
  `~` (nvm, `~/.cargo`) unreadable; `sandbox-exec` is deprecated by Apple. Checklist added to `docs/VALIDATION.md` (§5 bis).
- Tests: 323 → 342.

## HTTP verification of the benchmark (0.10.2)

`zero bench --full` is no longer satisfied with “living process”: at the end of the period it
lists the TCP ports listening to the process tree (reading `/proc`, Linux) and
probe each in HTTP. The report contains `listening_ports`, `http` and `http_ok`
(a code 404/500 counts: the server speaks HTTP). A portless worker is not
counted. First try: node-js-getting-started → 200; express-locallibrary →
not launched (MongoDB absent).

### Batch 3 of old repositories (with HTTP probe)

8 repositories, 8 cloned: 5 executables, 4 built, 1 launched, 0 HTTP response (sandbox without
Redis/PostgreSQL). Replayed with local services installed: **microblog → HTTP 200**.
Remaining failures, all excluding automatic fix for now:
- `pallets/flask`: the detected command (`flask` without argument) displays help and exits with code 2 (library repository).
- `full-stack-fastapi-template`: `dev` script calls `bun`, unmanaged runtime.
- `sahat/megaboilerplate`: `npm install` fails (very old dependencies, recent Node).
- `django/djangoproject.com`: Launched, but `make scss` fails and no HTTP ports are listening.
- `heroku/ruby-getting-started`: Ruby not supported; `expressjs/express`, `gin-gonic/examples`: No launch command.

## Bare Bun and CLI (0.10.3)

- **bun**: detected via `bun.lock` / `bun.lockb`, `packageManager: bun`, or a `package.json` script that calls `bun run|x|install`. Install `bun install`, launch `bun run dev|start`. The binary comes from the npm fallback of `ensure_pm`. Checked: `full-stack-fastapi-template` → HTTP frontend 200 (port 5173).
- **CLI without arguments**: a console script which only displays its help (`flask`, `django-admin`, `celery`, `uvicorn`, `pytest`…) is no longer taken for a launch command (list `NEEDS_ARGS_CLIS` into `plan.py`). `pallets/flask` therefore changes from “false command, code 2” to “no main command found”.
- Limit: on the FastAPI template, only the frontend is launched; the backend (Docker Compose) is not. The CLI list is handmade.

## npm compatible with old Node (0.10.4)

When `nodejs.org` is inaccessible, zero falls back to the npm package `node`, which does not provide
than the binary: it is then the recent `npm` of the system which was running under an old Node
(`Cannot find module 'node:path'`). zero now installs a compatible npm alongside
(Node ≤ 6 → npm 3, < 12 → npm 6, < 18 → npm 8, otherwise nothing) and creates the links `npm`/`npx`.
Checked on `sahat/megaboilerplate` (Node 6.1.0): the correct npm is selected (3.10.10).
Not verified end-to-end: In the test sandbox, Node 6 rejects the certificate of
proxy (`SELF_SIGNED_CERT_IN_CHAIN`), so the packages could not be installed successfully.
This path is only used without access to nodejs.org; with access, the npm provided with Node is used.

## libpq variables for PostgreSQL (0.10.5)

In addition to `DATABASE_URL`, zero exposes `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` and
`PGDATABASE` for the PostgreSQL service (never over the environment or `.env`
existing). Apps that leave the host empty (Django, `psql`) thus join the database
zero instead of looking for a Unix socket. Observed on `django/djangoproject.com`: the error
“socket not found” disappears.
Known limit: this repository hard-fixes the role `djangoproject` (and reads its secrets in a
file), which zero does not create (`role "djangoproject" does not exist`). Track: resume
`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` of the `docker-compose.yml` of the repository.

## PostgreSQL credentials for docker-compose (0.10.6)

If the `docker-compose.yml` of the repository declares `POSTGRES_USER`, `POSTGRES_PASSWORD` or
`POSTGRES_DB` in literal (`- VAR=x` or `VAR: x`, or `${VAR:-défaut}`), zero uses them
for container **and** for `DATABASE_URL` / `PGUSER` / `PGPASSWORD` / `PGDATABASE`. With the
Local PostgreSQL (without container), it creates this role (superuser) and this database. The
non-literal values (`${SECRET}`) are ignored and default to zero
(`zero` / `zero` / `app`) remain for the rest. PostgreSQL only for now.
Observed on `django/djangoproject.com`: the Django server is starting (the error
`role "djangoproject" does not exist` disappears). Unverified: an HTTP request; the deposit
93 reports unapplied migrations, which zero does not execute.

## Automatic Django migrations (0.10.7)

Before launching, zero executes `manage.py migrate --noinput` when: the project is Django,
**zero itself manages a database** (PostgreSQL or MySQL, container or local) and no command from
repository (including Procfile) already contains `migrate`. SQLite and external databases are never
affected. A migration failure warns without interrupting the launch. The `--all` mode applies the
same rule stack by stack (0.10.9).
Observed on `django/djangoproject.com`: 93 migrations apply and warning
“unapplied migrations” disappears; the server responds in HTTP (code 400 on `127.0.0.1`,
probably a `ALLOWED_HOSTS` from the deposit, not investigated).

## MySQL/MariaDB identifiers of docker-compose (0.10.8)

Same principle as for PostgreSQL: `MYSQL_USER`, `MYSQL_PASSWORD` and `MYSQL_DATABASE`
`docker-compose.yml` literals feed `DATABASE_URL` and the container. With the server
local (MariaDB or MySQL), zero creates the database and the application account (all rights, for
`localhost`, `127.0.0.1`, `::1` and `%`), idempotently. **root** password remains
that of zero (`zero`): a `MYSQL_ROOT_PASSWORD` from the repository is not included. Verified in real
with MariaDB (connection with the repository account, two starts in a row). Not tested:
Oracle's MySQL; `MYSQL_USER=root` (refused by the official image) is not processed separately.

### Migrations in `--all` mode (0.10.9)

Every Django stack that depends on a zero-managed database is migrated before launch
common. Checked on a mini repository (Django backend + local PostgreSQL, Node frontend):
migrations applied, backend on 8000, frontend on 3000.

## Validation on real machine

The checklist of what development could not verify (Docker/Podman, macOS, MySQL
Oracle, full demos) is in `docs/VALIDATION.md`.

## Bundle 4 and psycopg2 fixes (0.10.10)

Eight public repositories (Go, Flask, Node, Django), active HTTP probe. Before fixes:
`sample-nodejs`, `render flask-hello-world`, `render express-hello-world` → **HTTP 200**
(3/3 launched). Failures and consequences:
- `gothinkster/flask-realworld-example-app`: `psycopg2` does not compile (header `pg_config.h`
  absent while `pg_config` exists). The diagnosis did not see it: **`run_tee` did not keep
  than the last 200 lines** and the error was higher. It now also keeps the 150
  raw, and the detection covers `pg_config.h` / `libpq-fe.h` / `postgres_ext.h`. Result:
  substitution with `psycopg2-binary`, gunicorn listens on 8000.
- `digitalocean/sample-django`: `psycopg2-binary==2.9.3` does not have a wheel for Python 3.12.
  If the file is already in `-binary`, zero goes directly to removing the pin. Result: the
  Django server starts (without HTTP request checked).
- `miguelgrinberg/flask-video-streaming`: unsatisfyable requirements in the repository
  (`flask==2.0.2` requires `jinja2>=3`, pin file `jinja2==2.11.3`). Not corrected.
- `gothinkster/golang-gin-realworld-example-app`: GB not found, `go.dev` stuck in sandbox
  test (not evaluable here). `docker/getting-started`: No launch command.

## Bundle 5 and two fixes (0.10.11)

Eight Python/Node repositories. Before fixes: `digitalocean/sample-flask` (8080),
`sample-expressjs` (3000) and `render nextjs-hello-world` (3000) → **HTTP 200**; two deposits
Render (`fastapi-hello-world`, `django-hello-world`) failed cloning (not found);
`Flask-SocketIO-Chat`: No launch command. Two fixes:
- **Python server missing from requirements** (`flask-boilerplate`: Procfile `gunicorn …`, but
  gunicorn is not in `requirements.txt`, Heroku installs it itself): recovery
  installs `gunicorn`, `uvicorn`, `hypercorn`, `daphne`, `waitress`, `granian` or `flask` in the
  venv when the command responds “not found”. The deposit is not modified.
- **`pip install -e .` which fails on an application repository** (`microblog-api`: pyproject
  tooling, hatchling does not find a package): if a step `-r requirements` has already succeeded,
  This step is skipped and the app is launched from its sources. Result: gunicorn is listening on 8000.
Remains unfixed: `flask-boilerplate` starts but fails to load
(`ImportError: TextField`: The code uses an API removed from WTForms 3).

## Pipenv (0.11.0)

A repository with `Pipfile` but without `requirements.txt` is now detected (it was not):
- packages: `Pipfile.lock` (exact versions, without git entries/local path) otherwise `Pipfile`;
  `*` becomes “latest version”, the extras are kept;
- Python version: `[requires] python_full_version` / `python_version`;
- installation: a `uv pip install` with the packages as arguments (no file written);
- a `requirements.txt` present remains a priority; Pipfile also counts for monorepos.
Checked on a Flask Pipenv mini app: Python 3.12, “pipenv ok” page on port 5000.
Limitations: only the `[packages]` section is installed (not `[dev-packages]`); the fixes
psycopg2 per file do not yet apply to this mode; real test on a single synthetic deposit.

## Lot 6: Pipenv / real poetry (0.11.1)

Four deposits. `postmanlabs/httpbin` (Pipfile + `setup.py`, Python 3.6 requested) revealed two
holes, corrected:
- **Python too old for uv**: `uv` no longer provides 3.6/3.7. Automatic fallback now works
  to 3.8 (the oldest available) for any version < 3.8, in addition to the fallback “3.8.1 → 3.8”.
- **Pinned versions of `Pipfile.lock` unusable** (flask 1.0.2, gevent 1.3.4… do not install
  not on Python 3.8): if the repository also has a `setup.py`/`pyproject.toml`, the “lock” step is
  ignored and the project dependencies are sufficient (`Plan.soft_steps`).
Result: httpbin **installs** but does not start: `ImportError: BaseResponse` (API removed from
Werkzeug ≥ 2.1, untreated: this would be a table of version ceilings to be maintained).
Other repositories: `responder` launches a CLI which only displays its help (list `NEEDS_ARGS_CLIS`,
not extended on a case-by-case basis); `fastapi-realworld-example-app` (poetry) and `python-socketio`: none
Launch command found.

## Remeasurement of detection after 0.10.2 → 0.11.1

Same corpora, detection only (`benchmark/results/public-v4.json`, `heldout-v2.json`):
- hand-tuned corpus: 69/96 (71,9 %) → **68/96 (70,8 %)**;
- out of sample: 25/37 (67,6 %) → **24/37 (64,9 %)** of cloned repositories.
Only one repository changes, in both: `pallets/flask`, which counted as "executable" because of the
bare `flask` command (it only displays its help; discarded since 0.10.3). This decline of 1 is
wanted: the measurement is more honest, no other regression. The cloned repositories are those of today,
not those of the original measurement. A first pass showed 32 “clone_failed”: disk of
full sandbox, not a zero default; replayed after cleaning.

## Demo §16 and specification (0.11.2)

- The original specification is retained in `docs/05-zerodev.md`.
- `demo-real.sh` creates §16: three very different public repositories (`node-js-getting-started`,
  `python-getting-started`, `microblog`), launched then **probed in HTTP automatically**; the script
  displays one verdict per deposit and exits as 0 only if all three respond. Corpus:
  `benchmark/corpus.demo.txt`. Executed here end-to-end: 3/3 in HTTP 200 (Redis and PostgreSQL
  premises, without container).
- Limit of §16: none of the three are *abandoned* projects. Old projects tried fail:
  `heroku/python-sample` (Flask 0.9, `wsgiref` reserved for Python 2, not installable in Python 3),
  `heroku/node-js-sample` (Node 4.0.0 not found in sandbox npm fallback, `nodejs.org` blocked;
  not assessable here). `flasky` (2017) starts but asks for `SERVER_NAME`.
- Known false positive: a script that launches its web server with `--daemon` (`flask-by-example`:
  `heroku.sh`) detaches from zero; zero doesn't see it or stop it, and the report says "started"
  while only one worker is rotating.

## 0.12.0: daemons, Makefile, corpus of 500 repositories

**Corpus of 500 repositories (specification §15)**: `benchmark/corpus.public500.txt`, constituted by a
fixed rule and not by hand (GitHub API, `language:<L> stars:500..3000 archived:false`, sort by date
update, 100 by language python/javascript/typescript/go/rust, duplicates of other corpora removed).
98 repositories whose API size exceeds 300 MB are discarded (a single clone weighs up to 1,8 GB): **402
evaluated**, detection only (`benchmark/results/public500-v1.json`):

| | deposits | executables | rate |
|---|---|---|---|
| Nodes | 127 | 98 | 77 % |
| Go | 80 | 49 | 61 % |
| Python | 62 | 32 | 52 % |
| Rust | 73 | 35 | 48 % |
| others / without language | 60 | 0 | — |
| **Total** | **402** | **214** | **53,2 %** (51,5 % outside Makefile) |

The two hand-tuned corpora gave 71% and 65-68%: they **overestimated by around fifteen
dots** ; 53 % is the number to remember. Many of these repositories are libraries (nothing to launch),
therefore this rate is not a “failure rate” of zero. Detection alone: we do not know how much
would start. Bias: recently active repositories, average popularity, no giants. Still far from 1000.

**Corrected thanks to this corpus**: a `Cargo.toml` with `members = ["."]` (invalid glob pattern) was
plant zero ; `safe_glob` covers these grounds. The benchmark no longer stops on an exception of one
detector (status `detector_error`, 0 on this corpus). The detection-only benchmark processes deposits in
flow and **deletes each clone** after classification (the sandbox disk had filled up: 261 false
“clone_failed”).

**Makefile fallback (§2)**: without any other command, a target `run`/`dev`/`start`/`serve`/`server` no
empty Makefile becomes the command (`make run`), noted “deduced from the Makefile”. Effect: 7 deposits on 402,
most of which are dubious (`make run` from Kubernetes operators like kubeai or stackrox). They are counted at
part (`inferred_from_makefile`, `detection_rate_strict_of_cloned`).

**Daemons**: zero declares itself a “sub-reaper” of the kernel (Linux): a server launched with `--daemon` or by
double fork is adopted by zero, visible to the HTTP probe, and stopped with the rest (SIGTERM then SIGKILL).
Verified by unit test (a detached `sleep` is passed and then stopped). **Not proven on a real deposit**:
`gunicorn --daemon`'s `flask-by-example` fails on its side (no ports), so the actual case remains to be seen.

## 0.12.1: real launch of a sample of the corpus 500

Random draw (seed 42) from the “executable” repositories of `public500-v1.json`, Node and Python
only (Go/Rust toolchains inaccessible here). Expected: 30. **Evaluated: 22** (15 Node, 7 Python): the disk
of the sandbox became saturated (`node_modules`, heavy Python wheels) and interrupted the experiment
(`benchmark/results/live-v10-sample500.json`, 4 disc-killed clones ruled out).

| 22 “executable” repositories | built | launched (living process) | **respond using HTTP** |
|---|---|---|---|
| Node (15) | 10 | 6 | 4 (200) |
| Python (7) | 5 | 3 | 1 (503) |
| **Total** | **15 (68 %)** | **9 (41 %)** | **5 (23 %)** |

Read with caution: 22 deposits, interrupted sample, rather the lightest. “Reply using HTTP” is a
bad criteria for a CLI or a worker (several “launched” without HTTP are online tools for
command). In short: **of these 22 deposits that zero declares to be launchable, approximately one in four is actually used
a page**, and the 53 % detection of the corpus 500 says nothing about this rate. Common failures: installing
dependencies (`npm ci`, wheels), Node versions/tools too recent, external services.

Benchmark: `--full` mode is now sequential and in flow (clone → launch → cleanup), with
`ZERO_BENCH_CLEANUP=1` to remove clone, venv, and fallback Node runtimes after each repository; the report
is saved (atomic write) after each deposit, so an interruption no longer loses anything.

## 0.12.2: Actual sample failure causes

Reading 13 sample failures from 22 repositories (0.12.1), by cause:
- **Command line tools taken for servers** (citgm, dario, NUR, datacontract-cli, bub…): they
  show their help then leave. The benchmark now classifies them separately (`cli_tool`, `cli_tools`) instead of
  to count them as failures or servers. Unresolved on the detection side: zero always launches the command.
- **Slow installations cut by the delay** (probo, takt, ScienceClaw, saleor-dashboard): these were not
  failures. Each row now has `phase` (`install_failed`, `install_timeout`, `run`) and the summary counts
  `install_timeout`. To be redone with a longer delay (or `--timeout 180`).
- **No wheel for Python 3.14** (`pose2sim`: `opensim` publishes cp311 to cp313 only): zero reads the list of
  ABI in the UV message, and falls back to the most recent Python covered (here 3.13), even when `plan.version`
  is just a constraint (`>=3.11`). Verified: fallback triggers on `pose2sim`; the complete installation does not
  could be completed (the sandbox disk was filled with the wheels of `opensim`), therefore not confirmed from start to finish.
- **Unprocessed**: build failing (`kaos-tools`), `npm ci` failing (`ing-bank/lion`), dependencies
  ESM/Node at runtime (`brightdata-mcp`, `DefiLlama-Adapters`), external services (`wildduck`).

## 0.12.3: fallback of `npm ci`

If `npm ci` fails, zero chooses a replacement based on the error (each only once, logged):
lockfile out of sync from `package.json` (“can only install packages when… in sync”, “Missing… from lock
file") → `npm install` ; peer conflict (`ERESOLVE`) → `npm install --legacy-peer-deps`. Other errors
(network, etc.) do not trigger anything. Checked on a mini project with a intentionally desynchronized lockfile: fallback,
installation, startup. **Not checked on `ing-bank/lion`**, the sample deposit was failing on `npm ci`
(very large, sandbox disk): its exact cause has not been preserved, it is therefore not proven that it relates to
this case. `npm install` can write `package-lock.json` to the cloned repository.

## 0.12.4: second sample, disk guardrail, `--ignore-scripts`

**Correction of a previous observation**: the lack of sandbox disk mainly came from the **global store of
pnpm (4,1 Go)** and the bun cache (~1 Go), which the benchmark fed without ever emptying them, and not from a limit
incompressible (`node_modules` and wheels alone do not explain it). After cleaning: 5,8 Free GB. Cleaning
automatic (`ZERO_BENCH_CLEANUP=1`) now flushes these caches and the benchmark stops cleanly, with partial reporting
(`stopped_disk_low`, `not_run`), if space remains under 900 MB. Sample results from the 0.12.1 (22 repositories)
may have been distorted by this lack of space: read with reservation.

**Second sample** (seed 7, 8 Node + 8 Python, deposits different from the first, delay 90 s, without disk incident;
`benchmark/results/live-v11-sample2.json`): 16 repositories, **10 built, 6 launched, 2 respond via HTTP (404: a
development server without root page), 5 command line tools, 1 installation still in progress at
deadline**. In other words: very few real web servers in this draw, a lot of CLI tools/agents.

**Fallback `--ignore-scripts`**: if a lifecycle script (`postinstall`…) causes `npm ci|install` to fail,
`pnpm install` or `yarn`, zero reruns the same command with `--ignore-scripts` (once, logged, last
recourse: the native modules to be compiled will then not work). Checked on `Orkas-AI/Orkas`, one of which
postinstall downloads an embedding template: the installation passes and the app launches. Not verified on
`juspay/xyne-spaces` (huge pnpm monorepo: it filled the disk during the test).

Remaining failures from second draw: `uv sync --frozen` which fails to build (`cutile-python`, `avibe`),
`sglang-omni` (PyTorch, `--torch-backend=auto`), `xyne-spaces`; not analyzed (too heavy or causes not noted).

## 0.12.5: version calculated from git (setuptools-scm, hatch-vcs)

A project whose version is calculated from git (`setuptools-scm`, `hatch-vcs`, `vcs-versioning`) fails to
construction when the history is missing: clone `--depth 1` (that of the benchmark), archive without `.git`. Zero the
detects in the error and restarts with `SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0` (and its variants), once,
journaled. Checked on a project `setuptools-scm` without git repository: installation then launch. The number of
installation patch rounds changes from 4 to 6 (several patches can follow one another).
On `avibe-bot/avibe` (hatch-vcs), the patch advances the build but the repository then requires `ui/dist`
(interface to be built before: `force-include` of hatch): failure not handled, it is a prerequisite of the repository.
Consequence for the measurement: the failures `uv sync --frozen` of the real samples came at least in part from the
superficial clones, not deposits.

## 0.12.6: third real sample, Node by range, optional steps

**Third sample** (seed 11, 12 Node + 12 Python, never seen, delay 75 s, without disk incident;
`benchmark/results/live-v12-sample3.json`, measured **before** the fixes below): 24 repositories, **17 built,
7 launched, 4 respond in HTTP** (gale, phanpy, sveltia-cms: 200; glomberb: 404), **4 CLI tools**, 5 chess
installation, 2 installations still in progress at the deadline. With the second draw (16 deposits): 40 deposits, 6 which
respond in HTTP (15%), almost all of which are Vite type Node applications. Small samples, not to
extrapolate.

**Node version by range**: a `engines.node` of the form `>=20.0.0` was read as "exactly 20.0.0" (the
lower bound): Next.js, which requires 20.9, refused to start (`wind-comic`). A small semver beach evaluator
(`>=`, `>`, `<`, `^`, `~`, wildcards, `||`) now chooses the **most recent LTS that fits** (online: via
`index.json` ; offline: major LTS 24/22/20/18…). An exact or partial version remains respected (`20.11.0`,
`20` → last 20.x). Verified offline: `>=20.0.0` → Node 24.21.0.

**Optional steps**: `manage.py collectstatic` no longer prevents launch if it fails (`overmind`: installation
was blocked); it warns and continues (`Plan.optional_steps`). **`bun install`** is covered by the fallback
`--ignore-scripts` (`better-sqlite3` from `oh-my-agent`).

Not covered in this draw: `yarn install` (`MatrixMedia`), `-e .` failing (`dd-trace-py`, `forge3d`), servers
Electron/TUI without screen (`token-monitor`, `selkies`), CLI without argument (`pynguin`, `loushang`).

## 0.12.7: replay of 24 deposits before/after, retry after disk failure

Same 24 repositories as in 0.12.6, replayed with the fixes (`benchmark/results/live-v13-sample3-replay.json`):

| | before | after |
|---|---|---|
| built | 17 | 19 |
| launched (living process) | 7 | 9 |
| respond in HTTP | 4 | 4 |
| CLI tools | 4 | 5 |
| installation failures | 5 | 3 |

Three repositories change, each thanks to a specific fix: `oh-my-agent` (failure `bun install` → launched, fallback
`--ignore-scripts`), `overmind` (`collectstatic` failure → it starts, it's a CLI tool), `wind-comic` (Node 20.0.0
refused by Next.js → Node 24, built and launched; Next still compiles after 75 s, so no HTTP response).
21 others are unchanged. **The number of HTTP responses has not changed**: these fixes repair
installations but do not transform CLIs/agents into servers.

The batch replay initially classified `wind-comic` as an installation failure: disk full (`ENOSPC`) at the wrong time,
not the deposit. The benchmark now retries **once** after flushing everything when the install failure comes
disk (`retried_after_disk_failure`); `wind-comic` replayed alone is in the report (note included). A Next.js repository
needs more than 1,5 GB: the threshold of 900 MB does not avoid all cases.
Limit: 24 deposits, before/after comparison on the same sample (not independent of the fixes resulting from it).

## Fourth real, independent sample (Node, seed 23)

Pull of never before seen 24 Node repositories from the remaining 62 “executables” of the 500 corpus, launched with the patches
0.12.7 (`benchmark/results/live-v14-sample4-node.json`). **22 evaluated** (the benchmark stopped before the last 2,
disk full; partial report retained). No fixes have been made from these repositories.

| 22 Node repositories | |
|---|---|
| built | 12 |
| launched (living process) | 9 |
| **respond using HTTP** | **6** (5 × 200, 1 × 401) |
| CLI tools | 1 |
| installations still in progress at the deadline of 75 s | 6 |
| installation failures | 4 (3 × `pnpm install`, 1 × `npm ci`) |

Or **27 % of HTTP responses** on Node repositories, of the same order as the first draw (4/15). 6 “install_timeout”
are large monorepos (xen-orchestra, waveboxapp, etc.): the measurement underestimates this rate, a longer delay would be necessary.
**No independent testing for Python**: only 3 unused executable Python repositories remained; Python numbers
available come from samples already exploited to find fixes. `pnpm install` (3 on 4) failures are
the most common untreated case: causes not analyzed.

## 0.12.8: analysis of 4 Node pull installation failures

None of the four were repository defects that a general patch would have fixed, except one:
- **`pnpm install` ×3 (`agentconnect`, `gsd-pi`, `cohub`): disk full**, not the repository. `agentconnect` replayed alone with
  1,7 Free GB still exhausts space (`ENOSPC` on `@resvg/resvg-js`); `cohub` and `gsd-pi` leave files
  pnpm temporaries cut. My previous reading (“frequent `pnpm install` failures”) was therefore **false**: these are
  sandbox artifacts. The benchmark better recognizes the full disk (`database or disk is full` in addition to `ENOSPC`) and
  classifies the failure **`disk_full`** (counted separately in `disk_full`) when it persists after a retry.
- **`npm ci` on `MyAgents`: `EBADDEVENGINES`.** The repository declares `devEngines.packageManager` = npm ≥ 11.15.0, while the
  Node selected npm book 10.9.7. Zero reads the required range in error, installs this npm in a dedicated folder
  (`~/.zero/runtimes/npm-<plage>`), puts it in front of `PATH` for installation **and** launch, then tries again.
  Checked on a mini project (requires npm ≥ 11: install, then start). **Not verified on MyAgents**: deposit too much
  big, it filled the disk during the test.
Consequence: Node pull 27 % HTTP response rate does not change, but its actual “installation failures”
fall from 4 to 1 (repaired), and 3 are to be stored under “disk” rather than under “repository”.

## 0.12.9: slow single repos replayed at 240 s, lockfile unusable

6 Node repositories whose installation had not finished at 75 s, replayed with a delay of 240 s
(`benchmark/results/live-v15-slow6-240s.json`): no more “install_timeout”. **3 built, 2 launched, 0 answered
HTTP, 3 installation failures** (2 × `npm ci`, 1 × `yarn install`). The 75 deadline therefore mainly underestimated the time,
not success.

Both `npm ci` (`lxserver`, `sandbase-harness`): the lockfile points to **registry mirrors** (Tencent,
npmmirror); here npm refuses these URLs (`EALLOWREMOTE`, sandbox config `allow-remote=none`: specific to this environment)
and, with `--replace-registry-host=always`, versions only exist on the mirror (404). New fallback: `npm ci`
→ **`npm install --no-package-lock`** when the error is `EALLOWREMOTE` or `E404` (peer conflicts and lockfiles
out of sync keep priority). The versions may then differ from those of the lockfile. Verified on `lxserver`:
installation then server listening (port 9527). Not replayed on `sandbase-harness` (same error). Untreated:
`xen-orchestra` (`yarn install`, monorepo to workspaces), `waveboxapp` (`scandir` from a missing folder).

## 0.13.0: dependencies by hardware variant (§10 specification)

Plans read on real AI projects (shallow clones, **no installation or launch**, they weigh several GB):
`ComfyUI` and `stable-diffusion-webui` already gave a coherent plan (`--torch-backend=auto`, CPU wheels reported without GPU,
template files to download). `oobabooga/text-generation-webui` failed: its dependencies are sorted by variant
(`requirements/full/requirements{,_amd,_apple_silicon,_cpu_only}.txt`, `requirements/portable/…`).

Zero now chooses the variant based on detected hardware (`gpu.pick_requirements_variant`) when there is no
`requirements.txt` nor “base/common/main…” game: group `full` (otherwise `main`, `base`, `default`, `all`, otherwise the first),
then NVIDIA → base file, AMD → `_amd`, Apple Silicon → `_apple_silicon`, Mac Intel → `_apple_intel`, Vulkan →
`_vulkan` or CPU, **no GPU → `_cpu_only`** (otherwise the base). The choice is indicated in a note with the means of changing it.
On this sandbox (without GPU), text-generation-webui gives `requirements/full/requirements_cpu_only.txt` and `python server.py`.

**Fixed in passing**: repository fingerprint ignored `requirements/**/*.txt`; a deposit whose only manifests are
there had the fingerprint of an empty string (`e3b0c442…`), the same as all the others. It now includes these files
(all variants, independent of hardware). Impact: An existing `zero.lock.json` or registry entry for
such deposits will be seen as "derived" once.

Limitations: **choice never tested on real hardware** (no GPU here) nor by a complete installation; he follows
naming conventions (`_cpu_only`, `_amd`, `_apple_silicon`…) seen on a single project. `karpathy/nanoGPT` (none
manifest, dependencies in the README) remains without a plan: “Python scripts at the root but no manifest recognized”.

## 0.14.0: Python scripts without manifest (dependencies deduced from `import`, §2)

A Python script repository at the root **without any manifest** (`karpathy/nanoGPT`, dependencies only in the
README) only gave an error. Zero now reads `import` from root scripts (parsing, without
execute), removes the standard library, local modules (root files and folders) and names too
generic (`utils`, `config`, `model`, `lib`…: risk of installing an unrelated PyPI homonym), then installs the rest
(table `PY_IMPORT_MAP`: `cv2` → `opencv-python`, `yaml` → `pyyaml`…, otherwise the name of the module with `_` → `-`).
Entry point: the only script with guard `if __name__ == "__main__"`, otherwise the only script that no one imports;
**if there are several, zero offers the choices instead of guessing one**. The plan note says that the outbuildings are
deducted. On nanoGPT: `numpy, tiktoken, torch, transformers, wandb` + `--torch-backend=auto`, and four proposed scripts
(`bench`, `configurator`, `sample`, `train`).

Limits: PyPI name **assumed** equal to module name (a module whose package has another name will fail, recovery
will then install by import); only the root scripts are read (nanoGPT also imports `datasets`, `tqdm` from a
subfolder: not seen); complete installation and launch not done (PyTorch, several GB). An existing case changes:
a repository with a `server.py` and a Node subproject is no longer rejected, it receives an inferred Python plan (the subfolder
remains ignored, `--project` works).
Footprint: for a repository without any manifest, the root scripts go into the footprint (otherwise all these repositories had
that of an empty string, therefore the same register lock); with a manifest, the source code still doesn't go into it.
A test of the suite had failed intermittently: see “Testing Signals” below.

## Testing signals: probable cause of intermittent failure, and test becoming hollow

`test_ignored_sigint_still_cleans_children` searched for leftovers with `ps | grep app.py` on **entire machine**: another
`zero`, a benchmark or command containing "app.py" caused it to fail (probable cause of isolated failures, never
reproduced in 12 clean passes). By correcting it I noticed that it could also **succeed without checking anything**: if zero
did not launch the script (unknown entry name), there was nothing to clean up. It now uses a script name
single, launches the script via `--cmd`, **verifies that the script has started**, then that no process with that name remains
(0,7 s instead of ~90 s idle wait). No product code changes.

## Corpus of 1000 deposits (specification §15): second batch and cumulative balance sheet

Second batch `benchmark/corpus.public500b.txt` (500 repositories, same fixed rule, slice **100 to 499 stars**, GitHub API of
2026-10-10, detection only, `benchmark/results/public500b-v1.json`). 78 deposits of more than 300 MB (API size) are discarded:
**422 evaluated**, 0 cloning failed, 0 detector error. **240 executables = 56,9 %** (55,7 % excluding commands deducted from
Makefile). By language: Node 106/143 (74%), Go 57/78 (73%), Python 39/74 (53%), Rust 38/70 (54 %).

**Cumulative balance of the two batches: 824 deposits evaluated on 1000 selected** (176 excluded for their size):

| | deposits | executables | rate |
|---|---|---|---|
| Nodes | 270 | 204 | 75,6 % |
| Go | 158 | 106 | 67,1 % |
| Python | 136 | 71 | 52,2 % |
| Rust | 143 | 73 | 51,0 % |
| without recognized language | 117 | 0 | — |
| **Total** | **824** | **454** | **55,1 %** (53,6 % outside Makefile) |

Statuses: 454 executables, 165 without launch command (mostly libraries), 88 ambiguous entry points, 63 monorepos
ambiguous, 54 not supported. **Reading**: the detection of an order is stable around **54-55 %** from one batch to another (53,2 % then
56,9%), far from the 72% of hand-chosen corpora. Detection only: nothing has been launched on these 824 repositories; this rate does not say
that the command is the correct one or that it starts (see the real samples: approximately one in four “executables” serves one page).
Bias: recently active deposits, moderate popularity (100 to 3000 stars), deposits of more than 300 MB excluded (so mainly
light applications), five languages questioned (the first batch and the second do not overlap).

## 0.14.1: old repositories (§16) and Python 2

**Selection**: GitHub, `pushed:<2019-01-01`, 300 to 4000 stars, Python and JavaScript, ≤ 200 MB, 116 repositories (latest commits from 2015 to
2018). **Detection only: 30/116 executables (26 %)**, 28 unsupported, 42 without command, 15 ambiguous. **Actual launch of 20 of them**
(random draw, seed 5, delay 90 s; `benchmark/results/live-v16-old-repos-20.json`): 8 built, 2 launched, **2 respond via HTTP 200 without
no edit**: `streamproc/MediaStreamRecorder` (last July commit 2018, server on port 9001) and `arscan/encom-boardroom`
(October 2017; the page responds, but the GitHub API it calls refuses requests without authentication). **This is §16 reached**, with a
very low rate: 2 on 20 (10%), both Node applications.

Causes of failures (18 on 20): about half of Python projects are **Python 2** (`print` without parentheses, `cPickle`, `theano`,
`cudarray`), dependencies not found (`meatier`, `RocketMap`: `npm install`; `Vue-cnodejs`: `yarn install`), resources missing
(`registry.bower.io`), Recent node facing 2016 code (`reapp`, `ttystudio`: `MODULE_NOT_FOUND`), slow installation (`home-automation`).
Reduced size, sample filtered on ≤ 200 MB and on repositories where an order is found.

**Python 2 explained**: When the installation or launch fails, a typical trace of Python 2 (`Missing parentheses in call to 'print'`, `No module
named cPickle/urllib2…`) déclenche un message clair (« ce projet semble écrit pour Python 2… à migrer avec `2to3` or to launch with a Python 2"). In the
deduction of dependencies without manifest, the modules specific to Python 2 (`cPickle`, `urllib2`, `ConfigParser`, `Tkinter`…) are no longer installed as packages
PyPI and are reported in a note. Checked on `fraser-hemp/gradify`. Zero still does not provide Python 2 or port the code.

## 0.15.0: `zero doctor`

New command `zero doctor [--json] [--no-network]`: system and architecture, Python, user (root or not), IPv6 on the
local loop, free space in `ZERO_HOME`, versions of `git uv node npm pnpm yarn bun cargo go`, Docker/Podman (presence **and** daemon
reachable), local fallback services (redis, postgres, MySQL/MariaDB, MongoDB), GPU, and network access (HEAD, 5 s) to github.com, pypi.org,
registry.npmjs.org, nodejs.org, go.dev and static.rust-lang.org. Goal: attach a reliable diagnosis to each test return on a machine
actual (return model added to `docs/VALIDATION.md`). No personal data collected (neither machine name nor address).
On this sandbox it reflects the limits already noted (no IPv6, `nodejs.org`/`go.dev`/`static.rust-lang.org` inaccessible, neither Docker nor
GPU). Corrected by the way: `go` does not have a `--version` (`go version`).

## 0.16.0: command line tools (arguments after `--`)

Only about one in four “executables” serves one page; many others are command line tools which, launched without arguments,
show their help and leave. Two changes: (1) `zero run <dépôt> -- <arguments>` passes everything after `--` to the launched command (arguments
protected; for `npm run|start|test`, zero inserts `--` otherwise npm consumes the options: fault found by an end-to-end test; ignored with a
warning for a Procfile, refused if there is no command); (2) a quick output (< 8 s) which displays usage/help gives a clear message
instead of failure: “looks like a command line tool... installed; launch it with your arguments.” Same heuristic as the benchmark
(`recovery.CLI_HELP`). Verified on a mini Node tool (use without argument, result with `-- data.txt --verbose`). Limit: detection by text
(“Usage:”, “--help”…), so a server which prints startup help and then exits would also be classified as a “tool”.

## 0.17.0: distribution (three installation modes)

Before: `./bin/zero` from repository, or `pip install -e .`. Now: (1) `install.sh`: launcher `~/.local/bin/zero` to cloned folder
(refuses a Python < 3.10, warns if `~/.local/bin` is not in the `PATH`, `ZERO_INSTALL_DIR` to change folder); (2) `scripts/build_pyz.py`:
single executable `dist/zero.pyz` (zipapp, 63 KB, shebang `/usr/bin/env python3`), independent of the source tree; (3) `pip install .`.
**Flaw fixed**: `pyproject.toml` announced version `0.10.1` while the product was progressing; the version now comes from `zerodev.util.VERSION`
(only one source). Checked: `zero.pyz --version` and `doctor`, `pip install` in a clean environment (command `zero` and metadata
`0.16.0`), `install.sh` with a false personal file, refusal of a Python that is too old. **Not verified**: macOS, `pipx` (not installed here), published on
PyPI (no packages published, no names reserved), Windows (outside scope). “git clone && zero” on a machine without Python remains impossible.

## 0.18.0: isolated execution `--sandbox` (specification §3)

`zero run --sandbox` wraps **each installation step and each launch** (`run_tee`, `Supervisor.spawn`; also in `--all`) in bubblewrap:
read-only system (`--ro-bind / /`), personal folder replaced by a tmpfs (invisible secrets), private `/tmp`, write only in repository and
`~/.zero`, Isolated PID and IPC namespaces, `--die-with-parent`. Caches (`uv`, `npm`, `pip`, `yarn`, `pnpm`) are redirected to `~/.zero/cache` (otherwise they would go
in the hidden home folder and would be lost). The network remains shared (a development server must remain reachable).
**Verified in real life** (bubblewrap 0.9.0, this sandbox): a fake project whose `postinstall` reads `~/.ssh` and writes to `~` and `/usr`: secret **invisible**, writing to `~` without
effect on the host (private tmpfs), `/usr` **refused**, writing to the repository possible; the server responds using HTTP **from the host**; no process or residual `bwrap` after shutdown;
`npm install` works in the sandbox. Tests: argument construction (mount order), refusal without bubblewrap, and a real containment test (ignored if
bubblewrap is unusable). `zero doctor` indicates whether isolation is available.
**Limits, not to be minimized**: no barrier against code exploiting the kernel or against outgoing network requests; readable system files outside the home folder
remain legible; actions specific to zero (downloading runtimes, containers, local services) are not in the sandbox; **macOS not supported** (`sandbox-exec` not used);
**Docker/Podman as an unmade isolation alternative**; tested on a single kernel (that of the sandbox: user namespaces allowed — this is not the case everywhere, hence the explicit refusal).

## 0.19.0: decide between ambiguous entry points (README, Dockerfile, compose)

On the 824 repositories evaluated, 151 were ambiguous: 63 single-repos and **88 multiple entry points** (57 Rust, 28 Go, 3 Python). Zero now holds back one
choice only if it is **the only one supported by textual proof**: `ENTRYPOINT`/`CMD` of a Dockerfile (root, `docker/`, `build/`, `deploy/`) or `command`/`entrypoint` of a compound
(weight 3), or a command to launch the README whose name is the **target** (`cargo run … --bin/-p NOM`, `./target/release/NOM`, `go run|build ./cmd/NOM`, `python NOM.py`; weight 2).
A mention in prose, a name cited as an argument or as a file (`--config NOM/config.json`) does not count; a tie leaves the list of choices. The plan notes the
source and alternatives (`--cmd` to correct).
**Measurement** (88 cases, detection only): **13 decided (15 %)**, 75 remain ambiguous. A first version, too permissive, separated 20 from which false positives that I have
found by checking the proof lines (`yellowstone-grpc-geyser`, a plugin cited as an argument; `./` taken for a proof): tightened. **Manual control of the first 12**: 9 rest
on a `ENTRYPOINT`/`CMD` (solid), 3 on a README command (plausible; `oxideterm-cli` is only launched there with `doctor`). **None have been launched**: the Go and Rust toolchains are
inaccessible in this sandbox, so “the right entry point” is not proven. Ambiguous 63 **monorepos** are not processed. Not remeasured on 824 (the detection rate of 55,1 %
would go up at most about 1,6 point). Bench: field `entry_from_docs` and counter `entry_from_docs`.

## 0.20.0: multi-stack monorepos (under `src/`, `app/`, `apps/`) launched alone

Of the 63 ambiguous single repository corpora, **none** was recognized as multi-stack: the detection only looked for `backend/`, `frontend/`, `api/`, `web/`… only at the root, while many
stored under `src/` or `app/` (`src/backend` + `src/frontend`). It now also looks at `src/`, `app/` and `apps/` (`app/` is only a container if it itself contains such
files). A monorepo whose subprojects are **different languages** (≥ 2) and at most **3** stacks is launched alone, as with `--all` (explicit message, distinct ports,
Backend URL given to frontend); beyond that, or with `--project`/`--cmd`, zero always asks to choose. **Bug found by a test**: `AmbiguousProject` did not retain its attribute
`multistack`. **Verified in real life**: a monorepo `src/backend` (Python) + `src/frontend` (Node): backend on 8000, frontend on 3000 which queries the backend (`frontend -> backend ok`), none
residual process.
**Actual effect on 63**: only **5 are recognized multi-stack** (`couchers`, `open-wearables`, `gradient`, `patchies`, `dex`), the other 58 remain ambiguous: single repos of packages of the same language,
libraries, documentation, where "running everything" doesn't make sense. The automatic launch of these 5 has **not** been tested on real repositories (mobile Expo, MCP, daemons, etc.): only the synthetic case has been tested.
The benchmark always classifies these repositories as “ambiguous_monorepo” (field `multistack` and counter `multistack_monorepos`).

## 0.20.1: remeasurement of detection on 823 deposits with code 0.20

Same filings as balance sheet 0.12 (today's clones), `benchmark/results/public1000-remeasure-v0.20.json`. **473/823 = 57,5 % with command** (55,1 % before);
**excluding last resort heuristics: 440/823 = 53,5 %** (53,6 % before: the “safe” core has not moved). 33 deposits earned come exclusively from heuristics added since:
**13** entry points divided by proof (README/Dockerfile) + **12** Makefile commands (counted from 0.12) + **7** script repositories without manifest whose dependencies are deduced from `import`.
Status changes, all explained: 13 ambiguous → executable (department), 7 unsupported → executable (imports deduced, including a **Caliber plugin**, which is not launchable: false positive
assumed this heuristic, hence its separate counting), 2 unsupported → ambiguous, 1 executable → without command (`react-big-schedule`: its `package.json` no longer has a script `dev`, change of the deposit
and not zero), 1 cloning failed (repository become inaccessible). **No regression from zero.**
The report now counts `deps_deduced` separately, and the "strict" rate excludes the three heuristics (Makefile, README/Dockerfile proof, inferred imports).
Incident: when launching 9 parallel cloning, the disk dropped to 239 MB; added disk wait for parallel detection (`wait_for_disk`, ≥ 700 MB free) and restarted parallel cloning at 6.

## Hygiene (without version change): static analysis and mutation tests

`pyflakes` on `src`, `tests` and `scripts`: 5 mild warnings after twenty versions (imports and one variable unused), fixed; the code is clean.
**Mutation tests** on three recent behaviors (we deliberately break the code and verify that the tests fail): the sandbox (no longer hide the folder
personal) and the insertion of `--` for npm are detected; the tie-breaking of entry points **survived** the removal of the minimum proof threshold (a single analyzable choice
without any proof was retained). A test has been added, and the replayed mutation is now detected. Only three mutations: this is not a measure of the quality of the whole
continuation (227 tests), only a targeted check after having already found a hollow test (signal test).

## Packaging: the zip contained artifacts and `build/` was tracked by git

By replaying the experience of a first user (decompression of the deliverable into a blank folder, tests, examples), two packaging defects appeared, present for several versions: (1) the zip was done
from the **working folder** and included 54 superfluous files (`__pycache__`, `build/`); (2) `build/` (artifact of `pip install .`) had been **accidentally committed** with a `git add -A` (18 tracked files).
Fixed: `build/` removed from tracking and ignored; new script `scripts/export_zip.py` which builds the zip from a **clean export of the repository** (tracked files + history), refuses a repository for non-modifications
validated and reports any suspicious files tracked (pattern test added). Checked on the decompressed deliverable: 0 superfluous file, 227 tests OK, `./bin/zero --version`, and the examples `python-app` (HTTP 200 on 8000),
`node-app` (3000) and `multistack-app` (8000) start from this folder, with no residual processes. In the process, I killed my own shell again with a `pgrep -f` whose pattern appeared in my command.

## 0.21.0: popular starters (Next, Vite, Django, Flask) and three fixes

16 starters/templates chosen by the GitHub API (by framework, by number of stars, lightweight), launched in real time (delay 100 s, `benchmark/results/live-v17-starters.json`, **second pass, after fixes**;
the report of the first pass was deleted by mistake on my part by a `rm` that was too wide: only its broad outlines remain with me, five failures `yarn install`/`pnpm install`). Second pass: **6 built,
5 launched, 3 respond via HTTP** (`mantinedev/vite-template` 200, `jelmerdejong/flask-app-blueprint` 200, `django-react-boilerplate` 404), 2 ambiguous single repos, 3 without command, 1 installation still in progress, 4 failures
installation. Such a small sample does not give a rate; These are mainly defects to be corrected. Found and fixed:
- **pnpm ≥ 10: `ERR_PNPM_IGNORED_BUILDS`** (unapproved dependency scripts treated as an error, including version 12) affected 3 Vite/Next starters. `--ignore-scripts` does **not** avoid this error
  (verified); zero restart with `--config.strict-dep-builds=false` (pnpm default behavior: scripts not executed, without errors). Verified: `whylisa/vite-react-template-typescript` installs and starts (port 3001).
- **Corepack does not attach `repo.yarnpkg.com`** (corporate proxy, filtered domain; sandbox case): `yarn install` failed. Zero sets `COREPACK_NPM_REGISTRY` to the npm registry (the configured one if there is one) and tries again.
  Checked by hand (Yarn 4 installation is progressing); **automatic correction was not replayed on a real repository after coding**, only unit tested.
- **`manage.py` in a subfolder** (`<projet>/manage.py`, `src/manage.py`) was not seen (only the root was). Zero looks for it in ONE direct subfolder whose contents look like Django or Flask-Script
  (multiple candidates: nothing) and launches `python <sous-dossier>/manage.py runserver`; `collectstatic` and migrations follow. Checked: `flask-api-starter-kit` → `python src/manage.py runserver`; `django-hackathon-starter` reached
  the installation, which fails for a real reason: Django 1.7.6 from 2015, dependencies in Python syntax 2 (explicit message).
Remain without processing: `langchain-nextjs-template` (`yarn patch`: “cannot apply hunk”), `tedivms-flask` (Python installation), `Flask-User-starter-app` (old Flask facing recent Jinja), `fbone` (only one `wsgi.py` for mod_wsgi),
monorepos `materio…` and `vite-templates`, `maomao1996/vitepress-nav-template` (`pnpm install` failure to reprocess, unstable network).

## 0.22.0: old Python projects (version fallback, cascading API breaks)

Continuation of the starter test: `tedivm/tedivms-flask` (2020, Flask) served as a common thread; three zero faults appear one behind the other, all corrected.
- **Old pin that does not build** (`pyyaml==5.4` against Cython 3, no wheel for Python 3.10+): after the failure to build a **pinned** package (excluding missing system headers, excluding Python code 2),
  zero tries Python 3.9, then 3.8, without ever going below the project floor (`>=3.10` → refusal). Checked by hand: Python 3.9 installs these dependencies, 3.10 and 3.11 do not.
- **Bug found en route: after a downgrade of Python, the installation phase forgot its already installed fixes** (the plan is recalculated, the temporary psycopg2 file disappears) but still believed them
  applied, so did not replay them. The launch phase already did this correctly; installation also now. Installation hotfix rounds: 6 → 8.
- **Known API breaks, cascading** (`PY_API_BREAKS`, short table to maintain): `jinja2` ≥ 3.1 (`escape`, `Markup`…), `markupsafe` ≥ 2.1 (`soft_unicode`), `werkzeug` ≥ 2.1 / 3 (`BaseResponse`, `url_quote`…), `flask` ≥ 2.3
  (`escape`, `Markup`), `itsdangerous` ≥ 2.1 (`json`), `sqlalchemy` ≥ 2 (`no attribute '__all__'`, `Engine.execute`), `wtforms` ≥ 3 (`TextField`). If the Flask **installed** is old (< 2.2, read in Friv), zero suddenly installs the whole thing
  consistent from before 2022 (`flask<2.1 werkzeug<2.1 jinja2<3.1 itsdangerous<2.1 markupsafe<2.1`) instead of capping a single package, which would let the others break one by one; with a modern Flask, single ceiling.
  Patch budget at launch: 2 → 4 attempts (each patch is only attempted once).
**Actual result on `tedivms-flask`**: the installation passes (Python 3.9, psycopg2 pin removed) then the three fixes follow each other (Flask set before 2022, `sqlalchemy<2`); the application finally fails on **its own configuration**
(`Config setting SECRET_KEY is missing`): A variable that the user must provide, not a dependency. It therefore does not start without intervention. **Limits**: ceiling table to maintain (an unknown case fails); a ceiling
can break a project that was actually using the recent version (each fix is logged); verified in real life on a single deposit; `httpbin` (`BaseResponse`) and `Flask-User-starter-app` are not replayed.

## 0.23.0: old Flask projects replayed (httpbin, Flask-User-starter-app) and example configuration

Replay of the two repositories which had motivated the API case table of 0.22.0, with the ports checked free before each test (a first test had wrongly assigned the server of a previous test,
remained alive on port 8000, at the following repository: method error on my part, redone properly).
- **`postmanlabs/httpbin`** (Pipfile + setup.py, Python 3.6 requested): Python 3.8, step `Pipfile.lock` ignored, `gunicorn` installed, then `BaseResponse` → Flask set from before 2022: **HTTP 200** (it failed on `BaseResponse` in 0.11.1).
- **`lingthio/Flask-User-starter-app`** (2018): Python 3.6 → 3.8, then three chained API cases (`jinja2` ≥ 3.1, `werkzeug` ≥ 1.0 for `from werkzeug import url_encode`, `sqlalchemy` ≥ 2), then the module `app.local_settings` absent.
  Two additions: a second set of versions for very old Flask (`flask<1.1 werkzeug<1.0 jinja2<3.0 itsdangerous<1.2 markupsafe<2.0`, imports from `werkzeug` at the top level) and **copy of a configuration template**:
  if the absent configuration module has a unique neighboring model (`local_settings_example.py`, `config_local.py.example`, `…_sample`, `…_template`, `….dist`), zero copies it (`cp -n`: never overwrite; no copy if it are two models or if the module exists).
  Result: **HTTP 200** (`Running on http://127.0.0.1:5000/`).
**The repository is modified in this case**: a new configuration file is created there (generally ignored by git), this is reported in the fix description. Limitations: Copy the example configuration as is (dummy keys);
very general pattern but verified in real life on a single deposit; the API case table remains to be maintained.

## Replaying failed 10 Python repositories (with code 0.23.0)

`benchmark/results/live-v18-python-replay.json`, delay 120 s, same deposits as previous samples (so **not** an independent sample). Result: **9 built, 2 launched, 1 in HTTP
(microblog, already in 200), 3 command line tools, 1 installation still in progress** (`aiavatarkit`, NVIDIA wheels download). Status changes: `kaos-tools` changes to “launched” (an interface
in terminal), `datacontract-cli` and `NUR` are now classified as CLI tools; the others are unchanged. **Low real gain**: the remaining failures no longer come from dependencies but from the nature of the projects
(terminal interface that requires a prompt, feed server that requires a screen, CLI tool, ML models to download). This is not a zero defect that a general patch would fix; I am therefore no longer looking for gain on this side.

## 0.24.0: version of Python/Node deduced from Dockerfile or CI (specification §2): useful in theory, **without measured gain**

When nothing sets the version (neither `.python-version`, `runtime.txt`, `.tool-versions`, `requires-python`, `Pipfile`, nor `.nvmrc`, `.node-version`, `engines.node`), zero searches for the version that the project actually uses: `FROM python:3.9` /
`FROM node:20` of a Dockerfile first (this is what is delivered), then the CI (GitHub Actions `python-version` / `node-version`, GitLab `image:`, Travis `python:` / `node_js:`). A matrix of versions → the most recent (Node at most the LTS
current, Python at most 3.14, never an unstable version); expressions `${{ }}`, pypy and nightly ignored. The plan note says where the version came from (`déduit de Dockerfile…`). Can be disabled: `ZERO_NO_RUNTIME_HINT=1`.
**Coverage** (240 Node/Python repositories in the corpus): among those **without declared version**, 58 % of Node projects (44/76) and 35 % of Python projects (7/20) receive an index, almost all from `.github/workflows` (43 to 51).
**A/B test on the same 13 repositories, with then without the index** (`benchmark/results/live-v19-runtime-hint-ab.json`, real launches): **12 identical, 1 worse with the index, 0 better** (`obsidian-local-images`: Node 16 read in an old CI
→ installation failed, although it launched with LTS by default). Defect corrected: **end of life versions coming from the CI are ignored** (Node < 20, Python < 3.10); the Dockerfile is not filtered. Second defect found by the
measurement: matrices containing `3.15` caused a Python version not yet stable to be proposed; capped.
**Honest conclusion**: no benefit demonstrated on this sample of 13; the default (the latest stable version) already works in most cases, and the fallback ladder catches the others. I keep the function (it is conservative, deactivatable,
and the specification calls for it), but **it should not be presented as a proven improvement**. Limit: The end-of-life filter is a constant to update (`NODE_OLDEST_FROM_CI`, `PYTHON_OLDEST_FROM_CI`).

## Replay of two starters rated “untreated” (code 0.24.0)

- **`realpython/flask-boilerplate`** (never replayed since adding the API case table): `gunicorn` missing from dependency file → installed; `ImportError: TextField` (WTForms 3) → `wtforms<3` ;
  **HTTP 200** on port 8000, ports checked free initially. It failed on `TextField` in 0.10.11.
- **`langchain-ai/langchain-nextjs-template`**: `yarn install` installation now passes and Next.js starts ("Ready in 555ms", port 3000; HTTP response not checked by `curl`). My old note “`yarn patch`: cannot apply hunk”
  actually indicated a failure of Yarn itself (download via corepack blocked), corrected to 0.21.0 by the npm registry: **my reading of the cause was wrong**.

## 0.24.1: Product-aligned documentation and help

Rereading `zero --help` and the README against the real behavior after twenty-five versions. Fixed: `--services` help omitted MySQL/MariaDB (added in 0.9.0); `--all`'s help did not say that monorepos
2-3 stacks of different languages are launched automatically; the README did not document `--sandbox` nor `--` in the options table, nor the environment variables (`ZERO_HOME`, `ZERO_REGISTRY`,
`ZERO_NO_RUNTIME_HINT`, `ZERO_BENCH_CLEANUP`, `PORT`), nor the modules `procs.py`, `sandbox.py`, `doctor.py`, and its "principle: refuse rather than guess" ignored the two exceptions (entry point supported by a proof,
multi-stack monorepo). No change in behavior.

## Benchmark traceability (without version change)

Additions: `benchmark/README.md` (what each field, each corpus, each results file measures, with the code version and reservations; the 27 files with similar names were not explained) and
`benchmark/build_corpus_rule.py` (reproduces the fixed rule of the two corpora of 500; verified against the API in real life on a small print run; the results depend on the date, hence the corpora kept). Corrected:
`corpus.public.txt`'s header claimed that the GitHub API is unusable without a token, which was only true at the time it was formed. The main README links to `benchmark/README.md`.

## 0.24.2: rereading and simplification of the code (without functional change, one message corrected)

Measurement first (`radon`, `vulture`): cyclomatic complexity **medium B (6,4)**, but a rank function **F (55): `install_deps`**, followed by `run_project` (41), `detect_node`/`detect_python` (35), `diagnose` (33), `summarize` (30);
almost no dead code (two remnants removed: `STATUSES`, `in_tty`).
**Refactorings done**, each checked before continuing:
- **`install_deps`: 55 → 8.** The loop of 8 turns remains; each patch becomes a small function (`_fix_corepack`, `_fix_psycopg2_swap`, `_fix_npm_ci`…) evaluated in the order of `INSTALL_FIXERS`, on a shared state (`InstallState`).
  The subtleties are preserved: the psycopg2 exchange without effect falls on the removal of the pin in the same round, `devEngines` falls on the following ones if it fails, the Python downgrade resets the patches to zero.
  **Safety net written BEFORE touching the code**: 14 characterization tests (shell steps which fail with the correct message), passed on the old code then on the new; a test has been verified by mutation (it fails if reset is removed).
  **Verified in real life after the fact**, results identical to before: `tedivms-flask` (Python 3.9, psycopg2, Flask ensemble, SQLAlchemy, up to `SECRET_KEY`), `lxserver` (`npm ci` without lockfile, server listening), pnpm starter (`strict-dep-builds`).
- **`summarize` (bench): 30 → 18**, by counter table. **Compared to the old version on the 124 real report summaries: 0 difference** (keys, values ​​and order).
- **`diagnose` (retrieval): 33 → list of 9 ordered rules** (`RULES`). **Compared to the old version on 552 cases** (23 error outputs × 6 plans × 2 Flask states × 2 patch sets already attempted, including 364 producing a fix): **0 difference**.
**A misleading message corrected** (it existed before): switching to Python 3.9 for an old pinned package that does not build (`pyyaml==5.4`) was announced "a module removed from Python 3.12 is required"; he now says the real cause (added test, three separate reasons).
An old test which read the source code (considered weak) is deleted: the corresponding behavior test replaces it. Medium complexity: B (6,4 → 6,1).
**Not done, on purpose**: `run_project` (41), `detect_node`/`detect_python`/`detect_rust` (32-35), `make_plan` (29), `dispatch` (25) remain complex. The detectors are cascades of rules well covered by the tests but I do not have a characterization net
equivalent for `run_project` (services, supervision, recovery at launch): refactoring it without it would be a gamble.

## 0.24.3: Simplified `run_project` (41 → 7), same method

`run_project` (rank F, complexity 41) is divided into `_prepare_environment`, `_setup_run_environment` (services, variables, PORT, migrations), `_supervise` (the launch loop with its two types of restart:
`_retry_with_other_python` and `_apply_run_fixes`), `_report_outcome` and `_record_success`. Complexity: **41 → 7** (the most complex of the new functions: 10); project average **6,04** (B).
Same method as in 0.24.2: **15 characterization tests written first** (supervision, services, fixes, PORT, .env, migrations, messages) by simulating everything related to the system, passed on the old code then on the new;
**4 mutations detected** (fixes reset after Python downgrade removed, service shutdown removed, restart budget ignored, user `.env` overwritten). One detail preserved: the final environment (replaced by the
Python downgrade) is used for lock registration.
**Verified in real life after refactoring**: `fullstack-app` (local PostgreSQL and Redis started, variables injected, Procfile web + worker, services stopped properly, ports freed), `python-app` and `node-app` (HTTP 200, ports free initially),
and a monorepo `src/backend` + `src/frontend` (backend and frontend respond, no residual processes). One more test for the 0.24.2 served as a model: tests first, refactoring then, comparison finally.
**Remainder complex** (Rank D/E): `detect_node`, `detect_python`, `detect_rust` (32-35), `make_plan` (29), `dispatch` (25), `detect_stacks` (23), `node_satisfies` (23), `detect_go`, `entry_evidence`, `script_imports` (21-22), `run_stacks` (21).
These are cascades of detection rules well covered by the tests; their division would require an old/new comparison on the corpus of clones (≈ 25 min of cloning) to be sure.

## 0.24.4: simplified detectors and `make_plan`, with an old/new comparison on 298 repositories

**After a sandbox reset** (the working folder had disappeared; the repository was restored from the zip, 303 tests OK, 5 ignored due to lack of services), `detect_node`, `detect_python`, `detect_rust`, `detect_go` and `make_plan` were cut into
petites fonctions (`_node_version`, `_node_package_manager`, `_node_run` ; `_python_manifest`, `_python_install_steps`, `_python_run` ; `_rust_toolchain`, `_rust_run_from_bins`, `_rust_run_from_workspace` ; `_go_version`, `_go_run_from_cmd_dir` ;
`_note_multistack`, `_fill_missing_command`, `_apply_lock_or_registry`). Measured complexities (`radon`): `detect_node` 35 → 5, `detect_python` 35 → 12, `detect_rust` 32 → 8, `detect_go` 22 → 3, `make_plan` 29 → 10 ; the most complex of the new functions: 16 (`_go_run_from_cmd_dir`); no more rank E or F functions; **medium 5,77 (B)**.
**The safety net (excluding deposit, in `/tmp`, to be recreated if necessary)**: lightweight snapshots of 298 deposits (text files ≤ 100 KB of the types read by the detectors, without `.git` nor `node_modules`), the complete plan of each serialized by the code from before
(commit `716647b`, exported in `/tmp/ref_src`), then compared field by field after each refactoring. Deterministic measurement (two executions of the same code: 0 difference). **Result: 0 difference on 298 plans** (245 complete plans, 53 errors expected; 52 Go plans and 49 Rust plans exercised).
**Network flaw found by mutation and fixed**: my first version excluded lockfiles from snapshots, therefore the mutation `npm ci → npm install` was **not detected** (0 difference) while all branches that depend on the presence of a lockfile (`pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`, `uv.lock`, `bun.lock`…)
were never exercised. The lockfiles were recreated **empty** (only their existence matters; 1 273 files in 298 deposits); the same mutation is then detected on 46 deposits.
**Limitations**: the comparison calls `make_plan` with `use_lock=False`, so `_apply_lock_or_registry` is only covered by existing unit tests; snapshots do not contain files older than 100 KB nor types not listed; this net is not in the repository (disposable tool: `snap.py`, `locks.py`, `baseline.py` described above).
**Rank D remainder**: `dispatch` (25), `node_satisfies` (23), `detect_stacks` (23), `entry_evidence` (22), `script_imports` (21), `run_stacks` (21).

## 0.24.5: `detect_stacks`, `entry_evidence`, `script_imports` simplified (same net, 0 difference)

Three more D-rank functions, cut out: `detect_stacks` (23) → `_runnable`, `_conventional_stack_dirs`; `entry_evidence` (22) → `_docker_command_lines`, `_readme_code_lines`, `_entry_score` ; `script_imports` (21) → `_imported_modules`. Each compared to the oracle (commit `716647b`,
298 real plans): **0 difference**, with 7 plans with multi-stack note and 2 ambiguous multi-stack cases, 6 plans with entry point chosen by proof and 18 with remaining choices, 8 plans with inferred dependencies actually exercised. 303 tests OK, `pyflakes` clean.
Average project complexity: **5,68 (B)**. **Remains Rank D, unaffected**: `dispatch` (25, CLI), `node_satisfies` (23, semver ranges), `run_stacks` (21, launch `--all`): the oracle does not cover them (they are not called by `make_plan`);
existing tests partially cover them; refactoring them would require characterization tests written beforehand (method already applied to `install_deps` and `run_project`).

## 0.24.6: `node_satisfies` and `dispatch` simplified

- **`node_satisfies` (23 → 7)**: the elementary comparison becomes `_comparator_ok`. Pure function, therefore verified by an **exhaustive old/new comparison: 18 126 version × range pairs, 0 difference** (34 % of true results, therefore a sample that discriminates;
  159 ranges include operators, wildcards, `||`, invalid ranges, `None`), and `pick_node_major` the same on 159 ranges.
- **`dispatch` (25 → 10)**: a clear referral to `_cmd_doctor`, `_cmd_bench`, `_enable_sandbox`, `_cmd_all_stacks`, `_auto_all_stacks`, `_cmd_project`. **11 characterization tests written before** (which command calls what, with what options, what it displays, automatic switching to multi-stack and
  its cases of refusal), passed on the old then the new code; **4 mutations detected** (limit of 3 stacks removed, sandbox active for `plan`, arguments after `--` added after plan display, `--all` accepted with `--cmd`). Actual control via CLI: `plan` then `run` from `node-app` → HTTP 200 to 3000 (initially free ports), no residual processes.
314 tests OK (5 ignored in this sandbox due to lack of services), `pyflakes` clean. **Rank D remainder: `run_stacks` alone (21).**

## 0.24.7: Simplified `run_stacks`; no more rank D, E or F functions

`run_stacks` (mode `--all`, 21) is split into `_install_stacks`, `_shared_services` and `_wire_stacks` (ports, backend URL, service variables, migrations). Same method: **9 characterization tests written before** (installation by stack in its runtime, a service
by type for the entire repository, announced ports and URLs, service variables without overwriting the `.env` of a stack or the process environment, command keys, migrations, exit code, stopping services), passed on the old then the new code; two of my test hypotheses were wrong
(the process environment is part of the copied environment; without a service there is no manager): the tests now describe the real behavior. **4 mutations detected** (one service per stack instead of one per type, `.env` crashed, services not stopped, short interruption counted as success);
the “services not stopped” mutation had first mutated the wrong `finally` (that of `run_project`) and seemed to survive: redone on the good block, it was detected. Actual control: monorepo `src/backend` + `src/frontend`: backend on 8000, frontend on 3000 querying backend, ports and URLs advertised, no residual processes.
323 tests OK (5 ignored in this sandbox due to lack of services), `pyflakes` clean. **Review of the simplification (0.24.2 to 0.24.7): no function of rank D, E or F; average complexity 6,4 → 5,53 (B).** Method chosen: characterization tests or comparison to an oracle written **before**, refactoring afterwards, mutations to prove that the net detects, real control finally.

## Final verification of the simplification (without version change)

After resetting the sandbox, the suite was running with 5 tests ignored due to lack of services. Redis, PostgreSQL 16, MariaDB and bubblewrap have been reinstalled (the apt nodesource repository, blocked in 403, moved out of `sources.list.d`) and the complete suite replayed on 0.24.7:
**323 tests, ignored 0, all OK**, including actual integration tests (local MariaDB and PostgreSQL, Redis, bubblewrap containment, signals), and no residual processes. The refactorings of `install_deps`, `run_project`, `dispatch`, `run_stacks` and detectors are therefore also confirmed against real services.
