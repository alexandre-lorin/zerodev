# ZeroDev

> **Category**: self-reproducible development environment  
> **Ambition**: make any Git repository executable with a command, without manual configuration  
> **Horizon**: 1 to 3 years  
> **Hook GitHub**: **git clone && zero.**

## 1. Vision

Today:

```text
clone repo
↓
wrong Node
↓
missing Python
↓
wrong CUDA
↓
DB missing
↓
.env ???
↓
Redis
↓
FFmpeg
↓
README outdated
```

ZeroDev aims:

```bash
git clone repo
cd repo
zero
```

and the project is running.

## 2. Principle

Automatically scan: `package.json`, `pyproject.toml`, `requirements.txt`, `Cargo.toml`, `go.mod`, Dockerfile, compose, Makefile, `.nvmrc`, `.tool-versions`, README, CI config and imports source.

Then produce a plan: runtimes, DB, services, libs, env vars, ports, GPU requirements.

## 3. Architecture

```text
Repository
    ↓
Detectors
    ↓
Dependency Graph
    ↓
Environment Planner
    ↓
Resolver
    ↓
Sandbox Runtime
    ↓
Services
    ↓
Process Supervisor
```

Possible backends: Nix, Podman/containers, bubblewrap, system packages, language version managers.

## 4. V0

Support Node, Python, Rust.

`zero` should detect language/version, install isolated runtime, install dependencies, detect main command and launch project.

## 5. V1

Databases, Redis, queues, workers, ports, `.env` templates, health checks, service graph.

## 6. V2: zero freeze

```bash
zero freeze
```

Produces a reproducible definition with runtimes, versions, deps, system libs, services, ports, env and GPU requirements.

## 7. V3: zero shares

```bash
zero share
```

Someone else recreates the environment exactly.

Objective: **works on my machine → here is my machine state.**

## 8. V4: automatic recovery

Process error → diagnostics → dependency hypothesis → retry sandbox, with changes always inspectable.

## 9. Optional registry

Repo fingerprint → functional known environment, without mandatory cloud dependency.

## 10. GPU / AI projects

Support CUDA, ROCm, Vulkan, model files, wheels GPU, llama.cpp, PyTorch, ComfyUI.

```bash
zero https://github.com/some-ai-project
```

## 11. Difference with Docker

Docker generally assumes that someone has already described the environment. ZeroDev attempts to **infer it from the repo**.

## 12. Difference from “an AI writes a Dockerfile”

ZeroDev must remain deterministic, cacheable, testable, reproducible and inspectable. AI only helps in ambiguous cases.

## 13. R&D issues

Versions, implicit system dependencies, external services, secrets, old projects, CUDA, install scripts, monorepos, CPU architectures, fake docs.

## 14. What not to do

No full IDE, cloud dev environment, SaaS, CI/CD, agent coding or hosting at the start.

Initial promise: **clone → zero → run.**

## 15. Public benchmark

Create a corpus of 100, then 500, then 1000 public repositories. Measure detection, build, launch, time to first run and human interventions.

## 16. GitHub demo

Three very different repos, including an old one: `zero` → they run without manual editing.

## 17. North Star

The “Installation” section of the README gradually becomes useless.
