"""Interface à invites : curses si un terminal est disponible, REPL sinon.

Les deux modes partagent les mêmes commandes et le même état, de sorte qu'un
script headless et une session interactive se comportent pareil.
"""

import curses
import os
import shutil
import subprocess
import sys
import time

from . import feeds as feeds_mod
from . import translate as translate_mod
from .extract import slug_for

HELP = [
    ("a", "ajouter les URL du champ de saisie à la liste"),
    ("d", "télécharger, extraire et archiver les articles manquants"),
    ("t", "traduire l'article sous le curseur (ouvre $EDITOR)"),
    ("o", "importer les articles récents d'un export OPML"),
    ("b", "construire l'EPUB (demande un titre)"),
    ("x", "retirer l'article sous le curseur"),
    ("/", "filtrer la liste"),
    ("j / k", "descendre / remonter"),
    ("g / G", "haut / bas de liste"),
    ("Entrée", "valider la saisie"),
    ("q", "quitter"),
]

STATUS_ORDER = ["nouveau", "récupéré", "à traduire", "traduit", "publié"]


class Item:
    """Un article suivi par la session."""

    def __init__(self, url):
        self.url = url
        self.slug = slug_for(url)
        self.title = ""
        self.date = ""
        self.lang = ""
        self.state = "nouveau"
        self.keep = True
        self.note = ""

    def refresh(self, project):
        entry = project.catalog.get(self.url)
        if entry is None:
            self.title = self.url
            self.state = "nouveau"
            return
        self.title = entry.get("title") or self.url
        self.date = entry.get("date", "")
        self.lang = entry.get("lang", "")
        self.slug = entry.get("slug", self.slug)
        published = bool(entry.get("epubs"))
        translated = project.has_translation(self.slug)
        if translated:
            self.state = "publié" if published else "traduit"
        elif self.lang and self.lang != "fr":
            self.state = "publié" if published else "à traduire"
        else:
            self.state = "publié" if published else "récupéré"


def _editor():
    return os.environ.get("EDITOR") or shutil.which("vi") or "vi"


