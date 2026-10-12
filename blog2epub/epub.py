"""Assemblage EPUB 3 : une page XHTML par article, images incorporées."""

import html
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import uuid
import zipfile
from datetime import datetime, timezone

from .markdown import IMG_RE, esc, md_to_html

CSS = """@charset "utf-8";
body { margin: 0 5%; line-height: 1.5; font-family: serif; }
h1 { font-size: 1.5em; line-height: 1.25; margin: 1.2em 0 .2em 0; text-align: center; }
h2 { font-size: 1.15em; margin: 1.6em 0 .4em 0; border-bottom: 1px solid #999; padding-bottom: .2em; }
h3 { font-size: 1.02em; margin: 1.2em 0 .3em 0; }
p { margin: .55em 0; text-align: justify; hyphens: auto; }
.chapter-meta { text-align: center; font-style: italic; color: #555; font-size: .85em;
                margin-bottom: 1.6em; }
.chapter-flag { text-align: center; font-size: .8em; color: #a33; margin: -.8em 0 1.4em 0; }
.source { margin-top: 2.2em; padding-top: .6em; border-top: 1px solid #bbb; font-size: .78em;
          color: #666; text-align: center; font-style: italic; }
ul, ol { margin: .5em 0 .5em 1.4em; }
li { margin: .25em 0; }
blockquote { margin: 1em 1.2em; padding: .1em 1em; border-left: 3px solid #ccc; color: #444; }
pre { background: #f2f2f2; padding: .7em .9em; overflow-x: auto; font-size: .82em;
      line-height: 1.35; white-space: pre-wrap; word-wrap: break-word; }
code { font-family: monospace; }
p > code, li > code { font-size: .88em; background: #f2f2f2; padding: 0 .2em; }
img { max-width: 100%; height: auto; display: block; margin: 1em auto .3em auto; }
em + em, p > em:only-child { display: block; text-align: center; font-size: .8em; color: #666; }
hr { border: 0; border-top: 1px solid #ccc; margin: 1.6em auto; width: 40%; }
a { color: #169; }
.cover-page { margin: 0; padding: 0; text-align: center; }
.cover-page img { max-height: 100%; max-width: 100%; margin: 0; }
"""

