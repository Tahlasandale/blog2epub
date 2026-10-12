#!/usr/bin/env python3
"""
blog2epub — compile une liste d'articles de blog en un seul EPUB 3,
un chapitre par article. Python stdlib uniquement (aucune installation).

    python3 blog2epub.py liens.txt -o livre.epub
    python3 blog2epub.py liens.txt --fetch-only
    python3 blog2epub.py liens.txt --list-missing

Pipeline : fetch -> extraction HTML -> Markdown (src/<slug>.md)
           -> traduction FR optionnelle (fr/<slug>.md)
           -> rendu XHTML -> images -> EPUB 3.
"""

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser

UA = "Mozilla/5.0 (X11; Linux x86_64) blog2epub/1.0 (+compilation personnelle hors ligne)"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}
SKIP = {"script", "style", "head", "noscript"}


# --------------------------------------------------------------------------
# 1. Micro-DOM
# --------------------------------------------------------------------------
class Node:
    __slots__ = ("tag", "attrs", "kids", "text")

    def __init__(self, tag, attrs=None, text=""):
        self.tag = tag
        self.attrs = attrs or {}
        self.kids = []
        self.text = text

    def find(self, tag):
        for k in self.kids:
            if k.tag == tag:
                return k
        return None

    def find_all(self, tag, deep=False):
        if not deep:
            return [k for k in self.kids if k.tag == tag]
        found = []
        for k in self.kids:
            if k.tag == tag:
                found.append(k)
            found.extend(k.find_all(tag, deep=True))
        return found

    def deep_find(self, tag):
        found = self.find_all(tag, deep=True)
        return found[0] if found else None


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            if tag != "head":
                self.skip += 1
            return
        if self.skip:
            return
        n = Node(tag, {k: (v if v is not None else "") for k, v in attrs})
        self.stack[-1].kids.append(n)
        if tag not in VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        if self.skip or tag in SKIP:
            return
        self.stack[-1].kids.append(Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag in SKIP:
            if tag != "head" and self.skip:
                self.skip -= 1
            return
        if self.skip:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self.skip or not data:
            return
        self.stack[-1].kids.append(Node("text", text=data))


def parse_html(source):
    p = Parser()
    p.feed(source)
    p.close()
    return p.root


# --------------------------------------------------------------------------
# 2. Fetch
# --------------------------------------------------------------------------
def fetch(url, retries=3, delay=1.0):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr,en;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
            return raw.decode("utf-8", "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            last = e
            time.sleep(delay * (attempt + 1))
    raise RuntimeError("échec de téléchargement %s : %s" % (url, last))


# --------------------------------------------------------------------------
# 3. HTML -> Markdown
# --------------------------------------------------------------------------
def collapse(text):
    return re.sub(r"\s+", " ", text)


def abs_url(base, href):
    if not href:
        return href
    if re.match(r"^(https?:|mailto:|gemini:|gopher:|data:|ftp:|//)", href):
        return href
    return urllib.parse.urljoin(base, href)


def inline_md(node, base):
    """Rend un noeud en Markdown inline."""
    out = []
    for k in node.kids:
        t = k.tag
        if t == "text":
            out.append(collapse(html.unescape(k.text)))
        elif t == "br":
            out.append("  \n")
        elif t in ("em", "i"):
            out.append("*%s*" % inline_md(k, base).strip())
        elif t in ("strong", "b"):
            out.append("**%s**" % inline_md(k, base).strip())
        elif t in ("code", "tt", "samp", "kbd"):
            txt = collapse(html.unescape("".join(x.text for x in k.kids if x.tag == "text")))
            if "`" in txt:
                out.append("<code>%s</code>" % html.escape(txt, quote=False))
            else:
                out.append("`%s`" % txt)
        elif t in ("sub", "sup"):
            inner = inline_md(k, base).strip()
            out.append("<%s>%s</%s>" % (t, inner, t))
        elif t == "a":
            href = abs_url(base, k.attrs.get("href", ""))
            txt = inline_md(k, base).strip() or href
            out.append("[%s](%s)" % (txt, href))
        elif t == "img":
            src = abs_url(base, k.attrs.get("src", ""))
            alt = collapse(html.unescape(k.attrs.get("alt", ""))).strip().replace("]", ")")
            out.append("![%s](%s)" % (alt, src))
        elif t in ("figure", "figcaption", "span", "small", "u", "mark", "abbr", "q"):
            out.append(inline_md(k, base))
        else:
            out.append(inline_md(k, base))
    return re.sub(r"[ \t]+", " ", "".join(out))


def raw_text(node):
    parts = []
    for k in node.kids:
        if k.tag == "text":
            parts.append(html.unescape(k.text))
        else:
            parts.append(raw_text(k))
    return "".join(parts)


def list_md(node, base, depth=0, ordered=False, index=0):
    pad = "  " * depth
    lines = []
    idx = index
    for li in node.kids:
        if li.tag != "li":
            continue
        idx += 1
        marker = ("%d. " % idx) if ordered else "- "
        inner_blocks = []
        loose = False
        for k in li.kids:
            if k.tag in ("ul", "ol"):
                loose = True
                inner_blocks.append(list_md(k, base, depth + 1, k.tag == "ol"))
            elif k.tag == "p":
                inner_blocks.append(inline_md(k, base).strip())
            else:
                t = one_md(k, base).strip()
                if t:
                    inner_blocks.append(t)
        inner_blocks = [b for b in inner_blocks if b]
        if not inner_blocks:
            continue
        if loose and len(inner_blocks) > 1:
            first, rest = inner_blocks[0], inner_blocks[1:]
            lines.append(pad + marker + first)
            for r in rest:
                lines.append("\n".join(pad + "  " + l.lstrip() if l else "" for l in r.split("\n")))
            lines.append("")
        else:
            body = " ".join(inner_blocks)
            lines.append(pad + marker + body.replace("\n", " "))
    return "\n".join(lines)


CONTAINERS = ("div", "section", "article", "main", "body", "center",
              "details", "summary", "header", "footer", "form", "td", "th")

INLINE_TAGS = ("a", "img", "code", "em", "strong", "b", "i", "sub", "sup",
               "tt", "span", "small", "br", "u", "mark", "abbr", "q")


def one_md(node, base):
    """Rend un noeud unique : dispatch inline si inline, sinon ses enfants."""
    if node.tag == "text":
        return collapse(html.unescape(node.text))
    if node.tag in INLINE_TAGS:
        fake = Node("span")
        fake.kids = [node]
        return inline_md(fake, base)
    out = []
    children_md(node, base, out)
    return "\n".join(out).strip()


def children_md(parent, base, out):
    """Rend tous les enfants bloc d'un conteneur."""
    for k in parent.kids:
        if k.tag == "text":
            txt = collapse(html.unescape(k.text)).strip()
            if txt:
                out.append(txt)
                out.append("")
        else:
            block_md(k, base, out)


def block_md(node, base, out):
    """Rend un noeud de bloc (titre, paragraphe, liste, code, figure...)."""
    t = node.tag
    if t == "text":
        txt = collapse(html.unescape(node.text)).strip()
        if txt:
            out.append(txt)
            out.append("")
    elif t in ("h1", "h2", "h3", "h4", "h5", "h6"):
        lvl = int(t[1])
        txt = inline_md(node, base).strip()
        if txt:
            out.append("#" * lvl + " " + txt)
            out.append("")
    elif t == "p":
        txt = inline_md(node, base).strip()
        if txt:
            out.append(txt)
            out.append("")
    elif t in ("ul", "ol"):
        md = list_md(node, base, ordered=(t == "ol"))
        if md.strip():
            out.append(md)
            out.append("")
    elif t == "pre":
        code = raw_text(node).strip("\n").replace("\r\n", "\n").rstrip()
        out.append("```")
        out.append(code)
        out.append("```")
        out.append("")
    elif t == "blockquote":
        inner = []
        children_md(node, base, inner)
        quote = "\n".join(inner).strip()
        out.extend("> " + l if l else ">" for l in quote.split("\n"))
        out.append("")
    elif t == "figure":
        caption = ""
        media = []
        for kk in node.kids:
            if kk.tag == "figcaption":
                caption = inline_md(kk, base).strip()
            elif kk.tag in ("img", "a", "p", "picture"):
                media.append(inline_md(kk, base).strip())
        for md in media:
            if md:
                out.append(md)
                out.append("")
        if caption:
            out.append("*%s*" % caption)
            out.append("")
    elif t == "hr":
        out.append("---")
        out.append("")
    elif t == "table":
        rows = []
        for tr in node.find_all("tr", deep=True):
            cells = [inline_md(td, base).strip().replace("|", "\\|")
                     for td in tr.kids if td.tag in ("td", "th")]
            if cells:
                rows.append(cells)
        for r_i, cells in enumerate(rows):
            out.append("| " + " | ".join(cells) + " |")
            if r_i == 0:
                out.append("| " + " | ".join(["---"] * len(cells)) + " |")
        out.append("")
    elif t == "dl":
        for kk in node.kids:
            if kk.tag in ("dt", "dd"):
                txt = inline_md(kk, base).strip()
                if txt:
                    out.append(("%s: " % txt) if kk.tag == "dt" else txt)
                    out.append("")
    elif t in CONTAINERS:
        children_md(node, base, out)
    else:
        md = inline_md(node, base).strip()
        if md:
            out.append(md)
            out.append("")


def date_from_text(md):
    """Filet de sécurité : cherche une date ISO dans le Markdown."""
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", md)
    return m.group(0) if m else ""


def clean_md(md):
    md = md.replace(" ", " ").replace(" ", " ")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"^ *\n", "", md)
    return md.strip() + "\n"


# --------------------------------------------------------------------------
# 4. Extraction d'un article
# --------------------------------------------------------------------------
class Article:
    def __init__(self):
        self.url = ""
        self.slug = ""
        self.lang = ""
        self.title = ""
        self.author = ""
        self.date = ""
        self.source_md = ""   # markdown extrait
        self.text_md = ""     # markdown final (traduit ou non)
        self.translated = False
        self.og_image = ""


def meta_of(root, name=None, prop=None):
    for m in root.find_all("meta", deep=True):
        a = m.attrs
        if name and a.get("name", "").lower() == name:
            return html.unescape(a.get("content", ""))
        if prop and a.get("property", "").lower() == prop:
            return html.unescape(a.get("content", ""))
    return ""


def extract(url, source):
    art = Article()
    art.url = url
    art.slug = os.path.basename(urllib.parse.urlparse(url).path) or uuid.uuid4().hex[:8]
    if art.slug.endswith(".html"):
        art.slug = art.slug[:-5]
    root = parse_html(source)

    art.title = meta_of(root, prop="og:title") or meta_of(root, name="title")
    if not art.title:
        h1 = root.deep_find("h1")
        art.title = inline_md(h1, url).strip() if h1 else art.slug
    art.title = collapse(art.title).strip()
    art.author = collapse(meta_of(root, prop="og:article:author")
                          or meta_of(root, prop="article:author")
                          or meta_of(root, name="author") or "").strip()
    art.date = (meta_of(root, prop="og:article:published_time")
                or meta_of(root, prop="article:published_time")
                or date_from_text(art.source_md) or "")[:10]
    html_node = root.deep_find("html")
    art.lang = (html_node.attrs.get("lang", "") if html_node else "")[:2].lower()
    art.og_image = abs_url(url, meta_of(root, prop="og:image"))

    body = root.deep_find("article") or root.deep_find("body") or root
    out = []
    signature_md = ""
    for k in list(body.kids):
        if "signature" in k.attrs.get("class", ""):
            sig = []
            block_md(k, url, sig)
            signature_md = clean_md("\n".join(sig))
            continue
        if k.tag == "h1":
            continue  # le titre devient l'en-tête de chapitre
        if k.tag == "p" and "subtitle" in k.attrs.get("class", ""):
            continue  # auteur/date repris en en-tête
        if k.tag == "img" and "header" in k.attrs.get("class", ""):
            continue  # logo décoratif
        block_md(k, url, out)
    art.source_md = clean_md("\n".join(out))
    art._signature_md = signature_md
    return art


# --------------------------------------------------------------------------
# 5. Markdown -> XHTML
# --------------------------------------------------------------------------
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


IMG_RE = re.compile(r'!\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)')
LINK_RE = re.compile(r'\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)')
CODE_RE = re.compile(r"`([^`]+)`")


def render_inline(text):
    codes = []

    def keep(m):
        codes.append(m.group(1))
        return "\x00%d\x00" % (len(codes) - 1)

    s = CODE_RE.sub(keep, text)
    s = esc(s)
    s = IMG_RE.sub(lambda m: '<img src="%s" alt="%s"/>' % (m.group(2), esc(m.group(1), ) if False else m.group(1).replace('"', "&quot;")), s)
    s = LINK_RE.sub(lambda m: '<a href="%s">%s</a>' % (m.group(2), m.group(1)), s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s, flags=re.S)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s, flags=re.S)
    s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s, flags=re.S)
    s = re.sub(r"<sub>", "<sub>", s)
    s = re.sub(r" {2}\n", "<br/>\n", s)
    for i, c in enumerate(codes):
        s = s.replace("\x00%d\x00" % i, "<code>%s</code>" % esc(c))
    return s.strip()


