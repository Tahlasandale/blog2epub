"""Conversion HTML vers Markdown, et Markdown vers HTML (pour l'EPUB)."""

import html
import re

from .dom import CONTAINERS, INLINE_TAGS, Node

# --------------------------------------------------------------------------
# HTML -> Markdown
# --------------------------------------------------------------------------


def collapse(text):
    return re.sub(r"\s+", " ", text)


def abs_url(base, href):
    if not href:
        return href
    if re.match(r"^(https?:|mailto:|gemini:|gopher:|data:|ftp:|//|#)", href):
        return href
    import urllib.parse
    return urllib.parse.urljoin(base, href)


def inline_md(node, base):
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
            out.append("<code>%s</code>" % html.escape(txt, quote=False)
                       if "`" in txt else "`%s`" % txt)
        elif t in ("sub", "sup"):
            out.append("<%s>%s</%s>" % (t, inline_md(k, base).strip(), t))
        elif t == "a":
            href = abs_url(base, k.attrs.get("href", ""))
            txt = inline_md(k, base).strip() or href
            out.append("[%s](%s)" % (txt, href))
        elif t == "img":
            src = abs_url(base, k.attrs.get("src", ""))
            alt = collapse(html.unescape(k.attrs.get("alt", ""))).strip().replace("]", ")")
            out.append("![%s](%s)" % (alt, src))
        elif t in ("del", "s"):
            out.append("~~%s~~" % inline_md(k, base).strip())
        else:
            out.append(inline_md(k, base))
    return re.sub(r"[ \t]+", " ", "".join(out))


def one_md(node, base):
    """Rend un nœud unique : dispatch inline si inline, sinon ses enfants."""
    if node.tag == "text":
        return collapse(html.unescape(node.text))
    if node.tag in INLINE_TAGS:
        wrapper = Node("span")
        wrapper.kids = [node]
        return inline_md(wrapper, base)
    out = []
    children_md(node, base, out)
    return "\n".join(out).strip()


def list_md(node, base, depth=0, ordered=False):
    pad = "  " * depth
    lines = []
    index = 0
    for li in node.kids:
        if li.tag != "li":
            continue
        index += 1
        marker = ("%d. " % index) if ordered else "- "
        blocks = []
        loose = False
        for k in li.kids:
            if k.tag in ("ul", "ol"):
                loose = True
                blocks.append(list_md(k, base, depth + 1, k.tag == "ol"))
            elif k.tag == "text":
                txt = collapse(html.unescape(k.text)).strip()
                if txt:
                    blocks.append(txt)
            else:
                blocks.append(one_md(k, base).strip())
        blocks = [b for b in blocks if b]
        if not blocks:
            continue
        if loose and len(blocks) > 1:
            lines.append(pad + marker + blocks[0])
            for extra in blocks[1:]:
                lines.append("\n".join(pad + "  " + l.lstrip() if l else ""
                                       for l in extra.split("\n")))
            lines.append("")
        else:
            lines.append(pad + marker + " ".join(blocks).replace("\n", " "))
    return "\n".join(lines)


def children_md(parent, base, out):
    for k in parent.kids:
        if k.tag == "text":
            txt = collapse(html.unescape(k.text)).strip()
            if txt:
                out.append(txt)
                out.append("")
        else:
            block_md(k, base, out)


def block_md(node, base, out):
    t = node.tag
    if t == "text":
        txt = collapse(html.unescape(node.text)).strip()
        if txt:
            out.append(txt)
            out.append("")
    elif re.fullmatch(r"h[1-6]", t):
        txt = inline_md(node, base).strip()
        if txt:
            out.append("#" * int(t[1]) + " " + txt)
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
        code = node.text_of().strip("\n").replace("\r\n", "\n").rstrip()
        out.append("```")
        out.append(code)
        out.append("```")
        out.append("")
    elif t == "blockquote":
        inner = []
        children_md(node, base, inner)
        quote = "\n".join(inner).strip()
        out.extend("> " + line if line else ">" for line in quote.split("\n"))
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
        for tr in node.find_all("tr"):
            cells = [inline_md(td, base).strip().replace("|", "\\|")
                     for td in tr.kids if td.tag in ("td", "th")]
            if cells:
                rows.append(cells)
        for i, cells in enumerate(rows):
            out.append("| " + " | ".join(cells) + " |")
            if i == 0:
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


