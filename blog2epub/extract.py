"""Extraction d'un article : métadonnées + corps en Markdown.

La détection est générique (cascade de conteneurs, métadonnées multiples). Un
profil dans config/sites.json peut surcharger n'importe quel sélecteur.
"""

import html
import re
import urllib.parse

from .dom import parse_html, select, select_first
from .markdown import block_md, clean_md, collapse, inline_md

# Ordre de préférence des conteneurs quand aucun profil ne s'applique.
CONTAINER_CASCADE = [
    "article [itemtype*=Article]",
    "article",
    "[itemtype*=Article]",
    ".entry-content",
    ".post-content",
    "article-body",
    ".article-content",
    "main article",
    "main",
    "#content article",
    "#content",
    "body",
]

TITLE_CASCADE = ["h1", "h2", ".entry-title", ".post-title", "title"]
AUTHOR_CASCADE = [".author", ".byline", "[rel=author]", "[itemprop=author]"]
DATE_CASCADE = ["time[datetime]", "time", ".date", ".published", ".entry-date"]

META_TITLE = ["og:title", "twitter:title"]
META_AUTHOR = ["article:author", "author", "og:article:author"]
META_DATE = ["article:published_time", "og:article:published_time", "date",
             "og:updated_time", "pubdate"]
META_IMAGE = ["og:image", "twitter:image"]

CLEANSE = (
    "script, style, noscript, nav, .navbar, .navigation, .menu, .sidebar, aside,"
    "footer, .footer, .share, .sharedaddy, .social, .newsletter, .subscribe,"
    ".comment, .comments, .related, .recommend, .jp-relatedposts, .breadcrumb,"
    ".cookie, .banner, .advert, .ad, #comments, .signature, .author-bio"
)


class Article:
    """Un article extrait, prêt à être rendu en chapitre."""

    def __init__(self, url=""):
        self.url = url
        self.slug = ""
        self.host = ""
        self.lang = ""
        self.title = ""
        self.author = ""
        self.date = ""
        self.image = ""
        self.body_md = ""
        self.about_md = ""
        self.permalink = ""
        self.characters = 0
        self.container = ""
        self.problems = []

    def __repr__(self):
        return "<Article %s %s>" % (self.date, self.title[:40])


def slug_for(url):
    path = urllib.parse.urlparse(url).path
    slug = (path.rstrip("/").split("/")[-1] or urllib.parse.urlparse(url).netloc)
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug, flags=re.I)
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", slug)[:80] or "article"


def _meta(root, keys):
    """Cherche une balise <meta> par propriété Open Graph ou par nom."""
    for m in root.find_all("meta"):
        label = (m.attrs.get("property") or m.attrs.get("name")
                 or m.attrs.get("itemprop") or "").strip().lower()
        content = m.attrs.get("content") or ""
        if label and content and label in keys:
            return html.unescape(content)
    return ""


def _first_text(root, selectors, base):
    for selector in selectors:
        node = select_first(root, selector)
        if node is None:
            continue
        if node.tag == "meta":
            content = node.attrs.get("content", "")
            if content:
                return html.unescape(content).strip()
            continue
        if node.tag == "time":
            return (node.attrs.get("datetime") or collapse(node.text_of())).strip()
        text = collapse(inline_md(node, base)).strip()
        if text:
            return text
    return ""


def _strip_site_suffix(title):
    """Retire le nom du site ajouté en fin de titre, sans toucher aux tirets internes.

    « Mon billet - Mon Blog » devient « Mon billet », mais « Petit manifeste
    low-tech » reste intact.
    """
    for pattern in (r"\s*[|–—]\s*[^|–—]{3,60}$", r"\s+-\s+[^-–—|]{3,60}$"):
        stripped = re.sub(pattern, "", title)
        if stripped != title:
            return stripped.strip()
    return title.strip()


def _iso_date(text):
    if not text:
        return ""
    match = re.search(r"(20\d\d)-(\d\d)-(\d\d)", text)
    if match:
        return match.group(0)
    match = re.search(r"(\d{1,2})\s+(\w+)\s+(20\d\d)", text)
    if match:
        months = {"janvier": "01", "fevrier": "02", "février": "02", "mars": "03",
                  "avril": "04", "mai": "05", "juin": "06", "juillet": "07",
                  "aout": "08", "août": "08", "septembre": "09", "octobre": "10",
                  "novembre": "11", "decembre": "12", "décembre": "12"}
        name = match.group(2).lower()
        if name in months:
            return "%s-%s-%02d" % (match.group(3), months[name], int(match.group(1)))
    return ""


