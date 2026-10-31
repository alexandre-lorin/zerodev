# ZeroDev

> **git clone && zero.**

`zero` analyzes a Git repository, deduces its environment (runtime, version, dependencies, services, variables
of approx, GPU), installs it **in a sandbox under `~/.zero`** (nothing is installed on the system), then
launches the project.

```bash
git clone https://github.com/org/repo && cd repo
zero
```

Python ≥ 3.10, **no dependencies** (stdlib only). Linux and macOS. Languages: Node, Python, Rust, Go.

## Installation

Three ways, all without dependencies other than Python ≥ 3.10:

```bash
./bin/zero --help                 # 1. sans installation, depuis le dossier cloné
./install.sh                      # 2. commande `zero` pour l'utilisateur courant (~/.local/bin/zero ; le dossier doit rester en place)
python3 scripts/build_pyz.py      # 3. un exécutable unique dist/zero.pyz (63 Ko) : copiable ailleurs, ./zero.pyz run <dépôt>
pip install .                     #    ou : paquet pip (la commande `zero` ; la version vient du code)
```

`zero doctor` checks machine status (tools, Docker/Podman, GPU, network).

## Orders

| Order | Role |
|---|---|
| `zero [run] [cible]` | install + launch (default). Target: folder, git URL or bundle `.zeroshare.tgz` |
| `zero plan` | show plan without executing anything |
| `zero freeze` | write `zero.lock.json` (V2) |
| `zero share` | create bundle `<nom>.zeroshare.tgz` (V3) |
| `zero down` | stop services started by zero |
| `zero fingerprint` | repository fingerprint (registry key) |
| `zero bench corpus.txt [--full]` | benchmark on a corpus of repositories |
| `zero run --sandbox <dépôt>` | isolated installation and launch (bubblewrap on Linux, `sandbox-exec` on macOS — **not tested on a real Mac**): hidden `~`, read-only system, write limited to repository and `~/.zero`; non-isolated network. Refuse to continue if neither is usable |
| `zero run <dépôt> -- <arguments>` | everything after `--` is passed to the launched command (command line tools; npm: `--` inserted) |
| `python3 scripts/validate_machine.py` | **automatic validation on your machine**: synthetic repositories (Node, Python, Go, Rust, README, monorepos, etc.), real launch, HTTP probe, isolation; OK/KO/SKIP table + report without personal paths |
| `zero report [dépôt] [--no-network]` | **a single block to paste in a test return**: machine (doctor) + depot plan + latest automatic fixes; personal paths and username hidden, launches nothing |
| `zero doctor [--json] [--no-network]` | machine status: tools, Docker/Podman, local services, GPU, network access, disk (to be attached to a test return) |

Options:

| Options | Effect |
|---|---|
| `-p, --project DIR` | monorepo: start subproject `DIR` |
| `--all` | multi-stack: launch backend + frontend together (see below) |
| `--cmd "…"` | imposes launch command (when `zero` refuses to guess) |
| `--no-recover` | disables recovery V4 |
| `--no-services` | does not start V1 services |
| `--services auto\|container\|local` | where to start the services (default `auto`: container if podman/docker, otherwise local binaries) |
| `--no-lock` | ignore `zero.lock.json` and register |
| `--sandbox` | isolated installation and launch (bubblewrap on Linux, sandbox-exec on macOS), see the Security section |
| `-- <arguments>` | (after the target) arguments passed as is to the command launched |

**Principle: `zero` prefers to refuse than to guess wrong.** If there are several plausible entry points
(several `cmd/*` in Go, several Rust binaries, several subprojects of a monorepo), it lists them and
stops instead of randomly throwing: `zero --cmd "go run ./cmd/gh"` or `zero -p apps/web`.
Two exceptions, each with its limitations (see `docs/CHANGELOG.md`): an entry point is chosen only if it is
**the only one supported by proof** (`ENTRYPOINT`/`CMD` of a Dockerfile, target command of the README); a monorepo subproject is chosen only if it is **the only one targeted** by a `dev`/`start` script from the root `package.json` or by a `cd <dossier>` from a README code block **followed by a real launch command** (no test/lint) and without other launch command elsewhere in the README (without this, or equal, zero request `--project`); a monorepo of 2 or 3 stacks
of **different languages** (`backend/` + `frontend/`, also under `src/`, `app/`, `apps/`) is launched alone as with `--all`.
As a last resort (after the Makefile), zero takes a command to launch a block of code from the README **only if it is verified in the repository** (`python app.py` with `app.py` present, `uvicorn main:app` with uvicorn declared and `main.py` present, `streamlit run`, `flask run`, `node server.js`); placeholders, pipes, `cd` and tooling scripts (`scripts/`, `tests/`, `migrate.py`, `reset-admin.js`…) are discarded, and the plan reports the deduction.
The plan always says where an order or deduced version comes from.

