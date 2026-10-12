"""Orchestration : constitution d'un livre à partir d'une liste d'URL."""

import os
import re
import sys

from . import archive as archive_mod
from . import epub as epub_mod
from . import extract as extract_mod
from . import translate as translate_mod
from .config import Config
from .fetch import FetchError, fetch, fetch_text
from .markdown import clean_md


class Chapter:
    def __init__(self, url):
        self.url = url
        self.title = ""
        self.lang = ""
        self.author = ""
        self.date = ""
        self.permalink = ""
        self.md = ""
        self.flag = ""
        self.translated = False

    def as_dict(self):
        return {"url": self.url, "title": self.title, "lang": self.lang or "fr",
                "author": self.author, "date": self.date, "md": self.md,
                "flag": self.flag, "permalink": self.permalink}


class Project:
    def __init__(self, root=None, config=None):
        self.config = config or Config(root)
        self.catalog = archive_mod.Catalog(self.config.catalog_path)
        self.archive = archive_mod.Archive(self.config.archive_dir, self.catalog)

    # -- récupération -------------------------------------------------------
    def fetch_article(self, url, refresh=False, quiet=False):
        """Télécharge si nécessaire, extrait, archive et renvoie l'Article."""
        profile = self.config.profile_for(_host(url))
        if not refresh:
            cached = self.archive.cached(url)
            if cached is not None:
                entry = self.catalog.get(url) or {}
                article = extract_mod.extract(url, cached, profile,
                                              date_hint=entry.get("date", ""))
                article.about_md = self.archive.about(url)
                if not quiet:
                    print("  · %s (archive)" % _short(article.title or url))
                return article, False
        try:
            source = fetch_text(url, accept="text/html,application/xhtml+xml")
        except FetchError as exc:
            if not quiet:
                print("  ! %s" % exc, file=sys.stderr)
            return None, False
        article = extract_mod.extract(url, source, profile)
        article.about_md = extract_about(article, profile)
        self.archive.store(article, source)
        if article.about_md:
            self.archive.save_about(article, article.about_md)
        self.catalog.save()
        if not quiet:
            print("  ↓ %s" % _short(article.title or url))
        return article, True

    def fetch_all(self, urls, refresh=False, quiet=False):
        articles = []
        for url in urls:
            article, _fresh = self.fetch_article(url, refresh=refresh, quiet=quiet)
            if article is not None:
                articles.append(article)
        return articles

    # -- traduction ---------------------------------------------------------
    def translation_path(self, slug):
        return os.path.join(self.config.fr_dir, slug + ".md")

    def has_translation(self, slug):
        return os.path.exists(self.translation_path(slug))

    def translate(self, articles, model="", target_lang="fr", quiet=False):
        """Traduit via opencode les articles dont la langue diffère de la cible.

        Renvoie (traduits, échecs). Les traductions déjà présentes ne sont pas
        réécrites : le fichier fr/ fait foi.
        """
        settings = self.config.settings.get("translate", {})
        models = model or settings.get("model", "")
        timeout = settings.get("timeout", 900)
        attempts = settings.get("attempts", 2)
        done, failed = [], []
        for article in articles:
            if not article.lang or article.lang == target_lang:
                done.append(article)
                continue
            if self.has_translation(article.slug):
                done.append(article)
                continue
            if not quiet:
                print("  ⇢ traduction de %s" % _short(article.title))
            try:
                body, title = translate_mod.translate_one(
                    article.body_md, article.slug + ".md", model=models,
                    timeout=timeout, attempts=attempts,
                    single_shot=settings.get("single_shot", 2500),
                    chunk_words=settings.get("chunk_words", 600),
                    on_progress=None if quiet else _progress())
            except translate_mod.TranslationError as exc:
                print("  ! traduction échouée (%s) : %s" % (article.slug, exc),
                      file=sys.stderr)
                failed.append((article, str(exc)))
                continue
            issues = translate_mod.lint(article.body_md, body)
            if issues:
                print("  ! traduction refusée (%s) : %s"
                      % (article.slug, "; ".join(issues[:3])), file=sys.stderr)
                failed.append((article, "; ".join(issues[:3])))
                continue
            translate_mod.write_translation(self.config.fr_dir, article.slug, body, title or "")
            self.catalog.upsert(article.url, title_fr=title or article.title)
            done.append(article)
        self.catalog.save()
        return done, failed

    # -- livre --------------------------------------------------------------
    def chapters_from(self, articles, target_lang="fr"):
        chapters = []
        for article in articles:
            chapter = Chapter(article.url)
            chapter.lang = article.lang or target_lang
            chapter.date = article.date
            chapter.permalink = article.permalink
            entry = self.catalog.get(article.url) or {}
            author = article.author or entry.get("author", "")
            chapter.author = author
            body = article.body_md
            translated_here = False
            if chapter.lang != target_lang:
                path = self.translation_path(article.slug)
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as handle:
                        content = handle.read().strip()
                    content = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.S)
                    body = content
                    translated_here = True
                    chapter.lang = target_lang  # le chapitre est désormais en français
                else:
                    chapter.flag = "Traduction automatique indisponible — version originale"
                fr_title = translate_mod.read_title(self.translation_path(article.slug))
                chapter.title = fr_title or article.title
            else:
                chapter.title = article.title
            chapter.translated = translated_here
            chapter.md = body
            chapters.append(chapter)
        return chapters

    def build(self, urls, title, author=None, target_lang=None, order="desc",
              cover=None, translate=False, model="", quiet=False, out_path=None,
              lang=None):
        target_lang = lang or target_lang or self.config.settings["book"]["lang"]
        author = author or self.config.settings["book"]["author"]
        articles = self.fetch_all(urls, quiet=quiet)
        if not articles:
            raise SystemExit("aucun article récupéré")
        if translate:
            self.translate(articles, model=model, target_lang=target_lang, quiet=quiet)
        chapters = self.chapters_from(articles, target_lang=target_lang)
        if order == "desc":
            chapters.sort(key=lambda c: c.date or "", reverse=True)
        elif order == "asc":
            chapters.sort(key=lambda c: c.date or "")
        about = next((a.about_md for a in articles if a.about_md), "")
        if not about:
            about = next((self.archive.about(a.url) for a in articles
                          if self.archive.about(a.url)), "")
        about = about or default_about(articles)
        os.makedirs(self.config.outdir, exist_ok=True)
        filename = _slugify(title) + ".epub"
        out_path = out_path or os.path.join(self.config.outdir, filename)

        def downloader(url):
            return fetch(url, retries=2, accept="image/*,*/*")

        builder = epub_mod.EpubBuilder(out_path, self.config.settings)
        builder.build([c.as_dict() for c in chapters],
                      {"title": title, "author": author, "lang": target_lang,
                       "description": "Compilation hors ligne de %d articles de %s, "
                                      "un article par chapitre." % (len(chapters), _hosts(chapters))},
                      downloader, about_md=about, cover_url=cover or "")
        for chapter in chapters:
            entry = self.catalog.upsert(chapter.url, title_fr=chapter.title,
                                        date=chapter.date, lang=chapter.lang or target_lang)
            if chapter.flag:
                entry["status"] = "archived"
            elif chapter.translated:
                entry["status"] = archive_mod.STATUS_TRANSLATED
            else:
                entry["status"] = archive_mod.STATUS_PUBLISHED
            self.catalog.note_epub([chapter.url], title)
        self.catalog.save()
        problems = epub_mod.verify(out_path)
        return out_path, chapters, problems