def clean_md(md):
    md = md.replace(" ", " ").replace(" ", " ")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"^ *\n", "", md)
    return md.strip() + "\n"


# --------------------------------------------------------------------------
# Markdown -> HTML
# --------------------------------------------------------------------------

IMG_RE = re.compile(r'!\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)')
LINK_RE = re.compile(r'\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)')
CODE_RE = re.compile(r"`([^`]+)`")


def esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_inline(text):
    codes = []

    def stash(match):
        codes.append(match.group(1))
        return "\x00%d\x00" % (len(codes) - 1)

    s = CODE_RE.sub(stash, text)
    s = esc(s)
    s = IMG_RE.sub(lambda m: '<img src="%s" alt="%s"/>'
                  % (m.group(2), m.group(1).replace('"', "&quot;")), s)
    s = LINK_RE.sub(lambda m: '<a href="%s">%s</a>' % (m.group(2), m.group(1)), s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s, flags=re.S)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s, flags=re.S)
    s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s, flags=re.S)
    s = re.sub(r" {2}\n", "<br/>\n", s)
    for i, code in enumerate(codes):
        s = s.replace("\x00%d\x00" % i, "<code>%s</code>" % esc(code))
    return s.strip()


def md_to_html(md, img_map=None, id_prefix="c"):
    img_map = img_map or {}
    lines = md.replace("\r\n", "\n").split("\n")
    out = []
    para = []
    i = 0
    n = len(lines)

    def flush(buf):
        text = "\n".join(buf).strip()
        if text:
            out.append("<p>%s</p>" % render_inline(text))

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
            flush(para)
            para = []
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush(para)
            para = []
            level = max(2, min(len(heading.group(1)), 6))
            out.append('<h%d id="%s-h%d">%s</h%d>'
                       % (level, id_prefix, len(out),
                          render_inline(heading.group(2)), level))
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", line):
            flush(para)
            para = []
            out.append("<hr/>")
            i += 1
            continue

        if line.lstrip().startswith(">"):
            flush(para)
            para = []
            quote = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>%s</blockquote>" % md_to_html("\n".join(quote),
                                                                  img_map, id_prefix))
            continue

        if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
            flush(para)
            para = []
            items = []
            while i < n:
                current = lines[i]
                if not current.strip():
                    nxt = lines[i + 1] if i + 1 < n else ""
                    if re.match(r"^\s*([-*+]|\d+\.)\s+", nxt):
                        i += 1
                        continue
                    break
                match = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", current)
                if not match:
                    if items and current.startswith((" ", "\t")):
                        items[-1][1].append(current.strip())
                        i += 1
                        continue
                    break
                depth = len(match.group(1)) // 2
                while len(items) <= depth:
                    items.append(["", []])
                items[depth][0] = "ol" if re.match(r"\d", match.group(2)) else "ul"
                items[depth][1].append(match.group(3))
                i += 1
            rendered = []
            for tag, values in items:
                if not values:
                    continue
                lis = "".join("<li>%s</li>" % render_inline(v) for v in values)
                rendered.append("<%s>%s</%s>" % (tag, lis, tag))
            out.append("".join(rendered))
            continue

        para.append(line)
        i += 1

    flush(para)
    body = "\n".join(out)
    if img_map:
        body = re.sub(r'(<img src=")([^"]+)(")',
                      lambda m: m.group(1) + img_map.get(m.group(2), m.group(2)) + m.group(3),
                      body)
    return body