## Environment variables

| Varies | Effect |
|---|---|
| `ZERO_HOME` | zero working folder (default `~/.zero`: runtimes, environments, services, logs) |
| `ZERO_REGISTRY` | shared register (read/write folder, or read `https://…`) |
| `contrib/zero-container.sh <dépôt>` | launches zero **in a container** podman/docker (stronger isolation than `--sandbox`, especially under macOS) — written but **never executed with a real Docker**: see `docs/CONTAINER.md` |
| `ZERO_NO_RUNTIME_HINT=1` | does not use the version derived from Dockerfile/CI (falls back to default) |
| `ZERO_BENCH_CLEANUP=1` | benchmark `--full`: removes clone, venv and caches after each repository and monitors the disk |
| `PORT` | if defined (environment or `.env`), zero does not assign a port to this stack |

## Architecture

```
Repository → Detectors → Dependency/Env Planner → Resolver → Sandbox Runtime → Services → Process Supervisor
              plan.py        core.py (make_plan)   runtimes.py   ~/.zero          services.py   supervisor.py
```

| Module | Content |
|---|---|
| `plan.py` | Node / Python / Rust / Go detectors, monorepos, Procfile, detection of AI libs |
| `runtimes.py` | Node (official tarball, npm fallback, pnpm/yarn shims), Python (uv), Rust (rustup), Go (go.dev), all isolated |
| `services.py` | Postgres, MySQL, Redis, MongoDB, RabbitMQ: detection, podman/docker containers, health checks, `.env` |
| `localsvc.py` | fallback without container: `redis-server`, `postgres` (initdb + base `app`), MySQL/MariaDB, `mongod`; takes the identifiers of the compound |
| `supervisor.py` / `procs.py` | multi-process (Procfile), prefixed logs, clean shutdown; Linux subreaper that adopts and stops daemons |
| `report.py` | `zero report`: try return block with hiding home folder and username |
| `sandbox.py` | `--sandbox`: bubblewrap (Linux) or sandbox-exec (macOS) around installation and launch |
| `doctor.py` | `zero doctor`: machine status |
| `recovery.py` | V4: diagnostic → fix → retry, logged |
| `freeze.py` / `share.py` | V2 / V3 |
| `registry.py` | optional register |
| `gpu.py` | CUDA / ROCm / Vulkan / Metal, model files |
| `bench.py` | public benchmark |

## What each version does

**V0** — detects language and version (`.nvmrc`, `.node-version`, `.python-version`, `runtime.txt`,
`rust-toolchain(.toml)`, `.tool-versions`, `engines`, `requires-python`), installs an isolated runtime,
install dependencies (npm/pnpm/yarn, uv, cargo), guess main command, run.

**V1** — services inferred from `docker-compose`, dependencies and `.env.example`; started in containers
(free port if the default port is taken); health check TCP; Injected URLs (`DATABASE_URL`, `REDIS_URL`…);
`.env` created from the template (secrets generated, values ​​to be provided listed); `Procfile` (web, worker, release).
An existing `.env` is never overwritten, and its variables are not overridden.

**V2 `zero freeze`** — `zero.lock.json`: runtime and exact version, package manager, services (image,
port), env keys (never values), ports, cited system packages (Dockerfile, CI, README), GPU requirements,
hashes of manifests. On the next run, the version is pinned and the drift is reported.

**V3 `zero share`** — bundle = code (tracked/not skipped files) + lock + template of approx. The Secrets (`.env`,
`*.pem`, `*.key`, `.npmrc`…) are never shipped. The recipient does `zero projet.zeroshare.tgz`.
Bundles are validated upon extraction (no path outside destination).