XHTML_TMPL = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="{css}"/>
</head>
<body>
{body}
</body>
</html>
"""


def xhtml_page(title, body, lang="fr", css="style.css"):
    return XHTML_TMPL.format(lang=lang, title=esc(title), css=css, body=body)


def _resize(data, dest, ext, quality=88, max_width=1600):
    """Convertit en JPEG et borne la largeur via ImageMagick."""
    if ext in (".jpg", ".jpeg") and not max_width:
        with open(dest, "wb") as handle:
            handle.write(data)
        return True
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        if ext in (".jpg", ".jpeg"):
            with open(dest, "wb") as handle:
                handle.write(data)
            return True
        with open(dest, "wb") as handle:
            handle.write(data)
        return False
    tmp = os.path.join(os.path.dirname(dest), "_tmp" + ext)
    with open(tmp, "wb") as handle:
        handle.write(data)
    cmd = [magick, "-background", "white", tmp, "-flatten", "-resize",
           "%dx>" % max_width, "-quality", str(quality), dest]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        ok = result.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0
    except Exception:
        ok = False
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return ok


def _image_ext(data, ctype, url):
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"):
        return ext
    for hint, value in (("png", ".png"), ("gif", ".gif"), ("svg", ".svg"),
                        ("webp", ".webp"), ("jpeg", ".jpg")):
        if hint in (ctype or ""):
            return value
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return ".jpg"


class EpubBuilder:
    def __init__(self, out_path, settings):
        self.out_path = out_path
        self.settings = settings
        self.tmp = out_path + ".build"
        self.files = []
        self.images = {}

    def add_image(self, url, data, ctype=""):
        if url in self.images:
            return self.images[url]
        ext = _image_ext(data, ctype, url)
        base = os.path.splitext(os.path.basename(urllib.parse.urlparse(url).path))[0]
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", base)[:40] or "img"
        count = sum(1 for name in self.images.values() if name.startswith(base))
        name = "%s-%d.jpg" % (base, count + 1)
        dest = os.path.join(self.tmp, "OEBPS", "images", name)
        img_conf = self.settings.get("images", {})
        if not _resize(data, dest, ext, img_conf.get("quality", 88),
                       img_conf.get("max_width", 1600)):
            pass
        self.images[url] = name
        return name

    def build(self, chapters, meta, downloader, about_md="", cover_url=""):
        """(chapters : liste de dicts title/lang/url/md/flag)."""
        if os.path.isdir(self.tmp):
            shutil.rmtree(self.tmp)
        os.makedirs(os.path.join(self.tmp, "META-INF"))
        os.makedirs(os.path.join(self.tmp, "OEBPS", "images"))

        uid = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, meta["title"] + self.out_path))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lang = meta.get("lang", "fr")

        def img_map_for(md):
            mapping = {}
            for match in IMG_RE.finditer(md):
                url = match.group(2)
                if url in mapping:
                    continue
                try:
                    data, headers = downloader(url)
                except Exception:
                    continue
                name = self.add_image(url, data, headers.get("Content-Type", ""))
                mapping[url] = "images/%s" % name
            return mapping

        cover_name = None
        if cover_url:
            try:
                data, headers = downloader(cover_url)
                cover_name = self.add_image(cover_url, data, headers.get("Content-Type", ""))
            except Exception:
                cover_name = None
        if not cover_name:
            for chapter in chapters:
                match = IMG_RE.search(chapter["md"])
                if match:
                    try:
                        data, headers = downloader(match.group(2))
                        cover_name = self.add_image(match.group(2), data,
                                                   headers.get("Content-Type", ""))
                    except Exception:
                        cover_name = None
                    if cover_name:
                        break

        nav_items = []
        ncx_points = []

        if cover_name:
            body = ('<section class="cover-page" epub:type="cover">'
                    '<img src="images/%s" alt="Couverture"/></section>' % cover_name)
            with open(os.path.join(self.tmp, "OEBPS", "cover.xhtml"), "w", encoding="utf-8") as h:
                h.write(xhtml_page(meta["title"], body, lang))
            self.files.append(("cover.xhtml", "cover", "application/xhtml+xml", ""))
            nav_items.append('<li><a href="cover.xhtml">Couverture</a></li>')

        for index, chapter in enumerate(chapters, start=1):
            body_html = md_to_html(chapter["md"], img_map_for(chapter["md"]),
                                   id_prefix="ch%d" % index)
            parts = ['<h1 id="ch%d-t">%s</h1>' % (index, _esc_title(chapter["title"]))]
            author = chapter.get("author", "")
            pieces = []
            if author:
                pieces.append(author if author.lower().startswith("par ")
                              else "par %s" % author)
            if chapter.get("date"):
                pieces.append(chapter["date"])
            line = " — ".join(pieces)
            if line:
                parts.append('<p class="chapter-meta">%s</p>' % html.escape(line))
            if chapter.get("flag"):
                parts.append('<p class="chapter-flag">%s</p>'
                             % html.escape(chapter["flag"]))
            parts.append(body_html)
            source = chapter["url"]
            perma = chapter.get("permalink")
            perma_line = ""
            if perma:
                perma_line = '<br/><a href="%s">version gemlog</a>' % html.escape(perma, quote=True)
            parts.append('<p class="source">Source : <a href="%s">%s</a>%s</p>'
                         % (html.escape(source, quote=True), html.escape(source), perma_line))
            href = "chap%02d.xhtml" % index
            with open(os.path.join(self.tmp, "OEBPS", href), "w", encoding="utf-8") as h:
                h.write(xhtml_page(chapter["title"], "\n".join(parts), chapter.get("lang", lang)))
            self.files.append((href, "chap%02d" % index, "application/xhtml+xml", ""))
            nav_items.append('<li><a href="%s">%s</a></li>' % (href, html.escape(chapter["title"])))
            ncx_points.append((chapter["title"], href, index))

        if about_md:
            body = '<h1 id="about-t">À propos</h1>%s' % md_to_html(about_md, {}, "about")
            with open(os.path.join(self.tmp, "OEBPS", "about.xhtml"), "w", encoding="utf-8") as h:
                h.write(xhtml_page("À propos", body, lang))
            self.files.append(("about.xhtml", "about", "application/xhtml+xml", ""))
            nav_items.append('<li><a href="about.xhtml">À propos de l’auteur</a></li>')
            ncx_points.append(("À propos", "about.xhtml", len(ncx_points) + 1))

        image_dir = os.path.join(self.tmp, "OEBPS", "images")
        for name in sorted(os.listdir(image_dir)):
            props = "cover-image" if name == cover_name else ""
            self.files.append(("images/" + name, "img-" + re.sub(r"[^A-Za-z0-9]", "", name),
                               "image/jpeg", props))

        with open(os.path.join(self.tmp, "OEBPS", "style.css"), "w", encoding="utf-8") as h:
            h.write(CSS)

        nav = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">
<head><meta charset="utf-8"/><title>Sommaire</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
<nav epub:type="toc" role="doc-toc" id="toc">
<h1>Sommaire</h1>
<ol>
{items}
</ol>
</nav>
</body>
</html>
""".format(lang=lang, items="\n".join(nav_items))
        with open(os.path.join(self.tmp, "OEBPS", "nav.xhtml"), "w", encoding="utf-8") as h:
            h.write(nav)
        self.files.append(("nav.xhtml", "nav", "application/xhtml+xml", "nav"))

        points = "".join(
            '<navPoint id="np%03d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
            '<content src="%s"/></navPoint>' % (i, i, html.escape(title), href)
            for title, href, i in ncx_points)
        ncx = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content="{uid}"/><meta name="dtb:depth" content="1"/>
