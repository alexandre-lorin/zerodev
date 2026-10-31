# Benchmark ZeroDev: corpus, results, how to read them

`zero bench <corpus.txt>` clones each repository, calculates the plan and classifies the result (**detection only**, nothing is launched); with `--full` it actually launches each
deposit (arbitrary third-party code: see `docs/VALIDATION.md` before doing it at home, and `ZERO_BENCH_CLEANUP=1` to clean the disk).

## What the fields measure
- `status` (detection): `runnable` (an order is found), `no_run_command`, `ambiguous_entrypoint`, `ambiguous_monorepo`, `unsupported`, `clone_failed`, `detector_error`.
  **A command found is not a fair command, nor one that starts.** `run_inferred` / `entry_from_docs` / `deps_deduced` mark last resort heuristics (Makefile, README/Dockerfile proof,
  imports deducted); the “strict” rate excludes them.
- `phase` (real launch): `install_failed`, `install_timeout`, `run`, `disk_full`; `built` = installation completed and launch started; `launched` = a process is still alive at the end of the timeout;
  `http` = a port listening in the process tree responded in HTTP (any code: a 404 or a 401 counts as "responds"); `cli_tool` = displayed help and exited.
- `--full` reports are saved after each deposit (`"partial": true` if the benchmark was interrupted).

## Corpus
| File | Content | Nature |
|---|---|---|
| `corpus.sample.txt` | 5 example entries | examples of the repository |
| `corpus.public.txt` | 96 public repositories | **chosen by hand** (and adjusted to them: overestimates the detection by around fifteen points) |
| `corpus.heldout.txt` | 39 deposits | hand-picked, excluding tuning sample (a little less optimistic) |
| `corpus.public500.txt` / `corpus.public500b.txt` | 500 + 500 deposits | **fixed rule** (GitHub API, `language:<L> stars:<lo>..<hi> archived:false`, sort by update, 100 by language python/javascript/typescript/go/rust): batch 1 = 500..3000 stars, batch 2 = 100..499 ; reproducible with `build_corpus_rule.py` (results depend on execution date) |
| `corpus.demo.txt` | 3 deposits | the demo of `demo-real.sh` |
| `build_corpus.py` | historical generator by theme (webapp, cli, bot, etc.) | not used for the corpora above; requests a token for large volumes |

Deposits of more than 300 MB (API size, complete history): discarded during evaluation (176 on 1000: 98 + 78), so the measurements mainly describe lightweight applications.

## Detection results (`results/`)
| File | Corpus, code | Result |
|---|---|---|
| `public-v3.json` | Handmade 96, ~0.9 | 69/96 = 71,9 % |
| `public-v4.json` | same remeasured, ~0.12 | 68/96 = 70,8 % (`pallets/flask` excluded on purpose) |
| `heldout-v1.json` / `heldout-v2.json` | 39 out of sample, 0.9.1 then ~0.12 | 25/37 then 24/37 cloned |
| `public500-v1.json` | lot 1, code 0.12 | 214/402 = 53,2 % |
| `public500b-v1.json` | batch 2, code 0.12 | 240/422 = 56,9 % |
| `public1000-remeasure-v0.20.json` | **the 823 deposits of the two batches, code 0.20** | **473/823 = 57,5 %**, including 53,5 % without last resort heuristic (**figure to remember**) |

## Actual launch results (`results/live-*.json`): small samples, do not extrapolate
| File | Content | Reserve |
|---|---|---|
| `live-v1`, `live-v2-old-repos`, `live-v3-batch2`, `live-v4-http-probe`, `live-v5-batch3`, `live-v5b-microblog-with-services`, `live-v6-bun`, `live-v7-batch4`, `live-v8-batch5`, `live-v9-batch6` | successive tests from 2 to 8 repositories (versions 0.8 to 0.11), repositories chosen by hand then by the API | historical; this is where most fixes come from (see `docs/CHANGELOG.md`) |
| `live-v10-sample500.json` | drawing 22 “executable” repositories from batch 1 (Node/Python) | **fragile**: the sandbox disk has become full, 4 clones lost; first print |
| `live-v11-sample2.json` | 16 repositories (7 seed) | without disk incident |
| `live-v12-sample3.json`, `live-v13-sample3-replay.json` | 24 repositories (seed 11), then replay of the same after fixes | v13: before/after on the **same** sample, therefore not independent; `wind-comic` was replayed there alone (full disc) |
| `live-v14-sample4-node.json` | 22 Node repositories (23 seed) | the most independent (no fixes designed on it); 2 unrated (disk) |
| `live-v15-slow6-240s.json` | 6 large monorepos replayed with a delay of 240 s | 75 insufficient time before |
| `live-v16-old-repos-20.json` | 20 old repositories (latest commits 2015-2018), §16 | 2 respond using HTTP |
| `live-v17-starters.json` | 16 starters (Next, Vite, Django, Flask), **second pass** after fixes | first pass report lost |
| `live-v18-python-replay.json` | 10 Python repositories that had failed, replayed | same set as previous prints: not independent; low gain |
| `live-v19-runtime-hint-ab.json` | A/B with and without version inferred from Dockerfile/CI, same 13 repositories | 12 same, 1 worse (fixed), 0 better |

**Order of magnitude to remember: approximately one in four "executable" repositories serves an HTTP page** (many are command line tools, libraries, or require a terminal/screen).
Don't compare two files without looking at the version of the code that produced them (`docs/CHANGELOG.md`); the clones are those of the day of the measurement, the deposits evolve (a script `dev` deleted
is enough to change a repository from "executable" to "no command").
