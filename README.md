# ZeroDev

**Clone a repository, inspect its environment, and prepare a reproducible development setup.**

`zero` analyzes a Git repository, detects its language and dependency conventions, and helps construct or run the resulting environment. The repository includes sandbox/container support, diagnostics, examples and benchmark tooling.

## Installation

Python 3.10 or newer is required for the CLI.

```sh
git clone https://github.com/alexandre-lorin/zerodev.git
cd zerodev
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
zero --help
```

Read the [complete command and feature reference](docs/README-REFERENCE.md) before running project setup commands. Repository detection and a successful process launch do not establish that every project dependency or GPU feature works.

## Isolation and trust

Treat cloned projects and their setup commands as untrusted until reviewed. Use the [container guide](docs/CONTAINER.md) for its stated isolation scope and limitations. A container is not proof that every action is safe; a requested sandbox must not silently fall back when its backend is unavailable.

## Validation

```sh
python -m unittest discover -s tests -v
```

The previous local report recorded two remaining failures in the overall test suite. That historical result is not a claim that all tests pass in this public snapshot. The [real-machine validation guide](docs/VALIDATION.md) distinguishes what was exercised from what still needs hardware or runtime verification.

## Documentation

- [Full reference](docs/README-REFERENCE.md)
- [Containers](docs/CONTAINER.md)
- [Real-machine validation](docs/VALIDATION.md)
- [Benchmark methodology and results](benchmark/README.md)
- [Packaging and publishing](docs/PUBLISHING.md)
- [Historical changelog](docs/CHANGELOG.md)

Benchmark results apply to their documented datasets and environments. No general speed, isolation or GPU-compatibility guarantee follows from them.