**V4 recovery** — error → deterministic rules → fix → restart (4 attempts at launch, 8 turns to
installation; each fix is attempted only once): missing Python/Node module (installed in the isolated environment, with
alias table `cv2→opencv-python`…), busy port (free `PORT`), and, added version after version (detail and measurements in
`docs/CHANGELOG.md`): fallback of the Python version (3.13/3.9/3.8 depending on the error or the wheels available), psycopg2 → binary,
Python server missing (`gunicorn`…), `pip install -e .` optional, version caps for old APIs (Jinja, Werkzeug,
SQLAlchemy, WTForms…), copying a configuration template (`local_settings_example.py`), `npm ci` → `npm install`, scripts
installation files ignored, pnpm 10+ (`strict-dep-builds`), corepack via the npm registry, version imposed for setuptools-scm,
Django migrations. Missing system tools/libraries and variables: **never applied automatically**, shown as
manual action. Each patch is displayed and logged (`~/.zero/logs/<projet>.jsonl`). No AI in the loop.
Last resort fixes may deviate from the lockfile or repository: the plan and the log say so.

**Go** — `go.mod` (`toolchain`, `go`), `.go-version`, `.tool-versions` ; `go run .` if a `package main` is
root, otherwise `go run ./cmd/<nom>` when the name corresponds to the repository/module (`/vN` suffix ignored) or there is none
that one; otherwise explicit refusal. Runtime downloaded from go.dev (fallback: System Go).

**Monorepos** — if the root has no commands, `zero` searches for executable projects (depth ≤ 2). Only one
→ he throws it; several → it lists and asks `--project`. It does **not** go down into a subfolder when the
root is already recognized (Go library), when it is Ruby/PHP/Java (the `package.json` is only from the front), neither
when it contains `.py` scripts without manifest: zero then deduces the dependencies of `import` and offers the scripts as entry points
(the subproject remains accessible by `--project`).

**Non-container services** — without podman/docker (or with `--services local`), `zero` starts local binaries:
`redis-server` (ephemeral), `postgres` (cluster initialized with `initdb`, user `zero`, base `app`, data
**kept** in `~/.zero/services/<projet>/postgres`), `mongod`, `mariadbd`/`mysqld` (MariaDB or MySQL; user `root`, password `zero`, database `app`, data
**kept** in `~/.zero/services/<projet>/mysql`). It looks for binaries in the PATH then in the
usual locations (Debian `/usr/lib/postgresql/*/bin`, Homebrew, Postgres.app, RHEL). Under root, PostgreSQL is executed
via `runuser -u postgres` (it refuses to run as root). Clean stop at exit. **RabbitMQ has no fallback
local**: without container, `zero` reports this. Tested in real: Redis, PostgreSQL 16 and **MariaDB** (creation, restart with
data retention, clean shutdown). Not tested here: `mongod` and MySQL from Oracle (same commands, variant `--initialize-insecure`).

**Multi-stack (`--all`)** — a repository with at least two *different* executable languages (root, `backend/`,
`frontend/`, `server/`, `client/`, `api/`, `web/`, `app/`, `ui/`, `worker/`) is indicated in the plan. `zero --all`:
installs each stack in its own runtime, shares **a single** set of services (one Postgres for the entire repository),
plug in the `.env` of each stack and run everything under a supervisor, with logs prefixed by stack:

```
backend | backend ready on :8000
frontend| frontend ready on :3000 (backend : http://localhost:8000)
```

Without `--all`: if the root has no commands and there are 2 or 3 different language stacks (also under `src/`, `app/`, `apps/`),
zero launches alone as with `--all`; if the root already has a command, it only throws one side and says it. A root of the same language as a subfolder is ignored
(it is an orchestrator: the JS workspace which launches `frontend/` must not start the frontend twice).
In `--all` mode, automatic launch recovery is not applied (the installation phase is).
Each stack receives a separate `PORT` (3000 Node, 8000 Python, 8080 Go/Rust, incremented if busy), unless `PORT` is
already defined in the environment or `.env` of the stack. Programs that ignore `PORT` keep their default port.
If the repository has a stack `backend`/`server`/`api` (with a `PORT` assigned by zero) and a stack `frontend`/`client`/`web`/`ui`/`app`,
frontend receives url from backend in `BACKEND_URL`, `API_URL`, `VITE_API_URL`, `VITE_BACKEND_URL`, `NEXT_PUBLIC_API_URL`
and `REACT_APP_API_URL` (without overwriting the environment or `.env`). It is a convention: it only has effect if the
frontend reads one of these variables and the backend reads `PORT`. Verified only on `examples/multistack-app`.
If one stack stops, the others are stopped.

