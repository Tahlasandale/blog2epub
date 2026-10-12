---
title: "Bonjour Python 3.15, adieu 3.10, et maintenant je peux utiliser 3.11"
---

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

- [setlimit()](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.setlimit) et [getlimit()](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.getlimit) exposent un mécanisme pour définir les [limites d'exécution de SQLite](https://www.sqlite.org/c3ref/c_limit_attached.html) depuis Python.
- [create_window_function()](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.create_window_function) permet de créer des fonctions fenêtre personnalisées en Python, sous la forme d'une classe avec les méthodes `step()`, `value()`, `inverse()` et `finalize()`.
- [blobopen()](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.blobopen) fournit un mécanisme efficace pour lire et écrire partiellement de grandes valeurs binaires `BLOB` stockées dans une ligne SQLite.
- On peut maintenant appeler `set_authorizer(None)` pour retirer un authorizer SQLite. Datasette avait un contournement pour ça !

Plus tout un tas d'[améliorations du système de typage de Python](https://docs.python.org/3/whatsnew/3.11.html#new-feat-related-type-hints-311).

Je compte appliquer les améliorations de Python 3.11 à un tas de mes projets au cours des prochaines semaines. Voici [ma première PR Datasette](https://github.com/simonw/datasette/pull/2998), qui retire ce contournement `set_authorizer(None)`.

J'ai aussi mis à jour mes templates cookiecutter [click-app](https://github.com/simonw/click-app), [datasette-plugin](https://github.com/simonw/datasette-plugin), [python-lib](https://github.com/simonw/python-lib) et [llm-plugin](https://github.com/simonw/llm-plugin) pour qu'ils soient testés avec Python 3.11 jusqu'à Python 3.15.

Publié

12 octobre 2026

à 18h15 · Suivez-moi sur

Mastodon

,

Bluesky

,

Twitter

ou

abonnez-vous à ma newsletter

## Articles plus récents

- [Une nouvelle fonctionnalité pour mon blog, construite avec ma voix](https://simonwillison.net/2026/Oct/9/built-using-my-voice/) - 9 octobre 2026
- [Claude Haiku 5.5](https://simonwillison.net/2026/Oct/7/claude-haiku-5-5/) - 7 octobre 2026
- [Nous allons avoir besoin de plafonds budgétaires rigides par défaut sur à peu près tout](https://simonwillison.net/2026/Oct/3/default-hard-budget-caps/) - 3 octobre 2026
- [Blog live de l'OpenAI DevDay 2026](https://simonwillison.net/2026/Sep/29/openai-devday-2026-live-blog/) - 29 septembre 2026