# --------------------------------------------------------------------------
# REPL : repli quand aucun terminal n'est disponible
# --------------------------------------------------------------------------
def run_repl(project, seed=None):
    items = [Item(u) for u in (seed or [])]
    for item in items:
        item.refresh(project)
    print("blog2epub — mode invites (pas de terminal). « ? » pour l'aide, « q » pour quitter.")
    while True:
        _show(items)
        try:
            line = input("url> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        command, _, rest = line.partition(" ")
        rest = rest.strip()
        if command == "q":
            return 0
        if command == "?":
            for key, label in HELP:
                print("  %-8s %s" % (key, label))
        elif command == "a":
            new = [Item(u) for u in rest.split() if u.startswith("http")]
            items.extend(new)
            for item in new:
                item.refresh(project)
        elif command == "d":
            _do_fetch(project, items)
        elif command == "t":
            _do_translate_one(project, items[0] if items else None)
        elif command == "b":
            return _do_build(project, items, interactive=True)
        elif command == "o":
            _do_opml(project, rest)
        elif command == "x":
            if items:
                items.pop(0)
        elif command == "l":
            _show_long(items)
        else:
            print("commande inconnue : %s (tapez ?)" % command)


def _show(items, index=0):
    for position, item in enumerate(items, 1):
        mark = "+" if item.keep else " "
        print("%2d %s [%-11s] %-10s %s" % (position, mark, item.state, item.date,
                                          item.title[:56] or item.url))
    print("%d article(s)" % len(items))


def _show_long(items):
    for position, item in enumerate(items, 1):
        print("%2d [%s] %s" % (position, item.state, item.url))
        if item.note:
            print("      %s" % item.note)


def _do_fetch(project, items):
    todo = [i.url for i in items]
    print("Récupération de %d article(s)…" % len(todo))
    for url in todo:
        article, fresh = project.fetch_article(url)
        if article is not None:
            entry = project.catalog.get(url) or {}
            if article.lang and article.lang != "fr" and not project.has_translation(
                    article.slug):
                project.catalog.upsert(url, status="archived")
    project.catalog.save()
    for item in items:
        item.refresh(project)
    return 0


def _do_translate_one(project, item):
    if item is None:
        return
    path = project.translation_path(item.slug)
    if os.path.exists(path):
        print("déjà traduit : %s" % path)
        return
    source = project.archive.markdown(item.url)
    if not source:
        print("article non archivé : lancez « d » d'abord", file=sys.stderr)
        return
    print("Traduction en cours (%s)…" % item.slug)
    try:
        body, title = translate_mod.translate_one(source, item.slug + ".md")
    except translate_mod.TranslationError as exc:
        print("échec : %s" % exc, file=sys.stderr)
        item.note = str(exc)
        return
    issues = translate_mod.lint(source, body)
    if issues:
        print("traduction refusée : %s" % "; ".join(issues[:3]), file=sys.stderr)
        item.note = "; ".join(issues[:3])
        return
    translate_mod.write_translation(project.config.fr_dir, item.slug, body, title or "")
    project.catalog.upsert(item.url, title_fr=title or item.title)
    project.catalog.save()
    print("écrit : %s" % path)
    item.refresh(project)


def _do_build(project, items, interactive=True):
    urls = [i.url for i in items if i.keep]
    if not urls:
        print("aucun article retenu", file=sys.stderr)
        return 2
    if interactive and sys.stdin.isatty():
        title = _prompt("Titre du livre", "Anthologie")
    else:
        title = "Anthologie"
    out, chapters, problems = project.build(urls, title, translate=True)
    print("%s — %d chapitres" % (out, len(chapters)))
    for problem in problems:
        print("  - %s" % problem)
    return 1 if problems else 0


def _do_opml(project, path):
    if not path:
        print("usage : o <fichier.opml> [groupe]", file=sys.stderr)
        return
    groups = feeds_mod.parse_opml(path)
    for name, feeds in groups.items():
        print("\n=== %s ===" % name)
        for feed in feeds:
            loaded = feeds_mod.load_feed(feed.url)
            if not loaded.alive:
                print("  ✗ %-36s %s" % (loaded.title[:36], loaded.error))
                continue
            kept = feeds_mod.recent(loaded.entries, days=7)
            print("  · %-36s %d sur 7 jours" % (loaded.title[:36], len(kept)))
            for entry in kept:
                print("      %s  %s" % (entry.date, entry.title[:60]))
                print("        %s" % entry.url)


def _prompt(label, default):
    try:
        answer = input("%s [%s] : " % (label, default)).strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return answer or default


# --------------------------------------------------------------------------
# curses
# --------------------------------------------------------------------------
def run_tui(project, seed=None):
    """ Lance curses, ou bascule sur le REPL si le terminal s'y prête mal."""
    if not sys.stdin.isatty() or not sys.stdout.isatty() or not os.environ.get("TERM"):
        return run_repl(project, seed)
    try:
        return _curses_main(project, seed)
    except curses.error:
        return run_repl(project, seed)


def _curses_main(project, seed):
    items = [Item(u) for u in (seed or [])]
    for item in items:
        item.refresh(project)
    return curses.wrapper(lambda scr: _loop(scr, project, items))


def _loop(scr, project, items):
    curses.curs_set(1)
    input_buf = ""
    selected = 0
    status = "Saisissez des URL puis « a » pour les ajouter."
    filtering = False
    while True:
        _draw(scr, items, selected, input_buf, status, filtering)
        key = scr.getch()
        if key in (curses.KEY_RESIZE,):
            continue
        char = chr(key) if 0 <= key < 0x110000 else ""

        if filtering:
            if key in (curses.KEY_ENTER, 10, 13):
                filtering = False
                status = "Filtre effacé."
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                status = status[:-1]
            elif char.isprintable():
                status += char
            continue

        if key in (curses.KEY_BACKSPACE, 127, 8):
            input_buf = input_buf[:-1]
            continue
        if char.isprintable() and not char.isdigit():
            input_buf += char
            continue
        if key == curses.KEY_DOWN:
            selected = min(selected + 1, max(len(items) - 1, 0))
            continue
        if key == curses.KEY_UP:
            selected = max(selected - 1, 0)
            continue

        if key in (curses.KEY_ENTER, 10, 13):
            added = [u for u in input_buf.split() if u.startswith("http")]
            items.extend(Item(u) for u in added)
            input_buf = ""
            status = "%d URL ajoutée(s)." % len(added)
        elif char == "q":
            return 0
        elif char == "a":
            added = [u for u in input_buf.split() if u.startswith("http")]
            items.extend(Item(u) for u in added)
            input_buf = ""
            status = "%d URL ajoutée(s)." % len(added)
        elif char == "d":
            status = _do_fetch(project, items)
        elif char == "t":
            item = items[selected] if items else None
            _do_translate_one(project, item)
            if item:
                item.refresh(project)
            status = "Traduction de %s tentée." % (item.slug if item else "-")
        elif char == "o":
            _do_opml(project, input_buf)
            input_buf = ""
            status = "Flux listés ci-dessus."
        elif char == "b":
            return _do_build(project, items, interactive=True)
        elif char == "x":
            if items:
                url = items.pop(selected).url
                selected = min(selected, max(len(items) - 1, 0))
                status = "Retiré : %s" % url
        elif char == "/":
            filtering = True
            status = ""
        elif char == "?":
            status = "Aide : a ajouter · d télécharger · t traduire · b epub · x retirer · q quitter"
        elif char in (" ", "\t"):
            if items:
                items[selected].keep = not items[selected].keep
                status = "%s : %s" % (items[selected].title[:30],
                                      "retenu" if items[selected].keep else "écarté")


def _draw(scr, items, selected, input_buf, status, filtering):
    scr.erase()
    height, width = scr.getmaxyx()
    title = " blog2epub — composeurs d'EPUB à partir de billets de blog "
    scr.addnstr(0, 0, title.ljust(width - 1), width - 1, curses.A_REVERSE)

    label = "URL> "
    scr.addnstr(2, 0, label, len(label), curses.A_BOLD)
    scr.addnstr(2, len(label), input_buf[-max(width - len(label) - 2, 10):],
                max(width - len(label) - 2, 10))

    scr.addnstr(4, 0, "Articles", 10, curses.A_UNDERLINE)
    visible = [i for i in items if not filtering or filtering in
               (i.title or "") or filtering in i.url]
    row = 5
    visible_rows = height - 9
    start = max(0, min(selected - visible_rows // 2, len(visible) - visible_rows))
    for offset, item in enumerate(visible[start:start + visible_rows]):
        y = row + offset
        if y >= height - 4:
            break
        mark = "[x]" if item.keep else "[ ]"
        line = " %-5s %-11s %-10s %s" % (mark, item.state, item.date,
                                         (item.title or item.url)[:max(width - 34, 10)])
        if visible[start + offset] is items[selected] if selected < len(items) else False:
            scr.addnstr(y, 0, line.ljust(width - 1), width - 1, curses.A_REVERSE)
        else:
            scr.addnstr(y, 0, line, width - 1)

    footer = " a ajouter · d télécharger · t traduire · b epub · x retirer · ? aide · q quitter "
    scr.addnstr(height - 3, 0, footer.ljust(width - 1), width - 1, curses.A_REVERSE)
    scr.addnstr(height - 2, 0, status[:width - 1], width - 1)
    count = "%d article(s) · %d retenu(s)" % (len(items), len([i for i in items if i.keep]))
    scr.addnstr(height - 1, 0, count.ljust(width - 1), width - 1)
    scr.refresh()