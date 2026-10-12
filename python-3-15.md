---
title: "Python 3.15 : performances et mise à jour avec uv"
---

![Capture d'écran d'une sortie de terminal d'un profileur par échantillonnage Python, avec du texte coloré sur fond noir. Les lignes d'en-tête indiquent 2 651 échantillons capturés en 2,65 secondes, à un taux d'échantillonnage de 999,98 échantillons/sec, avec un taux d'erreur de 0,19. Un tableau Profile Stats avec des colonnes nsamples, sample%, tottime, cumul%, cumtime et filename:lineno(function) montre que 99,9 % des échantillons (2,644 secondes) ont été passés directement dans selectors.py KqueueSelector.select, ce qui signifie que le processus était presque entièrement inactif, en attente sur la boucle d'événements asyncio. Le reste du tableau liste la pile d'appels en dessous, avec un temps direct nul mais une présence cumulée à 100 % : asyncio base_events.py run_once, run_forever et run_until_complete, runners.py Runner.run et run, cli.py serve et sqlite_extensions wrapped, ainsi que plusieurs trames click core.py invoke, main et call. Une légende explique chaque colonne, suivie d'une section Summary of Interesting Functions qui liste les points chauds (KqueueSelector.select à 99,9 % d'échantillons directs), les fonctions les plus souvent présentes sur la pile (run_forever, run_until_complete et Runner.run à 100 %), et l'amplification d'appel la plus élevée (2645.0x pour BaseEventLoop._run_once).](https://static.simonwillison.net/static/2026/profiler-output.webp)

Il peut aussi produire [des flame graphs comme celui-ci](https://simonw.github.io/research/python-3-15-web-edit-profiling/artifacts/flamegraph.html) et [des heat maps comme celle-ci](https://simonw.github.io/research/python-3-15-web-edit-profiling/artifacts/heatmap/index.html), et même sortir un format affichable dans l'interface du Firefox profiler.

#### 3.15 n'est pas beaucoup plus rapide que 3.14

Miguel Grinberg a étudié l'autre jour [À quelle vitesse est Python 3.15 ?](https://blog.miguelgrinberg.com/post/how-fast-is-python-3-15) avec la version 3.15.0rc3 et a constaté que les performances sont globalement les mêmes qu'en 3.14, à l'exception du JIT expérimental. Le JIT a apporté un gain de 1,2x par rapport à l'interpréteur 3.15 standard (sur un test de Fibonacci) : c'est la première fois que Miguel observe une amélioration significative des performances du JIT.

Les [explorations de 3.14](https://blog.miguelgrinberg.com/post/python-3-14-is-here-how-fast-is-it) de Miguel l'an dernier avaient montré des gains considérables par rapport à Python 3.13, sur bien plus de catégories.

#### Mettre à jour vers Python 3.15 avec uv

J'ai utilisé la séquence de commandes suivante pour que `uv` utilise Python 3.15 sur mon Mac. D'abord il a fallu mettre à jour `uv` lui-même, pour qu'il connaisse la nouvelle version :

```
uv self update
```

Puis j'ai installé la version stable 3.15 :

```
uv python install 3.15
```

Et j'ai indiqué à `uv` que je voulais que ce soit la version par défaut pour toutes les commandes `uv run`, sauf si le projet lui-même épinglait une autre version :

```
uv python pin --global 3.15
```

Maintenant, la commande suivante affiche 3.15 comme version :

```
uv run python --version
```

J'avais déjà installé tout un tas d'outils avec `uv tool install`. Je les ai réinstallés pour utiliser Python 3.15 comme ceci :

```
uv tool upgrade datasette --python 3.15
```

Ensuite je peux confirmer la version comme ceci :

```
datasette --get /-/versions.json | jq
```

#### Les points saillants de Python 3.11

La sortie de 3.15 veut dire que Python 3.10 (sorti en 2021) n'est officiellement [plus pris en charge](https://devguide.python.org/versions/).

Ma règle pour mes principaux projets open source, c'est de les faire fonctionner sur toutes les versions de Python prises en charge. Je peux maintenant laisser tomber 3.10 et commencer à utiliser des fonctionnalités introduites en 3.11.

Voici le document [What’s new in Python 3.11](https://docs.python.org/3/whatsnew/3.11.html). Je peux enfin compter sur la disponibilité de [tomllib](https://docs.python.org/3/library/tomllib.html#module-tomllib) !

Datasette utilise beaucoup `asyncio`. 3.11 ajoute [TaskGroup](https://docs.python.org/3/library/asyncio-task.html#asyncio.TaskGroup) et [timeout()](https://docs.python.org/3/library/asyncio-task.html#asyncio.timeout), ainsi que [plusieurs](https://docs.python.org/3/whatsnew/3.11.html#asyncio) autres nouvelles fonctionnalités.

`datetime.UTC` est un nouvel alias, ajouté en 3.11, de `datetime.timezone.utc`.

Le support de SQLite par Python a reçu des améliorations notables en 3.11, dont :