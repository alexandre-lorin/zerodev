# Benchmark ZeroDev : corpus, résultats, comment les lire

`zero bench <corpus.txt>` clone chaque dépôt, calcule le plan et classe le résultat (**détection seule**, rien n'est lancé) ; avec `--full` il lance réellement chaque
dépôt (code tiers arbitraire : voir `docs/VALIDATION.md` avant de le faire chez vous, et `ZERO_BENCH_CLEANUP=1` pour nettoyer le disque).

## Ce que mesurent les champs
- `status` (détection) : `runnable` (une commande est trouvée), `no_run_command`, `ambiguous_entrypoint`, `ambiguous_monorepo`, `unsupported`, `clone_failed`, `detector_error`.
  **Une commande trouvée n'est pas une commande juste, ni qui démarre.** `run_inferred` / `entry_from_docs` / `deps_deduced` marquent les heuristiques de dernier recours (Makefile, preuve README/Dockerfile,
  imports déduits) ; le taux « strict » les exclut.
- `phase` (lancement réel) : `install_failed`, `install_timeout`, `run`, `disk_full` ; `built` = installation terminée et lancement commencé ; `launched` = un processus est encore vivant à la fin du délai ;
  `http` = un port en écoute de l'arbre de processus a répondu en HTTP (n'importe quel code : un 404 ou un 401 compte comme « répond ») ; `cli_tool` = a affiché une aide et quitté.
- Les rapports `--full` sont sauvegardés après chaque dépôt (`"partial": true` si le benchmark a été interrompu).

## Corpus
| Fichier | Contenu | Nature |
|---|---|---|
| `corpus.sample.txt` | 5 entrées d'exemple | exemples du dépôt |
| `corpus.public.txt` | 96 dépôts publics | **choisis à la main** (et réglés sur eux : surestime la détection d'une quinzaine de points) |
| `corpus.heldout.txt` | 39 dépôts | choisis à la main, hors échantillon de réglage (un peu moins optimiste) |
| `corpus.public500.txt` / `corpus.public500b.txt` | 500 + 500 dépôts | **règle fixe** (API GitHub, `language:<L> stars:<lo>..<hi> archived:false`, tri par mise à jour, 100 par langage python/javascript/typescript/go/rust) : lot 1 = 500..3000 étoiles, lot 2 = 100..499 ; reproductible avec `build_corpus_rule.py` (les résultats dépendent de la date d'exécution) |
| `corpus.demo.txt` | 3 dépôts | la démo de `demo-real.sh` |
| `build_corpus.py` | générateur historique par thèmes (webapp, cli, bot…) | non utilisé pour les corpus ci-dessus ; demande un jeton pour de gros volumes |

Dépôts de plus de 300 Mo (taille de l'API, historique complet) : écartés à l'évaluation (176 sur les 1000 : 98 + 78), donc les mesures décrivent surtout des applications légères.

## Résultats de détection (`results/`)
| Fichier | Corpus, code | Résultat |
|---|---|---|
| `public-v3.json` | 96 à la main, ~0.9 | 69/96 = 71,9 % |
| `public-v4.json` | idem remesuré, ~0.12 | 68/96 = 70,8 % (`pallets/flask` écarté à dessein) |
| `heldout-v1.json` / `heldout-v2.json` | 39 hors échantillon, 0.9.1 puis ~0.12 | 25/37 puis 24/37 clonés |
| `public500-v1.json` | lot 1, code 0.12 | 214/402 = 53,2 % |
| `public500b-v1.json` | lot 2, code 0.12 | 240/422 = 56,9 % |
| `public1000-remeasure-v0.20.json` | **les 823 dépôts des deux lots, code 0.20** | **473/823 = 57,5 %**, dont 53,5 % sans heuristique de dernier recours (**chiffre à retenir**) |

## Résultats de lancement réel (`results/live-*.json`) : petits échantillons, à ne pas extrapoler
| Fichier | Contenu | Réserve |
|---|---|---|
| `live-v1`, `live-v2-old-repos`, `live-v3-batch2`, `live-v4-http-probe`, `live-v5-batch3`, `live-v5b-microblog-with-services`, `live-v6-bun`, `live-v7-batch4`, `live-v8-batch5`, `live-v9-batch6` | essais successifs de 2 à 8 dépôts (versions 0.8 à 0.11), dépôts choisis à la main puis par l'API | historiques ; c'est de là que viennent la plupart des correctifs (voir `docs/CHANGELOG.md`) |
| `live-v10-sample500.json` | tirage de 22 dépôts « exécutables » du lot 1 (Node/Python) | **fragile** : le disque du sandbox s'est saturé, 4 clonages perdus ; premier tirage |
| `live-v11-sample2.json` | 16 dépôts (graine 7) | sans incident disque |
| `live-v12-sample3.json`, `live-v13-sample3-replay.json` | 24 dépôts (graine 11), puis rejeu des mêmes après correctifs | v13 : avant/après sur le **même** échantillon, donc pas indépendant ; `wind-comic` y a été rejoué seul (disque plein) |
| `live-v14-sample4-node.json` | 22 dépôts Node (graine 23) | le plus indépendant (aucun correctif conçu dessus) ; 2 non évalués (disque) |
| `live-v15-slow6-240s.json` | 6 gros monorepos rejoués avec un délai de 240 s | délai de 75 s insuffisant avant |
| `live-v16-old-repos-20.json` | 20 vieux dépôts (derniers commits 2015-2018), §16 | 2 répondent en HTTP |
| `live-v17-starters.json` | 16 starters (Next, Vite, Django, Flask), **seconde passe** après correctifs | le rapport de la première passe a été perdu |
| `live-v18-python-replay.json` | 10 dépôts Python qui avaient échoué, rejoués | même ensemble que les tirages précédents : pas indépendant ; gain faible |
| `live-v19-runtime-hint-ab.json` | A/B avec et sans la version déduite du Dockerfile/de la CI, mêmes 13 dépôts | 12 identiques, 1 pire (corrigé), 0 meilleur |

**Ordre de grandeur à retenir : environ un dépôt « exécutable » sur quatre sert une page HTTP** (beaucoup sont des outils en ligne de commande, des bibliothèques ou exigent un terminal/un écran).
Ne comparez pas deux fichiers sans regarder la version du code qui les a produits (`docs/CHANGELOG.md`) ; les clones sont ceux du jour de la mesure, les dépôts évoluent (un script `dev` supprimé
suffit à faire passer un dépôt de « exécutable » à « sans commande »).
