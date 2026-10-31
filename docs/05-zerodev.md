# ZeroDev

> **Catégorie** : environnement de développement auto-reproductible  
> **Ambition** : rendre tout dépôt Git exécutable avec une commande, sans configuration manuelle  
> **Horizon** : 1 à 3 ans  
> **Hook GitHub** : **git clone && zero.**

## 1. Vision

Aujourd’hui :

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

ZeroDev vise :

```bash
git clone repo
cd repo
zero
```

et le projet tourne.

## 2. Principe

Analyser automatiquement : `package.json`, `pyproject.toml`, `requirements.txt`, `Cargo.toml`, `go.mod`, Dockerfile, compose, Makefile, `.nvmrc`, `.tool-versions`, README, CI config et imports source.

Puis produire un plan : runtimes, DB, services, libs, env vars, ports, GPU requirements.

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

Backends possibles : Nix, Podman/containers, bubblewrap, system packages, language version managers.

## 4. V0

Support Node, Python, Rust.

`zero` doit détecter le langage/version, installer runtime isolé, installer dépendances, détecter la commande principale et lancer le projet.

## 5. V1

Databases, Redis, queues, workers, ports, `.env` templates, health checks, service graph.

## 6. V2 : zero freeze

```bash
zero freeze
```

Produit une définition reproductible avec runtimes, versions, deps, system libs, services, ports, env et besoins GPU.

## 7. V3 : zero share

```bash
zero share
```

Quelqu’un d’autre recrée exactement l’environnement.

Objectif : **works on my machine → here is my machine state.**

## 8. V4 : automatic recovery

Erreur process → diagnostics → hypothèse de dépendance → retry sandbox, avec changements toujours inspectables.

## 9. Registry facultatif

Fingerprint de repo → environnement connu fonctionnel, sans dépendance cloud obligatoire.

## 10. GPU / AI projects

Support CUDA, ROCm, Vulkan, model files, wheels GPU, llama.cpp, PyTorch, ComfyUI.

```bash
zero https://github.com/some-ai-project
```

## 11. Différence avec Docker

Docker suppose généralement que quelqu’un a déjà décrit l’environnement. ZeroDev tente de le **déduire à partir du repo**.

## 12. Différence avec “une IA écrit un Dockerfile”

ZeroDev doit rester déterministe, cacheable, testable, reproductible et inspectable. L’IA aide seulement dans les cas ambigus.

## 13. Problèmes de R&D

Versions, dépendances système implicites, services externes, secrets, vieux projets, CUDA, scripts install, monorepos, architectures CPU, docs fausses.

## 14. À ne pas faire

Pas d’IDE complet, cloud dev environment, SaaS, CI/CD, agent coding ou hosting au début.

Promesse initiale : **clone → zero → run.**

## 15. Benchmark public

Créer un corpus de 100, puis 500, puis 1000 repos publics. Mesurer détection, build, lancement, temps jusqu’au premier run et interventions humaines.

## 16. Démo GitHub

Trois repos très différents, dont un ancien : `zero` → ils tournent sans édition manuelle.

## 17. North Star

La section « Installation » des README devient progressivement inutile.
