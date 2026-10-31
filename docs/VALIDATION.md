# Validation on a real machine

What the development sandbox could **never** check: Docker/Podman, macOS, MySQL
of Oracle, and demos with full Internet access. Each step gives the command, the
expected result and what to note in case of deviation. Expect ~20 min. Prerequisites: Python ≥ 3.10, git.

Note for each step: OK / KO, OS and architecture (`uname -sm`), `zero --version`, and
paste the end of the exit in case of KO.

## Before you start: the condition of your machine

    ./bin/zero doctor > doctor.txt # system, tools, Docker/Podman, local services, GPU, network access, disk

Simpler, **a single command for the entire return**: `./bin/zero report <votre-dépôt> > retour.txt` (machine + depot plan +
latest fixes, hidden home paths; reread it before sharing), then complete the last line (“what happened”).

Otherwise, attach `doctor.txt` to your return (no personal data: no machine name or address; only
system user, tool versions and free space). `./bin/zero doctor --json` gives the same thing in JSON.

## Fastest: automatic validation

    python3 scripts/validate_machine.py --out validate-report.txt

Creates small synthetic repositories (Node, Python, **Go, Rust**, README alone, monorepos, Ruby…), launches zero on them, probes the HTTP and prints
`OK` / `KO` / `SKIP` by verification (including `--sandbox`, home folder isolation and container if the image exists). He only throws this
which he himself creates; the written report hides the personal file. The `go` and `rust` checks never worked for the author. The steps
below are still useful for what the script doesn't cover (demos on real repositories, services, MySQL).

## 0. Installation and testing (any machine)

    git clone <your copy> && cd zerodev # or unzip zerodev.zip
    ./bin/zero --version # expected: zerodev <version> (that of the cloned zip or folder)
    ./install.sh # optional: installs the `zero` command in ~/.local/bin
    python3 -m unittest discover -s tests # expected: OK (tests can be skipped
                                                # if redis-server / postgres / mariadb are absent)

## 1. Built-in demo (≈ 2 min, network to download Node/Python/Rust)

    ./demo.sh

Expected: 5 examples start, each is stopped after 15 s, without Python error.
On macOS: note the first example that fails (runtime download, `uv`, `cargo`).

## 2. Demo with real repositories (spec §16)

    ./demo-real.sh # ≈ 4 min: launches one after the other

Three very different repositories (Node; Python/Django; Flask + Redis + PostgreSQL) are cloned,
launched, probed in HTTP then stopped. Expected: three lines “OK HTTP 200…” and
“3/3 repositories respond over HTTP without manual editing” (exit code 0). The third
(`microblog`) needs Redis and PostgreSQL: containers if Docker/Podman, otherwise binaries
premises; without either it stops with a message ("FAILURE"), which is worth noting.
The details are in the `log.txt` / `report.json` files indicated in the last line.

## 3. Containers (Docker or Podman)

    docker --version # or podman --version
    ./bin/zero run --services container examples/fullstack-app

Expected: a `zero-…` Redis/PostgreSQL container starts, the app connects to it, and when stopped
(Ctrl-C) `docker ps` no longer displays a `zero-…` container. Please note: if the container remains alive,
the port, and the output of `docker ps`.

## 4. Local services (without container)

Install at least one server (Linux: `apt install redis-server postgresql`; macOS:
`brew install redis postgresql@16`), then:

    ./bin/zero run --services local examples/fullstack-app

Expected: "postgres ready", "redis ready", the app starts, and nothing remains after Ctrl-C
(`pgrep -fa "postgres -D|redis-server"` empty). On macOS, note if `initdb` is found
(Homebrew paths `/opt/homebrew/opt/postgresql@*/bin`).

## 5. Local MySQL/MariaDB

MariaDB has been tested; **Oracle's MySQL never**. With one of the two installed:

    python3 -m unittest tests.test_zerodev.TestRealMysqlCompose -v

Expected: OK (and not “skipped”). If Oracle MySQL: note the version (`mysqld --version`) and
possible initialization error (`--initialize-insecure`).

## 5 bis. Isolation `--sandbox` (Linux: bubblewrap; macOS: sandbox-exec)

    ./bin/zero run --sandbox examples/node-app

Expected under Linux with bubblewrap (`apt install bubblewrap`): the line “isolated mode (bubblewrap)” then the example
which responds using HTTP. Without bubblewrap, or if the kernel disallows user namespaces, **zero should refuse to
launch** with a clear message (never run without protection).

**Under macOS** (0.25.0, never launched on a real Mac): `zero doctor` should display “sandbox-exec (macOS) usable”; then
`./bin/zero run --sandbox examples/node-app` should show "isolated mode (sandbox-exec)" and the example should respond over HTTP.
If the installation or launch fails with "Operation not permitted", paste the exact line: the profile is too strict
(the tool in question — nvm, Homebrew, `~/Library`… — should be added to the authorized readings). Also check that a repository that attempts
reading `~/.ssh` or writing to `~` fails: `./bin/zero run --sandbox --cmd "cat ~/.ssh/id_rsa" <dépôt>` should not display anything.
Checked so far on only one kernel: note yours (`uname -r`) and if `zero doctor` shows "usable bubblewrap".

## 6. A deposit of yours

    ./bin/zero plan <folder or git URL> # display the plan without launching anything
    ./bin/zero run <folder or git URL>
    ./bin/zero run --sandbox <folder or git URL> # if the repository is unfamiliar to you (Linux)

Note: detected command vs actual command, first error, and whether an automatic fix
(“automatic fix:…”) has been applied. This is the most useful test for the future.

## 7. Option: real benchmark (small)

    ZERO_BENCH_CLEANUP=1 ./bin/zero bench benchmark/corpus.demo.txt --full --timeout 120 --out /tmp/bench.json

Runs the demo 3 repositories and writes a report; `ZERO_BENCH_CLEANUP=1` deletes each clone and its dependencies afterwards.
Expected: a summary with `launched` and `http_ok`. Attach `/tmp/bench.json` if possible. **Do not use large corpora**
(`corpus.heldout.txt`, `corpus.public*.txt`) with `--full` on your machine: they run dozens or hundreds of repositories
third party (hours, several GB, arbitrary code); they are used for detection only (without `--full`).

## Return model to send back to me

    zero doctor: (paste doctor.txt)

    0. unit tests: OK / KO (n tests, ignored?)
    1. demo.sh: OK / KO — first failed example:
    2. demo-real.sh: x/3 — pasted “OK/FAIL” lines:
    3. containers: OK / KO / not tested (docker or podman?) — container remained alive? :
    4. local services: OK / KO / not tested
    5. MySQL / MariaDB: OK / KO / not tested (which one?)
    5b. --sandbox: OK / clear refusal / KO — kernel (uname -r) or macOS (sw_vers):
    6. my repository: URL or name, command detected vs real, first error, automatic fix applied?
    7. real benchmark: (optional) attach /tmp/bench.json

One line per step is enough; in case of KO, paste the last 30 lines of output.
