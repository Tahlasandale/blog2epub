# blog2epub

Compile des articles de blog en **un EPUB, un chapitre par article**, en français.

Python 3.9 ou plus récent, **aucune dépendance** en dehors de la bibliothèque
standard. Pas de pandoc, pas de calibre, rien à installer. ImageMagick est utilisé
s'il est présent, pour convertir les images en JPEG.

```
./bin/blog2epub                      ouvre l'interface
./bin/blog2epub liens.txt            interface pré-remplie avec ces URL
./bin/blog2epub build liens.txt      construit l'EPUB sans passer par l'interface
```

---

## Sommaire

- [Ce que ça fait](#ce-que-ça-fait)
- [Démarrage](#démarrage)
- [L'interface](#linterface)
- [Commandes](#commandes)
- [Entrées possibles](#entrées-possibles)
- [Traduction automatique](#traduction-automatique)
- [Archive et catalogue](#archive-et-catalogue)
- [Configuration](#configuration)
- [Ajouter un site](#ajouter-un-site)
- [Images](#images)
- [Organisation du dépôt](#organisation-du-dépôt)
- [Dépannage](#dépannage)

---

## Ce que ça fait

1. **Télécharge** les billets, une page HTML à la fois.
2. **Extrait** le titre, l'auteur, la date et le corps, quel que soit le logiciel
   qui a généré le blog.
3. **Archive** le HTML brut et le Markdown extrait : un billet déjà vu n'est
   jamais retéléchargé.
4. **Traduit** en français les billets qui ne le sont pas, via le CLI `opencode`.
5. **Assemble** un EPUB 3 : sommaire, page de couverture, CSS de lecture, une
   page par article, et un lien vers la source d'origine en bas de chaque
   chapitre.
6. **Vérifie** la structure du fichier produit avant de dire que tout va bien.

L'outil ne dépend pas d'un blog en particulier. Sur les 18 flux d'un export OPML
réel, la détection générique a suffi pour tous les billets d'articles ; quatre
entrées sans article (podcast, vidanges de liens, flux vidéo) ont été reconnues
et écartées.

## Démarrage

```bash
cd ploum-epub

# Ouvrir l'interface et y coller des URL
./bin/blog2epub

# Ou construire directement un livre
./bin/blog2epub build liens-ploum.txt
```

La première construction télécharge, archive et traduit. Les suivantes
partent de l'archive et ne refont que ce qui manque. Le livre est écrit dans
`out/`.

## L'interface

L'interface est en plein écran (curses). Deux modes, séparés par **Tab** :

- **liste** — les touches sont des commandes ;
- **saisie** — ce que vous tapez va dans le champ `URL>` ; **Entrée** valide.

```
┌ blog2epub — composeurs d'EPUB à partir de billets de blog ┐
│                                                          │
│  URL>                                                    │
│                                                          │
│  Articles                                                │
│   [x]  publié     2026-09-21 Fuir le numérique ou bien… │
│   [x]  à traduire 2026-03-20 The Social Smolnet         │
│   [ ]  récupéré   2026-09-14 Soyez humains, communiquez│
│                                                          │
│  Tab saisie ·Entrée valider · espace retenir · j/k …     │
│  3 article(s) · 2 retenu(s)                             │
└──────────────────────────────────────────────────────────┘
```

| Touche | Action |
|---|---|
| `Tab` | passer dans le champ de saisie / revenir à la liste |
| `Entrée` | valider les URL saisies |
| `espace` | retirer ou remettre l'article sous le curseur |
| `j` / `k`, `g` / `G` | naviguer dans la liste |
| `d` | télécharger, extraire et archiver |
| `t` | traduire l'article sous le curseur |
| `o` | importer un export OPML |
| `b` | construire l'EPUB (demande un titre) |
| `x` | retirer l'article |
| `?` | aide |
| `q` | quitter |

**Sans terminal**, l'outil bascule tout seul sur un mode invites qui offre les
mêmes opérations, ce qui le garde scriptable :

```bash
printf 'a https://ploum.net/2025-04-01-xkcdpunk.html\nd\nb\n' | ./bin/blog2epub
```

## Commandes

| Commande | Effet |
|---|---|
| `blog2epub` | ouvre l'interface |
| `blog2epub <fichier.txt>` | interface pré-remplie |
| `blog2epub build <fichier>` | construit l'EPUB |
| `blog2epub fetch <fichier>` | télécharge, extrait, archive |
| `blog2epub check <fichier>` | contrôle les traductions existantes |
| `blog2epub translate <fichier>` | traduit via opencode |
| `blog2epub opml <fichier.opml>` | liste les articles récents des flux |
| `blog2epub archive stats\|list\|resync\|purge` | entretien de l'archive |
| `blog2epub tui` | interface (identique à la commande nue) |

Options de `build` :

| Option | Effet |
|---|---|
| `--title` | titre du livre ; sans option, il est demandé |
| `--author` | auteur des métadonnées |
| `--order desc\|asc\|given` | antichronologique (défaut), chronologique, ordre du fichier |
| `-o`, `--out` | chemin du fichier EPUB |
| `--cover URL` | image de couverture |
| `--lang` | langue du livre, `fr` par défaut |
| `--model` | modèle opencode pour la traduction |
| `--no-translate` | ne rien traduire, garder les langues d'origine |

## Entrées possibles

**URL** — un fichier texte (une URL par ligne), des `--url`, ou `-` pour stdin :

```bash
./bin/blog2epub build --url https://a.example/billet https://c.example/autre
cat urls.txt | ./bin/blog2epub build -
```

**Flux RSS et Atom** :

```bash
./bin/blog2epub fetch https://korben.info/feed/
```

**Export OPML** — un export d'abonnements, comme celui de votre lecteur de flux :

```bash
./bin/blog2epub opml ~/Téléchargements/SmartRSS-subscriptions-20261013.xml
./bin/blog2epub opml abonnements.opml --group Default --days 14
```

L'OPML est lu seul, jamais modifié. L'outil affiche les articles publiés dans la
fenêtre (7 jours par défaut), groupe par groupe de flux, pour que vous reteniez
ce qui vous intéresse. Les entrées qui ne sont pas des articles — podcast, vidange
de liens, flux vidéo — sont signalées et exclues par défaut.

## Traduction automatique

Les articles dont la langue diffère de celle du livre sont traduits par le CLI
`opencode`, automatiquement, à chaque construction.

```bash
./bin/blog2epub translate --url https://blog.exemple/un-billet-anglais
./bin/blog2epub build liens.txt --model opencode/un-autre-modele
```

Trois garde-fous :

- **un fichier `fr/<slug>.md` fait foi** — il n'est jamais réécrit, donc vos
  relectures sont conservées et les constructions suivantes sont gratuites ;
- **découpage** au-delà de 2 500 mots, pour que le modèle ne tronque pas ;
- **contrôle de parité** avant écriture : titres, liens, images, blocs de code et
  citations doivent correspondre à la source, la longueur doit rester plausible,
  et les caractères non latins ou les reliquats d'anglais font échouer la
  traduction.

Si une traduction échoue, le chapitre est **gardé en version originale** avec une
mention en tête de page, et un récapitulatif est affiché en fin de construction.
Le livre est produit quand même ; le code de retour vaut 1.

La liste des modèles est dans `config/settings.json`, avec repli :

```json
"translate": {
  "model": ["opencode/space-bunny-free", "opencode/ling-3.1-flash-free"],
  "attempts": 2
}
```

## Archive et catalogue

Chaque article téléchargé est conservé deux fois : le HTML brut et le Markdown
extrait, dans `archive/<hôte>/`. Rien n'est retéléchargé ensuite.

`catalog.jsonl` est le journal, **suivi par git**. Une ligne JSON par article :

```json
{"author":"Ploum - Lionel Dricot","characters":11901,"container":"article",
 "date":"2026-09-21","epubs":["Ploum.net — Anthologie 2025-2026"],
 "fetched_at":"2026-10-13T00:48:07+0200","host":"ploum.net",
 "lang":"fr","revision":1,"sha256":"7cfe09e3…","slug":"2026-09-21-fuir_o…",
 "status":"published","title":"Fuir le numérique ou bien le reconquérir ?","url":"…"}
```

Le champ `status` suit le parcours d'un article : `new` → `archived` →
`translated` → `published`.

```bash
./bin/blog2epub archive stats   # combien d'articles, par statut
./bin/blog2epub archive list    # la liste
./bin/blog2epub archive resync  # retire du catalogue les entrées disparues
./bin/blog2epub archive purge   # vide l'archive et le catalogue
```

Un article publié dans plusieurs livres les Accumule dans `epubs[]`.

## Configuration

`config/settings.json` (facultatif) :

```json
{
  "book":    { "lang": "fr", "author": "Auteur inconnu", "title": "Anthologie" },
  "translate": { "model": ["opencode/space-bunny-free"], "attempts": 2,
                 "single_shot": 2500, "chunk_words": 600 },
  "opml":    { "days": 7 },
  "images":  { "quality": 88, "max_width": 1600 },
  "epub":    { "outdir": "out" }
}
```

## Ajouter un site

Dans la plupart des cas, **rien à faire**. La détection essaie dans l'ordre :

```
article[itemtype*=Article] → article → [itemtype*=Article] → .entry-content
→ .post-content → main article → main → #content → body
```

et prend le premier conteneur dont le texte dépasse 200 caractères. Les titres,
auteurs et dates sont cherchés dans les balises Open Graph d'abord, puis à
l'intérieur du conteneur — jamais dans l'en-tête du site.

Quand un blog résiste, ajoutez un profil dans `config/sites.json` :

```json
{
  "host": "exemple.org",
  "container": "div.post-body",
  "remove": "nav, .comments, .share",
  "title": "h1.post-title",
  "author": ".byline",
  "permalink": "gemini"
}
```

Les sélecteurs acceptent `tag`, `.classe`, `#id`, `tag.classe`, le combinateur
descendant (espace) et les listes séparées par des virgules. Trois profils sont
livrés et servent de référence : `ploum.net`, `framablog.org` (WordPress) et
`simonwillison.net` (Django).

## Images

Les images sont téléchargées, converties en JPEG qualité 88 et bornées à
1 600 px de large, ce qui garde les livres autour de 1 Mo et évite les surprises
de mémoire sur liseuse. Sans ImageMagick, le fichier d'origine est conservé tel
quel. `--cover URL` impose une couverture ; sinon la première illustration du
livre est utilisée.

## Organisation du dépôt

```
bin/blog2epub          exécutable
blog2epub/             le paquet
  dom.py               micro-DOM et sélecteurs CSS
  config.py            réglages et profils
  fetch.py             téléchargement
  markdown.py          HTML ↔ Markdown
  extract.py           extraction d'article et classification
  epub.py              assemblage et vérification EPUB 3
  archive.py           archive et catalogue
  feeds.py             RSS, Atom, OPML
  translate.py         traduction via opencode et lint
  project.py           orchestration
  tui.py               interface curses et mode invites
  cli.py               commandes
config/sites.json      profils de sites
catalog.jsonl          journal des articles traités (suivi par git)
archive/               HTML et Markdown (ignoré)
fr/                    traductions (ignoré)
out/                   livres produits (ignoré)
liens-ploum.txt        les URL de l'anthologie de référence
```

## Dépannage

**Un billet sort vide ou tronqué.** Le conteneur détecté était le mauvais.
Ajoutez un profil pour ce domaine, ou vérifiez avec :

```bash
./bin/blog2epub fetch --url <url> --refresh
./bin/blog2epub archive list
```

**Un billet n'a pas de date.** Les balises `<time>`, Open Graph, l'URL
(`/2026/Oct/12/…`) et le début du texte sont essayés dans l'ordre. Un profil avec
un sélecteur `date` règle les cas difficiles.

**La traduction échoue.** Le message indique la section fautive et les deux
nombres comparés. Testez le modèle seul :

```bash
opencode run --auto --model opencode/space-bunny-free -f article.md "Traduis en français"
```

Un modèle free-tier peut tronquer : essayez un modèle plus fiable, ou réduisez
`translate.single_shot` pour forcer le découpage en sections.

**Le livre ne s'ouvre pas.** La construction affiche déjà le diagnostic :

```
PROBLÈMES :
  - OEBPS/chap03.xhtml : référence cassée images/photo-2.jpg
```

Le fichier reste produit, et `out/` conserve le dossier de construction pour
inspection.

---

Les textes restent la propriété de leurs auteurs ; `catalog.jsonl` ne contient que
des URL, des titres et des dates. Chaque chapitre de l'EPUB renvoie à sa source
d'origine.