def md_to_body(md, img_map=None, id_prefix="c"):
    img_map = img_map or {}
    lines = md.replace("\r\n", "\n").split("\n")
    out = []
    i = 0
    n = len(lines)

    def flush_para(buf):
        text = "\n".join(buf).strip()
        if text:
            out.append("<p>%s</p>" % render_inline(text))

    para = []
    while i < n:
        line = lines[i]

        if line.startswith("```"):
            i += 1
            code = []
            while i < n and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>%s</code></pre>" % esc("\n".join(code)))
            continue

        if not line.strip():
            if para:
                flush_para(para)
                para = []
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if para:
                flush_para(para)
                para = []
            lvl = max(2, min(len(m.group(1)), 6))  # le h1 de l'article est l'en-tête
            anchor = "%s-h%d" % (id_prefix, len(out))
            out.append('<h%d id="%s">%s</h%d>' % (lvl, anchor, render_inline(m.group(2)), lvl))
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", line):
            if para:
                flush_para(para)
                para = []
            out.append("<hr/>")
            i += 1
            continue

        if line.lstrip().startswith(">"):
            if para:
                flush_para(para)
                para = []
            quote = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            inner = md_to_body("\n".join(quote), img_map, id_prefix)
            out.append("<blockquote>%s</blockquote>" % inner)
            continue

        if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
            if para:
                flush_para(para)
                para = []
            items = []
            while i < n:
                cur = lines[i]
                if not cur.strip():
                    nxt = lines[i + 1] if i + 1 < n else ""
                    if re.match(r"^\s*([-*+]|\d+\.)\s+", nxt):
                        i += 1
                        continue
                    break
                mm = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", cur)
                if not mm:
                    if items and cur.startswith((" ", "\t")):
                        items[-1][1] += "\n" + cur.strip()
                        i += 1
                        continue
                    break
                depth = len(mm.group(1)) // 2
                while len(items) <= depth:
                    items.append(["", []])
                items[depth][0] = "ol" if re.match(r"\d", mm.group(2)) else "ul"
                items[depth][1].append(mm.group(3))
                i += 1
            html_items = []
            for tag, its in items:
                if not its:
                    continue
                lis = "".join("<li>%s</li>" % render_inline(t) for t in its)
                html_items.append("<%s>%s</%s>" % (tag, lis, tag))
            out.append("".join(html_items))
            continue

        para.append(line)
        i += 1

    if para:
        flush_para(para)

    body = "\n".join(out)
    if img_map:
        body = re.sub(r'(<img src=")([^"]+)(")',
                      lambda m: m.group(1) + img_map.get(m.group(2), m.group(2)) + m.group(3), body)
    return body


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