def _drop(node, root):
    """Supprime les sous-arbres correspondant aux sélecteurs de nettoyage."""
    doomed = set()
    for selector in CLEANSE.split(","):
        selector = selector.strip()
        if not selector:
            continue
        try:
            for hit in select(node, selector):
                doomed.add(id(hit))
        except Exception:
            continue
    if not doomed:
        return
    kept = []
    for k in node.kids:
        if id(k) in doomed:
            continue
        kept.append(k)
    node.kids = kept


def extract(url, source, profile=None, date_hint=""):
    """Extrait titre, auteur, date, image et corps Markdown d'une page HTML."""
    profile = profile or {}
    art = Article(url=url)
    art.host = urllib.parse.urlparse(url).netloc.lower()
    art.slug = slug_for(url)
    root = parse_html(source)

    html_node = next((n for n in root.walk() if n.tag == "html"), None)
    if html_node is not None:
        art.lang = (html_node.attrs.get("lang") or "").strip()[:2].lower()

    base = urllib.parse.urljoin(url, "/")
    art.title = collapse(_meta(root, META_TITLE)).strip()
    if not art.title:
        art.title = _first_text(root, profile.get("title") and [profile["title"]]
                                or TITLE_CASCADE, url)
    art.title = _strip_site_suffix(art.title) or art.slug

    art.author = collapse(_meta(root, META_AUTHOR)).strip()
    if not art.author:
        art.author = _first_text(root, AUTHOR_CASCADE, url)
    art.author = re.split(r"\s+[-–—|]\s+|\s+par\s+", art.author)[0].strip() if art.author else ""

    art.date = _iso_date(_meta(root, META_DATE)) or _iso_date(_first_text(root, DATE_CASCADE, url))
    if not art.date:
        art.date = _iso_date(date_hint) or _iso_date(url)

    image = _meta(root, META_IMAGE)
    art.image = _abs(image, url) if image else ""

    container_selectors = profile.get("container") or CONTAINER_CASCADE
    body_node, art.container = None, ""
    for selector in str(container_selectors).split(","):
        node = select_first(root, selector.strip())
        if node is not None and len(node.text_of().strip()) > 200:
            body_node, art.container = node, selector.strip()
            break
    if body_node is None:
        node = select_first(root, "body")
        body_node, art.container = node, "body"
        art.problems.append("conteneur introuvable, corps de la page entière")

    keep = profile.get("keep")
    if keep:
        for selector in str(keep).split(","):
            node = select_first(root, selector.strip())
            if node is None:
                continue
            body_node = node
            art.container = selector.strip()
            break

    _drop(body_node, root)
    for selector in str(profile.get("remove", "")).split(","):
        selector = selector.strip()
        if not selector:
            continue
        try:
            for hit in select(body_node, selector):
                hit.parent.kids.remove(hit)
        except Exception:
            continue

    out = []
    for k in list(body_node.kids):
        if k.tag == "h1":
            continue  # le titre devient l'en-tête de chapitre
        classes = k.classes()
        if "subtitle" in classes or "signature" in classes:
            continue
        if k.tag == "img" and "header" in classes:
            continue
        block_md(k, url, out)
    art.body_md = clean_md("\n".join(out))
    art.characters = len(re.sub(r"\s+", " ", art.body_md))

    if profile.get("permalink") == "gemini":
        parsed = urllib.parse.urlparse(url)
        art.permalink = "gemini://%s/%s.gmi" % (parsed.netloc,
                                                parsed.path.lstrip("/").replace(".html", ""))
    return art


def _abs(href, base):
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    return urllib.parse.urljoin(base, href)


def classify(article):
    """Classe un article pour l'import de flux.

    Retourne un couple (code, motif) : 'article', 'lien', 'creux' ou 'mort'.
    """
    if article.characters < 400:
        return "creux", "corps trop court (%d caractères)" % article.characters
    if len(article.body_md.split("\n")) < 4:
        return "creux", "presque aucun paragraphe"
    links = len(re.findall(r"(?<!\!)\[[^\]]*\]\(", article.body_md))
    words = len(article.body_md.split())
    if links > 8 and links * 6 > words:
        return "lien", "semble une vidange de liens (%d liens pour %d mots)" % (links, words)
    return "article", ""