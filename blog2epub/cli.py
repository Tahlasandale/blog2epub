"""Commandes en ligne de blog2epub."""

import argparse
import os
import sys

from . import archive as archive_mod
from . import extract as extract_mod
from . import feeds as feeds_mod
from . import translate as translate_mod
from .config import Config
from .project import Project

LEGACY_USAGE = ("Forme conservée : blog2epub <fichier.txt> ouvre l'interface ; "
                "pour un traitement direct, blog2epub build <fichier.txt>")


def _read_urls(source):
    if source in (None, "-"):
        raw = sys.stdin.read()
    elif os.path.exists(source):
        with open(source, encoding="utf-8") as handle:
            raw = handle.read()
    else:
        raw = source
    import re
    return [u for u in re.split(r"[\s,;]+", raw) if u.startswith("http")]


def _prompt_title(default):
    try:
        answer = input("Titre du livre [%s] : " % default).strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    return answer or default


def _auto_title(urls):
    hosts = []
    for url in urls:
        host = url.split("/")[2] if "://" in url else url
        base = host[4:] if host.startswith("www.") else host
        if base not in hosts:
            hosts.append(base)
    label = " + ".join(hosts[:3])
    if len(hosts) > 3:
        label += " et %d autres" % (len(hosts) - 3)
    return "Anthologie %s" % label


# --------------------------------------------------------------------------
# sous-commandes
# --------------------------------------------------------------------------
def cmd_build(args):
    project = Project()
    urls = _read_urls(args.links) if args.links else []
    if args.url:
        urls.extend(args.url)
    urls = list(dict.fromkeys(urls))
    if not urls:
        print("aucune URL : passez un fichier, des --url, ou '-' pour stdin", file=sys.stderr)
        return 2
    title = args.title or (_prompt_title(_auto_title(urls)) if sys.stdin.isatty()
                           else _auto_title(urls))
    out, chapters, problems = project.build(
        urls, title, author=args.author, order=args.order, cover=args.cover,
        translate=not args.no_translate, model=args.model,
        out_path=args.out, lang=args.lang)
    size = os.path.getsize(out) / 1024.0
    print("\n%s — %d chapitres, %.0f Ko" % (out, len(chapters), size))
    for chapter in chapters:
        mark = "✓" if not chapter.flag else "!"
        print("   %s %s" % (mark, chapter.title))
    missing = [c for c in chapters if c.flag]
    if missing:
        print("\n%d chapitre(s) sans traduction disponible, gardés en version originale."
              % len(missing))
    if problems:
        print("\nPROBLÈMES :")
        for problem in problems:
            print("  - %s" % problem)
        return 1
    print("\n✓ vérifications EPUB 3 passées")
    return 0


def cmd_fetch(args):
    project = Project()
    urls = _read_urls(args.links) if args.links else []
    urls.extend(args.url or [])
    urls = list(dict.fromkeys(urls))
    if not urls:
        print("aucune URL", file=sys.stderr)
        return 2
    print("Récupération de %d article(s)…" % len(urls))
    articles = project.fetch_all(urls, refresh=args.refresh)
    print("\n%d article(s) archivé(s), catalogue à jour (%d entrées)"
          % (len(articles), len(project.catalog.entries)))
    return 0


def cmd_check(args):
    project = Project()
    urls = _read_urls(args.links) if args.links else []
    urls.extend(args.url or [])
    ok = True
    for url in dict.fromkeys(urls):
        entry = project.catalog.get(url)
        if entry is None:
            print("? %s absent du catalogue" % url)
            continue
        source = project.archive.markdown(url)
        if not source:
            print("? %s sans Markdown archivé" % url)
            continue
        path = project.translation_path(entry.get("slug", ""))
        if not os.path.exists(path):
            status = entry.get("status", "")
            print("– %s : %s (aucune traduction)" % (entry.get("title", url)[:50], status))
            continue
        with open(path, encoding="utf-8") as handle:
            content = re_strip(handle.read())
        issues = translate_mod.lint(source, content)
        if issues:
            ok = False
            print("✗ %s" % entry.get("slug"))
            for issue in issues:
                print("    - %s" % issue)
        else:
            print("✓ %s" % entry.get("slug"))
    return 0 if ok else 1


def re_strip(text):
    import re
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", text.strip(), flags=re.S)


def cmd_translate(args):
    project = Project()
    urls = _read_urls(args.links) if args.links else []
    urls.extend(args.url or [])
    articles = project.fetch_all(list(dict.fromkeys(urls)), quiet=True)
    if not articles:
        print("aucun article", file=sys.stderr)
        return 2
    done, failed = project.translate(articles, model=args.model)
    print("%d traduit(s), %d échec(s)" % (len(done) - len([a for a in articles
                                                            if not a.lang or a.lang == "fr"]),
                                          len(failed)))
    return 1 if failed else 0