# --------------------------------------------------------------------------
# 6. Images
# --------------------------------------------------------------------------
def image_ext(data, ctype, url):
    exts = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"}
    base = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if base in exts:
        return base
    if "png" in (ctype or ""):
        return ".png"
    if "gif" in (ctype or ""):
        return ".gif"
    if "svg" in (ctype or ""):
        return ".svg"
    return ".jpg"


def to_jpeg(data, ext, dest):
    """Convertit en JPEG via ImageMagick si disponible (lisibilité maximale)."""
    if ext in (".jpg", ".jpeg"):
        with open(dest, "wb") as f:
            f.write(data)
        return True
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        return False
    tmp = os.path.join(os.path.dirname(dest), "_tmp" + ext)
    with open(tmp, "wb") as f:
        f.write(data)
    cmd = [magick, "-background", "white", tmp, "-flatten", "-quality", "88", dest]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=90)
        ok = r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0
    except Exception:
        ok = False
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return ok


# --------------------------------------------------------------------------
# 7. Assemblage EPUB 3
# --------------------------------------------------------------------------
CSS = """@charset "utf-8";
body { margin: 0 5%; line-height: 1.5; font-family: serif; }
h1 { font-size: 1.5em; line-height: 1.25; margin: 1.2em 0 .2em 0; text-align: center; }
h2 { font-size: 1.15em; margin: 1.6em 0 .4em 0; border-bottom: 1px solid #999; padding-bottom: .2em; }
h3 { font-size: 1.02em; margin: 1.2em 0 .3em 0; }
p { margin: .55em 0; text-align: justify; hyphens: auto; }
.chapter-meta { text-align: center; font-style: italic; color: #555; font-size: .85em; margin-bottom: 1.6em; }
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
p > img + em, p + p > em { display: block; text-align: center; font-size: .8em; color: #666; }
hr { border: 0; border-top: 1px solid #ccc; margin: 1.6em auto; width: 40%; }
a { color: #169; }
.cover-page { margin: 0; padding: 0; text-align: center; }
.cover-page img { max-height: 100%; max-width: 100%; margin: 0; }
.cover-page h1 { margin-top: 1.5em; }
.cover-page .sub { font-style: italic; color: #555; }
.about { font-size: .9em; color: #444; }
"""


