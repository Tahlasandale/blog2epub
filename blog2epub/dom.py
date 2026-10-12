"""Micro-DOM HTML et sélecteurs CSS.

Aucune dépendance : le parseur s'appuie sur html.parser et les sélecteurs sur un
moteur minimal supportant `tag`, `.classe`, `#id`, `tag.classe`, le combinateur
descendant (espace) et les listes (virgule).
"""

import re
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}
SKIP = {"script", "style", "noscript", "svg", "head"}
CONTAINERS = ("div", "section", "article", "main", "body", "center", "details",
              "summary", "header", "footer", "form", "td", "th", "li", "ul", "ol",
              "blockquote", "figure", "figcaption", "pre", "table", "tr", "dl", "p")
INLINE_TAGS = ("a", "img", "code", "em", "strong", "b", "i", "sub", "sup",
               "tt", "span", "small", "br", "u", "mark", "abbr", "q", "s")


class Node:
    __slots__ = ("tag", "attrs", "kids", "text", "parent")

    def __init__(self, tag, attrs=None, text=""):
        self.tag = tag
        self.attrs = attrs or {}
        self.kids = []
        self.text = text
        self.parent = None

    def walk(self):
        yield self
        for k in self.kids:
            if k.tag != "text":
                yield from k.walk()

    def find_all(self, tag):
        return [n for n in self.walk() if n.tag == tag]

    def text_of(self):
        parts = []
        for k in self.kids:
            parts.append(k.text if k.tag == "text" else k.text_of())
        return "".join(parts)

    def classes(self):
        return set(self.attrs.get("class", "").split())


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.skip = 0

    def _add(self, node):
        node.parent = self.stack[-1]
        self.stack[-1].kids.append(node)

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            if tag != "head":
                self.skip += 1
            return
        if self.skip:
            return
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs})
        self._add(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if self.skip or tag in SKIP:
            return
        self._add(Node(tag, dict(attrs)))

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
        node = Node("text", text=data)
        node.parent = self.stack[-1]
        self.stack[-1].kids.append(node)


def parse_html(source):
    p = Parser()
    p.feed(source)
    p.close()
    return p.root


# --------------------------------------------------------------------------
# Sélecteurs
# --------------------------------------------------------------------------
_COMPOUND = re.compile(r"^([a-zA-Z][\w-]*)?((?:[.#][\w-]+)*)$")


def parse_compound(token):
    m = _COMPOUND.match(token)
    if not m:
        return "*", [], []
    tag = m.group(1) or "*"
    rest = m.group(2) or ""
    classes = re.findall(r"\.([\w-]+)", rest)
    ids = re.findall(r"#([\w-]+)", rest)
    return tag, classes, ids


def match_compound(node, spec):
    tag, classes, ids = spec
    if tag != "*" and node.tag != tag:
        return False
    if ids and node.attrs.get("id") not in ids:
        return False
    if classes and not set(classes) <= node.classes():
        return False
    return True


def select(root, selector):
    """Renvoie les nœuds correspondant au sélecteur, dans l'ordre du document."""
    order = {id(n): i for i, n in enumerate(root.walk())}
    found = []
    seen = set()
    for group in selector.split(","):
        tokens = group.split()
        if not tokens:
            continue
        candidates = [n for n in root.walk() if match_compound(n, parse_compound(tokens[-1]))]
        for token in reversed(tokens[:-1]):
            spec = parse_compound(token)
            kept = []
            for node in candidates:
                anc = node.parent
                while anc is not None:
                    if match_compound(anc, spec):
                        kept.append(node)
                        break
                    anc = anc.parent
            candidates = kept
        for node in candidates:
            if id(node) not in seen:
                seen.add(id(node))
                found.append(node)
    found.sort(key=lambda n: order[id(n)])
    return found


def select_first(root, selector):
    nodes = select(root, selector)
    return nodes[0] if nodes else None