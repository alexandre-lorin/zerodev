# Publier zerodev sur PyPI

État vérifié (0.25.0, sandbox Linux) : `python -m build` produit un sdist et une roue (`py3-none-any`, aucune dépendance) ;
`twine check` : PASSED pour les deux ; la roue installée dans un venv vierge donne `zero --version` → `zerodev 0.25.0` et
`zero plan <dépôt>` fonctionne. Le nom `zerodev` (ainsi que `zero-dev` et `zerodev-cli`) renvoyait 404 sur PyPI le 27/10/2026,
donc libre à cette date : à revérifier juste avant de publier. **Rien n'a été publié** : il faut un compte PyPI.

## Procédure

    pip install build twine
    git status                                   # arbre propre
    python -m unittest discover -s tests         # tout OK
    python -m build --outdir dist .
    twine check dist/*
    twine upload --repository testpypi dist/*    # répétition sur test.pypi.org (compte distinct)
    pipx install --index-url https://test.pypi.org/simple/ zerodev    # contrôle
    twine upload dist/*                          # publication réelle (jeton API, pas le mot de passe)

Une version publiée est **définitive** (on ne peut ni la remplacer ni la réutiliser) : incrémenter `VERSION` dans
`src/zerodev/util.py` (source unique) avant chaque publication. Ne jamais commiter `dist/` ni `build/`.

## À savoir avant d'annoncer « pipx install zerodev »

- Le dépôt s'utilise aujourd'hui par `git clone` + `./bin/zero` ou `install.sh` ; les exemples (`examples/`) et `demo.sh` ne sont
  **pas** dans la roue : `pipx install` donne la commande `zero`, pas les démos.
- `uv` est installé par zero au besoin ; Docker/Podman restent facultatifs. Python ≥ 3.10 requis.
- Le README est le long_description : ses liens relatifs (docs/…) ne fonctionneront pas sur la page PyPI ; les remplacer par des URL
  absolues du dépôt public une fois l'adresse connue.