def xhtml_page(title, body, lang="fr", css="style.css"):
    return XHTML_TMPL.format(lang=lang, title=esc(title), css=css, body=body)


def build_epub(arts, out_path, book_title, book_author, cover_url, lang="fr",
               about_md=None, date_str=None):
    tmpdir = out_path + ".build"
    if os.path.isdir(tmpdir):
        shutil.rmtree(tmpdir)
    os.makedirs(os.path.join(tmpdir, "META-INF"))
    os.makedirs(os.path.join(tmpdir, "OEBPS", "images"))

    uid = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, book_title + out_path))
    now = (date_str or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    # --- images (téléchargement + conversion, une seule fois par URL) -------
    img_cache = {}   # url -> (filename, data)
    counters = {}

    def add_image(url):
        nonlocal counters
        if url in img_cache:
            return img_cache[url][0]
        data = None
        ctype = ""
        if url.startswith("http") and not url.startswith("https://ploum.net/gemini"):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=45) as r:
                    data = r.read()
                    ctype = r.headers.get("Content-Type", "")
            except Exception as e:
                print("    ! image ignorée (%s) : %s" % (url, e))
        base = os.path.splitext(os.path.basename(urllib.parse.urlparse(url).path))[0]
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", base)[:40] or "img"
        ext = image_ext(data or b"", ctype, url)
        counters[base] = counters.get(base, 0) + 1
        name = "%s-%d%s" % (base, counters[base], ".jpg")
        dest = os.path.join(tmpdir, "OEBPS", "images", name)
        if data is None:
            return None
        if not to_jpeg(data, ext, dest):
            with open(dest, "wb") as f:  # repli : format d'origine
                f.write(data)
        img_cache[url] = (name, None)
        return name

    # --- couverture --------------------------------------------------------
    cover_name = None
    if cover_url:
        cover_name = add_image(cover_url)
    if not cover_name:
        for a in arts:
            m = IMG_RE.search(a.text_md)
            if m:
                cover_name = add_image(m.group(2))
                if cover_name:
                    break

    # --- chapitres ---------------------------------------------------------
    files = []      # (href, id, media-type, properties)
    nav_items = []
    ncx_items = []
    chapters = []

    if cover_name:
        cover_body = (
            '<section class="cover-page" epub:type="cover">'
            '<img src="images/%s" alt="Couverture"/></section>' % cover_name)
        with open(os.path.join(tmpdir, "OEBPS", "cover.xhtml"), "w", encoding="utf-8") as f:
            f.write(xhtml_page(book_title, cover_body))
        files.append(("cover.xhtml", "cover", "application/xhtml+xml", ""))
        nav_items.append('<li><a href="cover.xhtml">Couverture</a></li>')

    for idx, art in enumerate(arts, start=1):
        # carte des images du chapitre
        img_map = {}
        for m in IMG_RE.finditer(art.text_md):
            name = add_image(m.group(2))
            if name:
                img_map[m.group(2)] = "images/%s" % name
        body_md = md_to_body(art.text_md, img_map, id_prefix="ch%d" % idx)

        short_author = art.author.split(" - ")[0].strip() if art.author else ""
        meta = "par %s" % short_author if short_author else ""
        if art.date:
            meta = ("%s — %s" % (meta, art.date)) if meta else art.date
        parts = []
        parts.append('<h1 id="ch%d-t">%s</h1>' % (idx, render_inline(art.title)))
        if meta:
            parts.append('<p class="chapter-meta">%s</p>' % esc(meta))
        parts.append(body_md)
        parts.append('<p class="source">Source : <a href="%s">%s</a><br/>'
                     '<a href="gemini://%s%s.gmi">version gemlog</a></p>'
                     % (art.url, esc(art.url), urllib.parse.urlparse(art.url).netloc,
                        urllib.parse.urlparse(art.url).path.lstrip("/").replace(".html", "")))

        body = "\n".join(parts)
        href = "chap%02d.xhtml" % idx
        with open(os.path.join(tmpdir, "OEBPS", href), "w", encoding="utf-8") as f:
            f.write(xhtml_page(art.title, body))
        files.append((href, "chap%02d" % idx, "application/xhtml+xml", ""))
        nav_items.append('<li><a href="%s">%s</a></li>' % (href, esc(art.title)))
        ncx_items.append((art.title, href, idx))
        chapters.append(art.title)

    if about_md:
        body = '<h1 id="about-t">À propos</h1>%s' % md_to_body(about_md, {}, "about")
        with open(os.path.join(tmpdir, "OEBPS", "about.xhtml"), "w", encoding="utf-8") as f:
            f.write(xhtml_page("À propos", body))
        files.append(("about.xhtml", "about", "application/xhtml+xml", ""))
        nav_items.append('<li><a href="about.xhtml">À propos de l’auteur</a></li>')

    # images ducover en propriété
    image_files = sorted(os.listdir(os.path.join(tmpdir, "OEBPS", "images")))
    for name in image_files:
        props = "cover-image" if name == cover_name else ""
        files.append(("images/" + name, "img-" + re.sub(r"[^A-Za-z0-9]", "", name),
                      "image/jpeg", props))

    with open(os.path.join(tmpdir, "OEBPS", "style.css"), "w", encoding="utf-8") as f:
        f.write(CSS)

    # --- nav.xhtml ---------------------------------------------------------
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
    with open(os.path.join(tmpdir, "OEBPS", "nav.xhtml"), "w", encoding="utf-8") as f:
        f.write(nav)
    files.append(("nav.xhtml", "nav", "application/xhtml+xml", "nav"))

    # --- toc.ncx -----------------------------------------------------------
    points = []
    for title, href, idx in ncx_items:
        points.append(
            '<navPoint id="np%02d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
            '<content src="%s"/></navPoint>' % (idx, idx, esc(title), href))
    if about_md:
        points.append('<navPoint id="np-about" playOrder="999"><navLabel><text>À propos</text>'
                      '</navLabel><content src="about.xhtml"/></navPoint>')
    ncx = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content="{uid}"/><meta name="dtb:depth" content="1"/>