**Install Recovery** — if a dependency requires a Node version newer than `.nvmrc`
(pnpm `ERR_PNPM_UNSUPPORTED_ENGINE`, yarn “incompatible”), `zero` upgrades version in the sandbox and tries again
once, without touching the deposit.

**Optional register** — after a successful run, the environment is registered by fingerprint in
`~/.zero/registry`. `ZERO_REGISTRY=/chemin/partagé` (write/read) or `https://…` (read) to share.
Local by default, no cloud required.

**GPU / AI** — torch detection, tensorflow, jax, llama-cpp-python, vllm…, `uv pip --torch-backend=auto`
(CUDA/ROCm/CPU), `CMAKE_ARGS` for llama.cpp, warning about download models.

## Security

- A lock or registry entry **only pins versions**: commands are always recalculated
  from the repository, so a malicious lock cannot inject a command.
- `zero run` executes the repository scripts (npm install, build.rs, setup.py…): like `git clone` + install
  manual, only run it on code you trust. `~/.zero` environment isolates versions
  and dependencies, **not** privileges (this is not a security container): to limit the damage of a questionable project, see `--sandbox` below.

**`--sandbox` mode** (Linux: bubblewrap; macOS: `sandbox-exec`, profile generated by `sandbox.seatbelt_profile`, **never launched on a real Mac**): the home folder is hidden (SSH keys, tokens, invisible browser profiles), the system is
read-only, writing is limited to the repository, `~/.zero` and a private `/tmp`, processes are isolated (PID/IPC). **The network is not
isolated** (a development server must remain reachable; the repository code can therefore issue requests) and the system's readable files
(`/etc`, `/usr`) remain readable. This is damage limitation for a dubious project, **not a guarantee** against code that would exploit the kernel.
On macOS, the profile denies writing outside repository/`~/.zero`/temporary folders and reading the home folder, but offers neither private `/tmp` nor PID/IPC namespace; `sandbox-exec` is deprecated by Apple. Without a usable backend, `--sandbox` refuses to launch rather than running unprotected.

## Benchmark

> **Figure to remember: 57,5 % of deposits with a detected order (473 on 823), including 53,5 % without any last heuristic
> recourse** (440 on 823; the rest comes from the Makefile, proof of the README/Dockerfile or deduced imports, all trusted
> weaker). Measuring code 0.20 on 1000 GitHub repositories selected by a fixed rule (`benchmark/corpus.public500.txt`+
> `corpus.public500b.txt`, detection only, 176 large deposits ruled out; 823 evaluated). The lower 71,9 % and 67,6 % come from selected corpora or
> adjusted by hand and **overestimate by around fifteen points**. In real launch, on a few dozen repositories deemed “executable”,
> about **one in four** actually serve an HTTP page (many are command line tools or libraries). Details and limitations: `docs/CHANGELOG.md`.

```bash
zero bench benchmark/corpus.public.txt                     # détection seule (rapide, 96 dépôts réels)
zero bench benchmark/corpus.sample.txt --full --timeout 90 # build + lancement réels
GITHUB_TOKEN=… python benchmark/build_corpus.py --per-query 100   # générer un corpus de 500–1000 dépôts
```

Each repository receives a status: `runnable` (command found), `no_run_command` (library…),
`ambiguous_entrypoint`, `ambiguous_monorepo`, `unsupported`, `clone_failed`.

### Results measured

**Detection on 96 real public repositories** (`benchmark/results/public-v3.json`) — *no code executed*:

| Status | Deposits | Meaning |
|---|---:|---|
| `runnable` | 69 | a launch command was found |
| `no_run_command` | 13 | libraries or collections: **correct refusal** |
| `ambiguous_entrypoint` | 4 | several plausible binaries: `zero` list and request `--cmd` |
| `ambiguous_monorepo` | 4 | several subprojects: `zero` list and request `--project` |
| `unsupported` | 6 | Java, PHP, Ruby, C, Python without manifest… |
| `clone_failed` | 0 | — |

“Order found” rate: **72 %** (69/96). By language detected:
python 17/19 · node 21/26 · rust 17/22 · go 14/19 · out-of-scope/ambiguous 10.

**Actual launch on 5 small repositories** (`benchmark/results/live-v1.json`, sandbox without containers but with local redis and postgresql):

