"""Archive sur disque et catalogue catalog.jsonl.

L'archive conserve le HTML brut et le Markdown extrait ; le catalogue est une
ligne JSON par article, suivie par git. Retélécharger un article déjà archivé
n'est jamais nécessaire.
"""

import hashlib
import json
import os
import time
import urllib.parse

from . import extract as extract_mod

STATUS_NEW = "new"
STATUS_ARCHIVED = "archived"
STATUS_TRANSLATED = "translated"
STATUS_PUBLISHED = "published"
STATUS_STALE = "stale"


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Catalog:
    def __init__(self, path):
        self.path = path
        self.entries = []
        self.by_url = {}
        self.load()

    def load(self):
        self.entries = []
        self.by_url = {}
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.entries.append(entry)
                self.by_url[entry.get("url", "")] = entry

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            for entry in self.entries:
                handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def get(self, url):
        return self.by_url.get(url)

    def upsert(self, url, **fields):
        entry = self.by_url.get(url)
        if entry is None:
            parsed = urllib.parse.urlparse(url)
            entry = {
                "url": url,
                "slug": extract_mod.slug_for(url),
                "host": parsed.netloc.lower(),
                "title": "",
                "title_fr": "",
                "author": "",
                "date": "",
                "lang": "",
                "sha256": "",
                "fetched_at": "",
                "revision": 0,
                "status": STATUS_NEW,
                "epubs": [],
                "source": "url",
                "problems": [],
            }
            self.entries.append(entry)
            self.by_url[url] = entry
        entry.update(fields)
        return entry

    def note_epub(self, urls, book):
        for url in urls:
            entry = self.get(url)
            if entry is None:
                continue
            if book not in entry.setdefault("epubs", []):
                entry["epubs"].append(book)

    def stats(self):
        counts = {}
        for entry in self.entries:
            counts[entry.get("status", STATUS_NEW)] = counts.get(entry.get("status", STATUS_NEW), 0) + 1
        return counts


class Archive:
    """Stockage des HTML bruts et Markdown extraits."""

    def __init__(self, root, catalog):
        self.root = root
        self.catalog = catalog

    def dir_for(self, host):
        safe = re_sub(host or "inconnu")
        return os.path.join(self.root, safe)

    @staticmethod
    def _coords(item):
        """Accepte une entrée du catalogue (dict) ou un objet article."""
        if isinstance(item, dict):
            return item.get("host", ""), item.get("slug", "")
        return getattr(item, "host", ""), getattr(item, "slug", "")

    def html_path(self, item):
        host, slug = self._coords(item)
        return os.path.join(self.dir_for(host), slug + ".html")

    def md_path(self, item):
        host, slug = self._coords(item)
        return os.path.join(self.dir_for(host), slug + ".md")

    def about_path(self, item):
        host, slug = self._coords(item)
        return os.path.join(self.dir_for(host), slug + ".about.md")

    def ensure(self, host):
        os.makedirs(self.dir_for(host), exist_ok=True)

    def store(self, article, html_text, status=STATUS_ARCHIVED):
        """Archive une page et enregistre l'entrée au catalogue."""
        self.ensure(article.host)
        digest = hashlib.sha256(html_text.encode("utf-8", "replace")).hexdigest()
        previous = self.catalog.get(article.url) or {}
        revision = int(previous.get("revision", 0)) + 1
        with open(self.html_path(article), "w", encoding="utf-8") as handle:
            handle.write(html_text)
        with open(self.md_path(article), "w", encoding="utf-8") as handle:
            handle.write(article.body_md)
        return self.catalog.upsert(
            article.url,
            slug=article.slug,
            host=article.host,
            title=article.title,
            author=article.author,
            date=article.date,
            lang=article.lang,
            image=article.image,
            sha256=digest,
            fetched_at=_now(),
            revision=revision,
            container=article.container,
            status=status,
            characters=article.characters,
            problems=article.problems,
        )

    def cached(self, url):
        """Renvoie le HTML archivé, ou None s'il faut télécharger."""
        entry = self.catalog.get(url)
        if entry is None:
            return None
        path = self.html_path(entry)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def markdown(self, url):
        entry = self.catalog.get(url)
        if entry is None:
            return ""
        path = self.md_path(entry)
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def about(self, url):
        entry = self.catalog.get(url)
        if entry is None:
            return ""
        path = self.about_path(entry)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                return handle.read()
        # à défaut, on isole le bloc « à propos » du Markdown
        body = self.markdown(url)
        if not body:
            return ""
        blocks = body.split("\n\n")
        tail = []
        for block in reversed(blocks):
            head = block.strip().lower()
            if head.startswith("## ") or head.startswith("> "):
                break
            if len(tail) >= 6:
                break
            tail.insert(0, block)
        candidate = "\n\n".join(tail).strip()
        if candidate and re_any_about(candidate):
            return candidate
        return ""

    def purge_orphans(self):
        """Supprime du catalogue les entrées dont les fichiers ont disparu."""
        removed = []
        for entry in list(self.catalog.entries):
            if not os.path.exists(self.md_path(entry)):
                self.catalog.entries.remove(entry)
                self.catalog.by_url.pop(entry.get("url", ""), None)
                removed.append(entry.get("url", ""))
        return removed

    def save_about(self, article, md):
        if md:
            self.ensure(article.host)
            with open(self.about_path(article), "w", encoding="utf-8") as handle:
                handle.write(md)


def re_sub(text):
    import re
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", (text or "").lower()).strip("-") or "inconnu"


def re_any_about(text):
    import re
    return bool(re.search(r"(?i)propos de l'auteur|about the author|je suis\b", text))