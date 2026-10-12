---
title: "Bonjour Python 3.15, au revoir 3.10, et je peux enfin utiliser 3.11"
---

## Bonjour Python 3.15, au revoir 3.10, et je peux enfin utiliser 3.11

12 octobre 2026

Python 3.15 [est arrivé](https://www.python.org/downloads/release/python-3150/) ! Voici le guide indispensable [What's new in Python 3.15](https://docs.python.org/3.15/whatsnew/3.15.html), cette année curationné par Hugo van Kemenade, release manager de 3.14 et 3.15. En tant que personne qui développe des logiciels open source qui fonctionnent sur toutes les versions de Python encore supportées, je peux dire adieu à Python 3.10 et commencer à adopter les fonctionnalités de Python 3.11.

D'abord, quelques points forts de Python 3.15.

#### Imports paresseux explicites

C'est l'[imports paresseux explicites](https://docs.python.org/3.15/whatsnew/3.15.html#pep-810-explicit-lazy-imports) de la [PEP 810](https://peps.python.org/pep-0810/) qui me enthousiasment le plus. Ils permettent d'importer des modules ainsi :

```
lazy import json
lazy from pathlib import Path
```

Le module sera alors importé la première fois que ces symboles seront utilisés dans le code qui suit.

Mon outil en ligne de commande [LLM](https://llm.datasette.io/) gère des plugins. J'ai dû [recommander les imports paresseux manuels](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#tip-lazily-load-expensive-dependencies) dans la documentation destinée aux auteurs de plugins, parce que le simple fait d'installer des plugins utilisant des dépendances lourdes comme `sentence_transformers` pouvait ajouter plusieurs secondes à chaque invocation de la commande `llm`. Les imports paresseux règlent directement ce problème de démarrage.

#### Déballage dans les comprehensions

La nouvelle syntaxe de déballage `[*sublist for sublist in lists]` est élégante. Voici un exemple [repris de la documentation](https://docs.python.org/3.15/whatsnew/3.15.html#pep-798-unpacking-in-comprehensions) :

```
lists = [[1, 2], [3, 4], [5]]
[*L for L in lists]
# [1, 2, 3, 4, 5]
# equivalent to [x for L in lists for x in L]

sets = [{1, 2}, {2, 3}, {3, 4}]
{*s for s in sets}
# {1, 2, 3, 4}
# equivalent to {x for s in sets for x in s}

dicts = [{'a': 1}, {'b': 2}, {'a': 3}]
{**d for d in dicts}
# {'a': 3, 'b': 2}
# equivalent to {k: v for d in dicts for k,v in d.items()}
```

La [PEP 798 : Unpacking in Comprehensions](https://peps.python.org/pep-0798/), par Adam Hartz et Erik Demaine, a proposé cela comme une extension de la syntaxe de déballage [de la PEP 448](https://peps.python.org/pep-0448/), qui avait fait son apparition [dans Python 3.5](https://docs.python.org/3/whatsnew/3.5.html#pep-448-additional-unpacking-generalizations) en 2015.

#### Un profileur par échantillonnage

Le profileur de traçage existant de Python a été renommé de `cProfile` en [profiling.tracing](https://docs.python.org/3.15/library/profiling.tracing.html#module-profiling.tracing), et a été rejoint par un nouveau profileur par échantillonnage passionnant appelé Tachyon, aka [profiling.sampling](https://docs.python.org/3.15/whatsnew/3.15.html#tachyon-high-frequency-statistical-sampling-profiler).

Les profileurs par échantillonnage fonctionnent en capturant périodiquement les stack traces des processus en cours d'exécution, puis en utilisant ces captures pour calculer quelles fonctions passent le plus de temps à l'intérieur. Ils ont une surcharge très faible et peuvent fournir un aperçu profond des systèmes en cours d'exécution, sans avoir besoin d'instrumenter ces systèmes au préalable.

J'ai [utilisé auparavant des outils](https://simonwillison.net/tags/profiling/) comme [py-spy](https://github.com/benfred/py-spy) pour cela. Maintenant cette capacité est intégrée dans la bibliothèque standard.