<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>
<docTitle><text>{title}</text></docTitle>
<navMap>
{points}
</navMap>
</ncx>
""".format(uid=uid, title=html.escape(meta["title"]), points=points)
        with open(os.path.join(self.tmp, "OEBPS", "toc.ncx"), "w", encoding="utf-8") as h:
            h.write(ncx)
        self.files.append(("toc.ncx", "ncx", "application/x-dtbncx+xml", ""))

        desc = meta.get("description") or (
            "Compilation hors ligne de %d articles, un article par chapitre. "
            "Chaque chapitre renvoie à sa source originale." % len(chapters))
        rights = meta.get("rights") or (
            "Textes © leurs auteurs respectifs — compilation personnelle hors ligne ; "
            "chaque chapitre renvoie à l'original.")
        manifest = "\n".join(
            '  <item id="%s" href="%s" media-type="%s"%s/>'
            % (ident, href, media, (' properties="%s"' % props) if props else "")
            for href, ident, media, props in self.files)
        spine = "\n".join('  <itemref idref="%s"/>' % ident
                          for _href, ident, media, _p in self.files
                          if media == "application/xhtml+xml")
        opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" xml:lang="{lang}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:identifier id="pub-id">{uid}</dc:identifier>
  <dc:title id="title">{title}</dc:title>
  <dc:creator id="creator">{author}</dc:creator>
  <meta refines="#creator" property="role" scheme="marc:relators">aut</meta>
  <dc:language>{lang}</dc:language>
  <dc:date>{now}</dc:date>
  <dc:description>{desc}</dc:description>
  <dc:rights>{rights}</dc:rights>
  <meta property="dcterms:modified">{now}</meta>
</metadata>
<manifest>
{manifest}
</manifest>
<spine toc="ncx">
{spine}
</spine>
</package>
""".format(lang=lang, uid=uid, title=html.escape(meta["title"]),
           author=html.escape(meta.get("author", "")), now=now,
           desc=html.escape(desc), rights=html.escape(rights),
           manifest=manifest, spine=spine)
        with open(os.path.join(self.tmp, "OEBPS", "content.opf"), "w", encoding="utf-8") as h:
            h.write(opf)

        with open(os.path.join(self.tmp, "META-INF", "container.xml"), "w", encoding="utf-8") as h:
            h.write('<?xml version="1.0" encoding="utf-8"?>\n'
                    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                    '  <rootfiles>\n    <rootfile full-path="OEBPS/content.opf" '
                    'media-type="application/oebps-package+xml"/>\n  </rootfiles>\n</container>\n')

        with zipfile.ZipFile(self.out_path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
            for base, _dirs, names in os.walk(self.tmp):
                for name in sorted(names):
                    full = os.path.join(base, name)
                    rel = os.path.relpath(full, self.tmp).replace(os.sep, "/")
                    zf.write(full, rel, zipfile.ZIP_DEFLATED)
        shutil.rmtree(self.tmp)
        return self.out_path


def _esc_title(text):
    from .markdown import render_inline
    return render_inline(text)


def verify(path):
    """Vérifie la structure EPUB et renvoie la liste des problèmes."""
    import xml.etree.ElementTree as ET
    problems = []
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        ordered = zf.namelist()
        if not ordered or ordered[0] != "mimetype":
            problems.append("mimetype n'est pas la première entrée")
        elif zf.getinfo("mimetype").compress_type != zipfile.ZIP_STORED:
            problems.append("mimetype n'est pas stocké sans compression")
        for name in sorted(names):
            if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                try:
                    ET.fromstring(zf.read(name))
                except Exception as exc:
                    problems.append("XML invalide %s : %s" % (name, exc))
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        root = ET.fromstring(opf)
        ids = set()
        for item in root.find("opf:manifest", ns):
            ids.add(item.get("id"))
            if "OEBPS/" + item.get("href") not in names:
                problems.append("manifest : %s absent de l'archive" % item.get("href"))
        for ref in root.find("opf:spine", ns):
            if ref.get("idref") not in ids:
                problems.append("spine : idref inconnu %s" % ref.get("idref"))
        for name in [n for n in names if n.endswith(".xhtml")]:
            body = zf.read(name).decode("utf-8")
            for match in re.finditer(r'(?:src|href)="([^"#:]+)"', body):
                ref = match.group(1)
                if ref.startswith(("http", "gemini", "mailto", "gopher")):
                    continue
                if "OEBPS/" + ref not in names:
                    problems.append("%s : référence cassée %s" % (name, ref))
    return problems