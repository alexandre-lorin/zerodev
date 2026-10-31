# Publish zerodev on PyPI

State checked (0.25.0, Linux sandbox): `python -m build` produces an sdist and a wheel (`py3-none-any`, no dependencies);
`twine check`: PASSED for both; the wheel installed in a blank venv gives `zero --version` → `zerodev 0.25.0` and
`zero plan <dépôt>` works. The name `zerodev` (along with `zero-dev` and `zerodev-cli`) returned 404 on PyPI on 27/10/2026,
therefore free on this date: to be rechecked just before publishing. **Nothing has been published**: you need a PyPI account.

## Procedure

    pip install build twine
    git status # clean tree
    python -m unittest discover -s tests # all OK
    python -m build --outdir dist .
    twine check dist/*
    twine upload --repository testpypi dist/* # repeat on test.pypi.org (separate account)
    pipx install --index-url https://test.pypi.org/simple/ zerodev # control
    twine upload dist/* # actual post (API token, not password)

A published version is **final** (it cannot be replaced or reused): increment `VERSION` in
`src/zerodev/util.py` (single source) before each publication. Never commit `dist/` or `build/`.

## Know before announcing “pipx install zerodev”

- The repository is used today by `git clone` + `./bin/zero` or `install.sh`; the examples (`examples/`) and `demo.sh` are not
  **step** in the wheel: `pipx install` gives the command `zero`, not the demos.
- `uv` is installed by zero if necessary; Docker/Podman remain optional. Python ≥ 3.10 required.
- The README is the long_description: its relative links (docs/…) will not work on the PyPI page; replace them with URLs
  absolute of the public deposit once the address is known.
