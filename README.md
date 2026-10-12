# ploum-epub — fabrique d'anthologies EPUB à partir de billets de blog

Outil autonome (Python 3, **stdlib uniquement**, aucune installation) qui transforme
une liste d'URL d'articles en un EPUB 3, **un chapitre par article**.

## Utilisation

```bash
# 1. télécharger et extraire les articles en Markdown (src/)
python3 blog2epub.py liens.txt --fetch-only

# 2. traduire : déposer un fichier fr/<slug>.md par article anglais
#    (front matter optionnel pour le titre)
#    ---
#    title: "Le titre traduit"
#    ---

# 3. contrôler la parité structurelle des traductions
python3 blog2epub.py liens.txt --check-fr

# 4. fabriquer l'EPUB (échoue si une traduction manque)
python3 blog2epub.py liens.txt --strict -o "Anthologie.epub"
```

## Options

| Option | Effet |
|---|---|
| `-o, --out` | fichier EPUB de sortie |
| `--title` / `--author` | métadonnées `dc:title`, `dc:creator` |
| `--order desc\|asc\|given` | antichronologique (défaut), chronologique, ordre du fichier |
| `--cover URL` | image de couverture (défaut : illustration du 1er article) |
| `--refresh` | re-télécharge les sources |
| `--fetch-only` | s'arrête après l'extraction Markdown |
| `--check-fr` | vérifie titres/liens/images/blocs de code et détecte texte étranger résiduel |
| `--list-missing` | liste les traductions manquantes |
| `--strict` | code retour 1 s'il manque une traduction |

## Ce que fait le pipeline

1. **Fetch** — `urllib`, 3 tentatives, User-Agent configurable.
2. **Extraction** — nœud `<article>`, `og:title` / `og:article:published_time` /
   `og:image`, `html lang`. Retraits : logo d'en-tête, `p.subtitle`, `div.signature`
   (remis en page « À propos » finale).
3. **HTML → Markdown** — titres, paragraphes, listes imbriquées, citations, figures
   avec légende, blocs `<pre>`, tableaux, liens et images absolutisés.
4. **Traduction** — `fr/<slug>.md` si présent, sinon le texte source d'origine.
5. **Markdown → XHTML** — rendu strict (une seule racine, balises fermées).
6. **Images** — téléchargement, conversion WebP/PNG → JPEG via ImageMagick,
   réécriture des `src`, `properties="cover-image"`.
7. **EPUB 3** — `mimetype` stocké en première entrée, `container.xml`, `content.opf`,
   `nav.xhtml`, `toc.ncx` (compat lecteurs anciens), CSS embarqué.
8. **Vérifications** — XML bien formé, `href`/`src` tous résolus, spine et manifest
   cohérents.

## Structure du dépôt

```
blog2epub.py         l'outil
liens.txt            les URL, une par ligne
src/<slug>.md        extraction Markdown (source)
src/<slug>.meta      titre, auteur, date, langue, image de couverture
src/<slug>.about.md  bloc « à propos de l'auteur »
fr/<slug>.md         traductions françaises
<sortie>.epub        le livre
```

## Réutiliser pour un autre blog

Le script ne dépend pas de ploum.net : il cherche un `<article>` et se rabat sur
`<body>`. Les métadonnées retombent sur `<title>`, `<h1>` et une date ISO trouvée
dans le texte.