def cmd_opml(args):
    """Charge un OPML et affiche les articles récents, prêts à être retenus."""
    groups = feeds_mod.parse_opml(args.file)
    wanted = [args.group] if args.group else list(groups)
    for name in wanted:
        feeds = groups.get(name)
        if not feeds:
            print("groupe inconnu : %s" % name)
            continue
        print("\n=== %s (%d flux) ===" % (name, len(feeds)))
        for feed in feeds:
            loaded = feeds_mod.load_feed(feed.url)
            if not loaded.alive:
                print("  ✗ %-40s %s" % (loaded.title[:40], loaded.error))
                continue
            kept = feeds_mod.recent(loaded.entries, days=args.days)
            print("  · %-40s %d entrées, %d sur %d jours"
                  % (loaded.title[:40], len(loaded.entries), len(kept), args.days))
            for entry in kept:
                print("      %s  %s" % (entry.date, entry.title[:64]))
                print("        %s" % entry.url)
    return 0


def cmd_archive(args):
    project = Project()
    if args.action == "stats":
        counts = project.catalog.stats()
        print("Catalogue : %d entrées" % len(project.catalog.entries))
        for status, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            print("  %-12s %d" % (status, count))
        return 0
    if args.action == "list":
        for entry in project.catalog.entries:
            print("%-12s %-10s %s" % (entry.get("status", "?"), entry.get("date", ""),
                                      entry.get("title", entry.get("url", ""))[:60]))
        return 0
    if args.action == "resync":
        removed = project.archive.purge_orphans()
        project.catalog.save()
        print("%d entrée(s) orpheline(s) retirée(s)" % len(removed))
        for url in removed:
            print("  - %s" % url)
        return 0
    if args.action == "purge":
        import shutil
        removed = project.archive.purge_orphans()
        if os.path.isdir(project.config.archive_dir):
            shutil.rmtree(project.config.archive_dir)
        project.catalog.entries = []
        project.catalog.by_url = {}
        project.catalog.save()
        print("archive vidée (%d entrées retirées)" % len(removed))
        return 0
    return 2


def cmd_tui(args):
    from .tui import run_tui
    return run_tui(Project(), seed=_read_urls(args.links) if args.links else [])


# --------------------------------------------------------------------------
# analyseur
# --------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="blog2epub",
        description="Compile des articles de blog en un EPUB, un chapitre par article.")
    parser.add_argument("--version", action="version", version="blog2epub 2.0")
    sub = parser.add_subparsers(dest="command")

    def common(p):
        p.add_argument("links", nargs="?", help="fichier d'URL, '-' pour stdin")
        p.add_argument("--url", action="append", help="URL supplémentaire (répétable)")

    build = sub.add_parser("build", help="construit un EPUB")
    common(build)
    build.add_argument("-o", "--out", default=None, help="chemin du fichier EPUB")
    build.add_argument("--title", default=None)
    build.add_argument("--author", default=None)
    build.add_argument("--lang", default=None)
    build.add_argument("--order", default="desc", choices=["desc", "asc", "given"])
    build.add_argument("--cover", default=None, help="URL d'une image de couverture")
    build.add_argument("--model", default="", help="modèle opencode pour la traduction")
    build.add_argument("--no-translate", action="store_true",
                       help="n'appelle pas opencode, garde les langues d'origine")
    build.set_defaults(func=cmd_build)

    fetch = sub.add_parser("fetch", help="télécharge, extrait et archive")
    common(fetch)
    fetch.add_argument("--refresh", action="store_true", help="retélécharge malgré l'archive")
    fetch.set_defaults(func=cmd_fetch)

    check = sub.add_parser("check", help="contrôle les traductions")
    common(check)
    check.set_defaults(func=cmd_check)

    translate = sub.add_parser("translate", help="traduit via le CLI opencode")
    common(translate)
    translate.add_argument("--model", default="")
    translate.set_defaults(func=cmd_translate)

    opml = sub.add_parser("opml", help="articles récents d'un export OPML")
    opml.add_argument("file")
    opml.add_argument("--group", default=None)
    opml.add_argument("--days", type=int, default=None)
    opml.set_defaults(func=cmd_opml)

    arch = sub.add_parser("archive", help="statistiques et entretien de l'archive")
    arch.add_argument("action", nargs="?", default="stats",
                      choices=["stats", "list", "resync", "purge"])
    arch.set_defaults(func=cmd_archive)

    tui = sub.add_parser("tui", help="interface à invites")
    tui.add_argument("links", nargs="?", default=None)
    tui.set_defaults(func=cmd_tui)

    return parser


KNOWN_COMMANDS = {"build", "fetch", "check", "translate", "opml", "archive", "tui"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not argv:
        return cmd_tui(argparse.Namespace(links=None))
    first = argv[0]
    if first not in KNOWN_COMMANDS and not first.startswith("-"):
        # usage historique : un fichier d'URL ouvre l'interface pré-remplie
        return cmd_tui(argparse.Namespace(links=first))
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_tui(argparse.Namespace(links=None))
    if args.command == "opml" and args.days is None:
        args.days = Config().settings["opml"]["days"]
    return args.func(args)