| Deposit | Result | Detail |
|---|---|---|
| streamlit/streamlit-example | ✅ starts | without intervention |
| typicode/json-server | ✅ starts | without intervention (after correction of the PATH pnpm) |
| nestjs/typescript-starter | ✅ starts | 1 automatic fix: port 3000 busy → restart with `PORT=8000` |
| sveltejs/realworld | ✅ starts | 1 automatic fix: `.nvmrc` says Node 20, a dependency requires ≥ 22.12 |
| miguelgrinberg/microblog | ✅ starts | without intervention, with local Redis fallback (gunicorn + worker). **Before fallback: ❌** (no containers in this sandbox) |

**5/5** starts, but read the condition: `redis-server` was installed locally for this test (I installed it
myself with apt). Without a container or local Redis, microblog fails as before. This test **found 3 bugs from `zero`** (pnpm missing from the PATH at launch, Node fallback on a tag
npm non-existent, no recovery during installation): all fixed. 5 deposits, this is a demonstration,
not a statistic.

### How to read these numbers

- **“runnable” means “a command has been guessed”, not “it starts”.** Only `--full` measures the start.
- The corpus of 96 repositories was **hand-picked** (the search API was not usable without a token). He
  is deliberately varied (apps, CLI, monorepos, libraries, languages outside scope) but not random:
  don't present it as a representative sample of GitHub.
- A status `no_run_command` on a library (requests, click, axum) is **correct**, not a failure.
- The rate went from 86% to 72% in two successive manual audits of the detector: each time,
  False orders inflated the figure. Audit 1: Ruby/PHP taken for Node, `go run ./cmd/gen-docs`, an example
  randomly among dozens, descent into `ui/`. 2 audit: the Node libraries file `main` (express,
  fastify, koa) launched as a program, syncthing `build.go` (`//go:build tools`) taken for binary, a
  `template/base` taken for the project, `--bin fd-find` instead of `fd`. Lowering the number was the right decision.
- **An audit stops when you stop looking**: I reread the 74 commands by hand, not the ~20 000 of a
  corpus of 1000 repositories. Expect more false positives on a larger scale.
- `benchmark/results/public-v3.json` contains the detail by deposit.

### Out-of-sample corpus (`benchmark/corpus.heldout.txt`)

39 repositories **never used to tune heuristics** (report: `benchmark/results/heldout-v1.json`):
25 “executables” on cloned 37 (**67,6 %**), against 71,9 % on the hand-tuned corpus: the difference is small,
but the lot is small. Manual rereading of 25 commands (judgment, **without having launched them**):

- 16 are real programs: 6 Rust binaries, 6 Go binaries, Home Assistant (`hass`), Docusaurus, husky, fastify-cli.
- 9 are questionable: libraries or tools that require arguments, or `dev` scripts that only monitor
  a build (gradio, pelican, mkdocs, fastapi, flask, weasyprint, next.js, vuejs/core, astro).
- 1 false positive corrected: `etcd` (Procfile `goreman` targeting `bin/etcd`, which only exists after compilation); a
  Procfile that references a missing local executable is now ignored.

Estimated “really useful order” rate: approximately 16/37 (≈ 43%), much lower than the gross rate. Do not quote 72 %
without this nuance.

### Old projects (§13 of the specification) — real tests

`benchmark/results/live-v2-old-repos.json`: 4 old/Heroku repositories launched for real in a sandbox (not a statistic):

| Deposit | Result |
|---|---|
| heroku/node-js-getting-started | launched, without intervention |
| heroku/python-getting-started | launched, **HTTP 200 checked** (Django, Python 3.14) after 3 fixes: comment in `.python-version`, IPv6 unavailable, `collectstatic` |
| miguelgrinberg/flasky (2017) | installed and started after automatic patches; stops on `SERVER_NAME` (configuration to be provided) |
| mdn/express-locallibrary-tutorial | installed; requires a MongoDB (not in the sandbox) |

Second batch (`benchmark/results/live-v3-batch2.json`, 6 repositories, local Redis/Postgres): **5 launched on 6**.
“Launched” = process still alive at the end of the delay, without HTTP verification (except `python-getting-started`, verified by curl).
Only failure: `sahat/hackathon-starter`, which requires MongoDB (`mongod` not available here). Actual bug found and fixed:
`runtime.txt` pins Python `3.8.1`, which `uv` does not offer (it only keeps the latest patch of each
minor version) → automatic fallback to `3.8`.