def _progress():
    def report(index, total):
        if total > 1:
            print("      section %d/%d" % (index, total))
    return report


def _host(url):
    import urllib.parse
    return urllib.parse.urlparse(url).netloc


def _hosts(chapters):
    hosts = []
    for chapter in chapters:
        host = _host(chapter.url)
        if host not in hosts:
            hosts.append(host)
    return ", ".join(hosts[:4]) or "plusieurs sources"


def _short(text, size=58):
    text = text or ""
    return text if len(text) <= size else text[:size - 1] + "…"


def _slugify(text):
    import unicodedata
    norm = unicodedata.normalize("NFKD", text)
    ascii_text = norm.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()
    return (slug or "anthologie")[:80]


def default_about(articles):
    """Page « À propos » générique,liste les sources quand aucun blog ne l'a fournie."""
    if not articles:
        return ""
    hosts = {}
    for article in articles:
        hosts.setdefault(article.host, 0)
        hosts[article.host] += 1
    lines = ["## À propos de cette compilation", "",
             "Ce livre rassemble %d articles, un par chapitre, récupérés depuis leur "
             "site d’origine. Chaque chapitre conserve un lien vers sa source, qui "
             "reste la version de référence." % len(articles), "",
             "### Sources", ""]
    for host, count in sorted(hosts.items(), key=lambda kv: -kv[1]):
        lines.append("- %s — %d article(s)" % (host, count))
    lines += ["", "Les textes restent la propriété de leurs auteurs. Cette compilation "
              "est destinée à la lecture hors ligne."]
    return "\n".join(lines)


def extract_about(article, profile=None):
    """Isole le bloc « à propos de l'auteur » à la fin du Markdown."""
    blocks = article.body_md.split("\n\n")
    tail = []
    for block in reversed(blocks):
        if block.strip().lower().startswith(("## ", "> ", "# ")):
            break
        if len(tail) >= 6:
            break
        tail.insert(0, block)
    candidate = "\n\n".join(tail).strip()
    if candidate and re.search(r"(?i)propos de l'auteur|about the author|je suis\b", candidate):
        return candidate
    return ""