<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>
<docTitle><text>{title}</text></docTitle>
<navMap>
{points}
</navMap>
</ncx>
""".format(uid=uid, title=esc(book_title), points="\n".join(points))
    with open(os.path.join(tmpdir, "OEBPS", "toc.ncx"), "w", encoding="utf-8") as f:
        f.write(ncx)
    files.append(("toc.ncx", "ncx", "application/x-dtbncx+xml", ""))

    # --- content.opf -------------------------------------------------------
    desc = ("Compilation hors ligne de %d articles du blog ploum.net, un article par "
            "chapitre. Chaque chapitre renvoie à sa source originale." % len(arts))
    manifest = "\n".join(
        '  <item id="%s" href="%s" media-type="%s"%s/>'
        % (i, h, m, (' properties="%s"' % p) if p else "")
        for h, i, m, p in files)
    spine = "\n".join('  <itemref idref="%s"/>' % i for h, i, m, p in files
                      if m == "application/xhtml+xml")
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
  <dc:source>ploum.net</dc:source>
  <dc:rights>Textes © Ploum (Lionel Dricot) — compilation personnelle hors ligne ; chaque chapitre renvoie à l'original sur ploum.net.</dc:rights>
  <meta property="dcterms:modified">{now}</meta>
</metadata>
<manifest>
{manifest}
</manifest>
<spine toc="ncx">
{spine}
</spine>
</package>
""".format(lang=lang, uid=uid, title=esc(book_title), author=esc(book_author), now=now,
           desc=esc(desc), manifest=manifest, spine=spine)
    with open(os.path.join(tmpdir, "OEBPS", "content.opf"), "w", encoding="utf-8") as f:
        f.write(opf)

    with open(os.path.join(tmpdir, "META-INF", "container.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n'
                '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                '  <rootfiles>\n    <rootfile full-path="OEBPS/content.opf" '
                'media-type="application/oebps-package+xml"/>\n  </rootfiles>\n</container>\n')

    # --- zip ---------------------------------------------------------------
    with zipfile.ZipFile(out_path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        for root, _dirs, files_ in os.walk(tmpdir):
            for name in sorted(files_):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, tmpdir).replace(os.sep, "/")
                z.write(full, rel, zipfile.ZIP_DEFLATED)
    shutil.rmtree(tmpdir)
    return chapters


# --------------------------------------------------------------------------
# 8. Vérifications
# --------------------------------------------------------------------------
def verify(path):
    import xml.etree.ElementTree as ET
    problems = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if z.namelist()[0] != "mimetype":
            problems.append("mimetype n'est pas la première entrée")
        info = z.getinfo("mimetype")
        if info.compress_type != zipfile.ZIP_STORED:
            problems.append("mimetype n'est pas stocké sans compression")
        for n in sorted(names):
            if n.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                try:
                    ET.fromstring(z.read(n))
                except Exception as e:
                    problems.append("XML invalide %s : %s" % (n, e))
        opf = z.read("OEBPS/content.opf").decode("utf-8")
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        root = ET.fromstring(opf)
        for item in root.find("opf:manifest", ns):
            href = item.get("href")
            if "OEBPS/" + href not in names:
                problems.append("manifest: %s absent de l'archive" % href)
        spine = root.find("opf:spine", ns)
        for ref in spine:
            idref = ref.get("idref")
            if not any(i.get("id") == idref for i in root.find("opf:manifest", ns)):
                problems.append("spine: idref inconnu %s" % idref)
        for n in [x for x in names if x.endswith(".xhtml")]:
            body = z.read(n).decode("utf-8")
            for m in re.finditer(r'(?:src|href)="([^"#:]+)"', body):
                ref = m.group(1)
                if ref.startswith("http") or ref.startswith("gemini") or ref.startswith("mailto"):
                    continue
                if "OEBPS/" + ref not in names:
                    problems.append("%s: référence cassée %s" % (n, ref))
    return problems


# --------------------------------------------------------------------------
# 8b. Contrôle des traductions
# --------------------------------------------------------------------------
EN_FUNCTION_WORDS = (
    "the", "and", "you", "your", "with", "that", "this", "from", "have", "will",
    "which", "they", "been", "were", "their", "there", "about", "would", "could",
    "should", "when", "what", "where", "than", "then", "them", "these", "those",
    "very", "just", "into", "over", "such", "some", "more", "most", "other",
    "because", "while", "after", "before", "again", "being", "does", "doing",
)


def structure_of(md):
    return {
        "titres": len(re.findall(r"^#{1,6}\s", md, re.M)),
        "liens": len(re.findall(r"(?<!\!)\[[^\]]*\]\(", md)),
        "images": len(re.findall(r"!\[[^\]]*\]\(", md)),
        "codes": md.count("```") // 2,
        "citations": len(re.findall(r"^>\s", md, re.M)),
        "puces": len(re.findall(r"^\s*[-*+]\s", md, re.M)),
        "mots": len(md.split()),
    }


def lint_fr(src_md, fr_md):
    """Compare la structure source/traduction et cherche les fautes de saisie."""
    issues = []
    s, f = structure_of(src_md), structure_of(fr_md)
    for key in ("titres", "liens", "images", "codes", "citations", "puces"):
        if s[key] != f[key]:
            issues.append("%s : source=%d traduction=%d" % (key, s[key], f[key]))
    ratio = f["mots"] / max(s["mots"], 1)
    if not (0.75 <= ratio <= 1.35):
        issues.append("longueur suspecte : %d mots source pour %d mots FR" % (s["mots"], f["mots"]))
    # caractères non latins : contamination ou texte non traduits
    for i, line in enumerate(fr_md.split("\n"), 1):
        bad = re.findall(r"[^\x00-\x7F\u00A0-\u024F\u2010-\u203A\u20AC]", line)
        if bad:
            issues.append("ligne %d : caractères non latins %s" % (i, "".join(sorted(set(bad)))))
    # placeholders de génération
    for pat in (r"\[Pardon", r"\[Stop\]", r"\[Reprise", r"\{\{", r"\}\}"):
        if re.search(pat, fr_md):
            issues.append("placeholder de génération résiduel : %s" % pat)
    # mots de fonction anglais isolés (traduction partielle / contamination)
    for line in fr_md.split("\n"):
        stripped = re.sub(r"`[^`]*`|\[[^\]]*\]\([^)]*\)|https?://\S+", "", line)
        words = re.findall(r"[A-Za-z']+", stripped.lower())
        runs = 0
        for w in words:
            runs = runs + 1 if w in EN_FUNCTION_WORDS else 0
            if runs >= 3:
                issues.append("anglais résiduel : « %s »" % line.strip()[:70])
                break
    return issues


# --------------------------------------------------------------------------
# 9. CLI
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Compiler des articles de blog en un EPUB.")
    ap.add_argument("links", help="fichier texte (une URL par ligne) ou '-' pour stdin")
    ap.add_argument("-o", "--out", default="livre.epub")
    ap.add_argument("--title", default="Ploum.net — Anthologie 2025-2026")
    ap.add_argument("--author", default="Ploum (Lionel Dricot)")
    ap.add_argument("--lang", default="fr")
    ap.add_argument("--order", default="desc", choices=["desc", "asc", "given"],
                    help="desc = antichronologique (défaut), asc = chronologique, given = ordre du fichier")
    ap.add_argument("--cover", default=None, help="URL ou chemin local d'une image de couverture")
    ap.add_argument("--refresh", action="store_true", help="re-télécharger et ré-extraire les sources")
    ap.add_argument("--fetch-only", action="store_true", help="extraire les Markdown et s'arrêter")
    ap.add_argument("--list-missing", action="store_true", help="lister les traductions manquantes")
    ap.add_argument("--check-fr", action="store_true", help="contrôler les traductions existantes")
    ap.add_argument("--strict", action="store_true", help="échouer si une traduction manque")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(here, "src")
    fr_dir = os.path.join(here, "fr")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(fr_dir, exist_ok=True)

    raw = sys.stdin.read() if args.links == "-" else open(args.links, encoding="utf-8").read()
    urls = [u.strip() for u in re.split(r"[\s,]+", raw) if u.strip().startswith("http")]
    if not urls:
        print("aucune URL trouvée", file=sys.stderr)
        return 2

    arts = []
    for url in urls:
        slug = os.path.basename(urllib.parse.urlparse(url).path)
        if slug.endswith(".html"):
            slug = slug[:-5]
        src_path = os.path.join(src_dir, slug + ".md")
        meta_path = os.path.join(src_dir, slug + ".meta")

        if args.refresh or not os.path.exists(src_path):
            print("→ %s" % url)
            try:
                source = fetch(url)
            except Exception as e:
                print("  ! %s" % e, file=sys.stderr)
                continue
            art = extract(url, source)
            with open(src_path, "w", encoding="utf-8") as f:
                f.write(art.source_md)
            sig = getattr(art, "_signature_md", "")
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write("url: %s\nlang: %s\ntitle: %s\nauthor: %s\ndate: %s\n"
                        "cover: %s\nsig: %s\n" % (art.url, art.lang, art.title, art.author,
                                                  art.date, art.og_image,
                                                  "oui" if sig else "non"))
            if sig:
                with open(os.path.join(src_dir, slug + ".about.md"), "w", encoding="utf-8") as f:
                    f.write(sig)
        else:
            print("· (cache) %s" % slug)
            art = Article()
            art.url = url
            art.slug = slug
            info = dict()
            if os.path.exists(meta_path):
                for line in open(meta_path, encoding="utf-8"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        info[k.strip()] = v.strip()
            art.lang = info.get("lang", "")
            art.title = info.get("title", slug)
            art.author = info.get("author", "")
            art.date = info.get("date", "")
            art.og_image = info.get("cover", "")
            art.source_md = open(src_path, encoding="utf-8").read()
            art._signature_md = ""
        arts.append(art)

    if args.fetch_only:
        print("\n%d articles extraits dans %s/" % (len(arts), src_dir))
        return 0

    # traductions (fichier fr/<slug>.md, front matter optionnel pour le titre)
    missing = []
    for art in arts:
        fr_path = os.path.join(fr_dir, art.slug + ".md")
        if os.path.exists(fr_path):
            body = open(fr_path, encoding="utf-8").read().strip()
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", body, re.S)
            if m:
                for line in m.group(1).split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        if k.strip() == "title":
                            art.title = v.strip().strip('"')
                        elif k.strip() == "date":
                            art.date = v.strip()
                body = m.group(2).strip()
            art.text_md = body
            art.translated = art.lang != "fr"
        else:
            art.text_md = art.source_md
            if art.lang != "fr":
                missing.append((art.slug, art.title))

    if args.list_missing:
        for slug, title in missing:
            print("MANQUE %s — %s" % (slug, title))
        print("\n%d/%d traductions manquantes" % (len(missing), len(arts)))
        return 1 if missing and args.strict else 0

    if args.check_fr:
        ok = True
        for art in arts:
            if not art.translated:
                continue
            issues = lint_fr(art.source_md, art.text_md)
            if issues:
                ok = False
                print("✗ %s" % art.slug)
                for i in issues:
                    print("    - %s" % i)
            else:
                s = structure_of(art.source_md)
                print("✓ %s (%d mots FR pour %d mots source)"
                      % (art.slug, structure_of(art.text_md)["mots"], s["mots"]))
        return 0 if ok else 1

    if missing and args.strict:
        print("traductions manquantes : %s" % ", ".join(s for s, _ in missing), file=sys.stderr)
        return 1

    if args.order == "desc":
        arts.sort(key=lambda a: a.date, reverse=True)
    elif args.order == "asc":
        arts.sort(key=lambda a: a.date)

    cover = args.cover
    if not cover:
        for art in arts:
            if getattr(art, "og_image", ""):
                cover = art.og_image
                break

    about = ""
    for art in arts:
        p = os.path.join(src_dir, art.slug + ".about.md")
        if os.path.exists(p):
            about = open(p, encoding="utf-8").read()
            break

    chapters = build_epub(arts, args.out, args.title, args.author, cover, args.lang, about)
    problems = verify(args.out)
    size = os.path.getsize(args.out) / 1024.0
    print("\n%s — %d chapitres, %.0f Ko" % (args.out, len(chapters), size))
    for c in chapters:
        print("   · %s" % c)
    if missing:
        print("\n(!) %d chapitre(s) en anglais faute de traduction : %s"
              % (len(missing), ", ".join(s for s, _ in missing)))
    if problems:
        print("\nPROBLÈMES :")
        for p in problems:
            print("  - %s" % p)
        return 1
    print("\n✓ vérifications EPUB 3 passées")
    return 0


if __name__ == "__main__":
    sys.exit(main())