Added automatic fetches (all logged in `~/.zero/logs/<projet>.jsonl`, repository never modified):
- **Python scale**: `imp`/`distutils`/`six.moves` → Python 3.11; `getargspec` → 3.10 ; aka `collections.*` → 3.9. Each level only once; the environment is recreated.
- **psycopg2** without libpq (`pg_config`) → `psycopg2-binary` in a temporary requirements (`-r` developed), then without the pin if no binary exists for this version.
- `pkg_resources` → `setuptools<81`.
- **Python version not found** (`3.8.1`) → same minor version (`3.8`).
- **IPv6 unavailable** (Docker, certain sandboxes) while `gunicorn.conf.py` links `[::]` → `GUNICORN_CMD_ARGS="--bind 0.0.0.0:<port>"` (priority over the config file).
- **Django + `STATIC_ROOT`**: `collectstatic --noinput` is added to the installation steps (otherwise HTTP 500 “Missing staticfiles manifest entry”).
- **Fatal error of a server remaining alive** (gunicorn restarts its workers in a loop): the supervisor treats it as a failure to trigger recovery.
- **Signals**: `SIGINT` and `SIGTERM` properly stop `zero` and its children, even launched with `SIGINT` ignored (non-interactive shell). This fixed a real bug: the `--full` benchmark left orphaned processes.
No “old” version is guessed without symptoms: without errors, the default version remains the most recent.

## Demo

`./demo-real.sh`: three real public repositories (Node, Python/Django, Flask + Redis + PostgreSQL), launched then probed in HTTP with a verdict (network required; see `docs/VALIDATION.md`). Then:
`./demo.sh`: five very different repositories (Node, Python with forgotten dependency, Procfile + services, Rust, and the
multi-stack launched with `--all`).

## Tests

```bash
python -m unittest discover -s tests -v     # ~185 tests, sans réseau ; des tests d'intégration réels (redis, postgres, mariadb) s'ignorent s'ils sont absents
```

## Known limits

- Libraries with console_script and Python repositories with a tooling `package.json` (e.g. gradio) can be wrongly counted "executable" (known framework CLIs which only display their help are discarded; a quick output which displays a usage gives the message "command line tool").
- **Multi-stack repositories**: without `--all`, `zero` launches the first runnable ecosystem (Node > Python > Rust > Go)
  and reports it. With `--all`, only conventional folders (backend, frontend, server, client, api, web, app,
  ui, worker) are explored: a stack named differently (`packages/api`, `client/` in a sub-subfolder)
  is not found. On the public corpus, detection offers 3 multi-stack deposits on 96 (mealie,
  full-stack-fastapi-template, gogs); **the `--all` launch was only verified on the example provided**,
  not on these real deposits (they require services and time).
- Ports: in `--all`, zero assigns separate ports (`PORT`) and gives the backend URL to the frontend; an app that ignores `PORT` may still conflict.
- Python: `requirements/<base|common|main|…>.txt` is recognized; for repositories ordered by hardware variant (`requirements/full/requirements_cpu_only.txt`, `_amd`…), zero chooses according to the hardware detected (never tested on a real GPU). Without any manifest, dependencies are inferred from `import` (assumed PyPI name).
- No Java, Ruby, PHP, .NET (detected as `unsupported`, without throwing anything false).
- Services: container (podman/docker) or local binaries for Redis, Postgres, MySQL/MariaDB and MongoDB. RabbitMQ
  requires a container; without it `zero` reports it and continues (the project will probably fail to connect).
  Container images could not be tested here (no podman/docker in my sandbox).
- Local Postgres: `trust` authentication on 127.0.0.1 only, designed for development, never for exposing
  a base.
- AI models are not downloaded.
- No native Windows.
- The `--full` benchmark (real launch) was run on over a hundred repositories, in small samples in a sandbox, not on
  hundreds at once: it launches arbitrary third-party code and requests a dedicated machine (and disk space: `ZERO_BENCH_CLEANUP=1`).

## Documentation

- `docs/05-zerodev.md`: original specification.
- `docs/CHANGELOG.md`: versions and measurements log (0.10.2 → today), with their reservations.
- `benchmark/README.md`: corpus, result files and how to read them (reservations included).
- `docs/VALIDATION.md`: checklist to run on a real machine (Docker/Podman, macOS, demos, Oracle MySQL).
