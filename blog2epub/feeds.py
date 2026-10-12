"""Flux RSS/Atom et import OPML."""

import datetime
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET

from .fetch import FetchError, fetch_text

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


class Entry:
    def __init__(self, title, url, date, summary=""):
        self.title = title
        self.url = url
        self.date = date
        self.summary = summary

    def __repr__(self):
        return "<Entry %s %s>" % (self.date, self.title[:40])


def _iso(value):
    if not value:
        return ""
    value = value.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            parsed = datetime.datetime.strptime(value, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    match = re.search(r"(20\d\d)-(\d\d)-(\d\d)", value)
    return match.group(0) if match else ""


def parse_feed(text, source_url=""):
    """Extrait les entrées d'un flux RSS 2.0 ou Atom."""
    try:
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    except ET.ParseError as exc:
        raise FetchError("flux illisible (%s) : %s" % (os.path.basename(source_url), exc))
    entries = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        if not link:
            guid = item.findtext("guid") or ""
            link = guid.strip() if guid.startswith("http") else ""
        entries.append(Entry(
            (item.findtext("title") or "").strip(),
            urllib.parse.urljoin(source_url, link),
            _iso(item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")),
            re.sub(r"<[^>]+>", " ", item.findtext("description") or "")[:400],
        ))
    if not entries:
        for item in root.iter(ATOM + "entry"):
            link = ""
            for link_node in item.findall(ATOM + "link"):
                if link_node.get("rel", "alternate") == "alternate" and link_node.get("href"):
                    link = link_node.get("href")
                    break
            entries.append(Entry(
                (item.findtext(ATOM + "title") or "").strip(),
                urllib.parse.urljoin(source_url, link),
                _iso(item.findtext(ATOM + "updated") or item.findtext(ATOM + "published")),
                re.sub(r"<[^>]+>", " ", item.findtext(ATOM + "summary") or "")[:400],
            ))
    return [e for e in entries if e.url.startswith("http")]


class Feed:
    def __init__(self, title, url):
        self.title = title
        self.url = url
        self.entries = []
        self.error = ""

    @property
    def alive(self):
        return not self.error


def load_feed(url, timeout=45):
    feed = Feed(url, url)
    try:
        text = fetch_text(url, timeout=timeout, accept="application/rss+xml, application/xml, */*")
    except FetchError as exc:
        feed.error = str(exc)
        return feed
    try:
        feed.entries = parse_feed(text, url)
    except FetchError as exc:
        feed.error = str(exc)
        return feed
    if not feed.entries:
        feed.error = "aucune entrée exploitable"
    return feed


def parse_opml(path):
    """Lit un OPML et renvoie {groupe: [Feed]}."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise FetchError("OPML illisible : %s" % exc)
    groups = {}
    for outline in root.iter("outline"):
        xml_url = outline.get("xmlUrl") or outline.get("xmlurl")
        title = (outline.get("title") or outline.get("text") or xml_url or "sans titre").strip()
        if xml_url:
            groups.setdefault("Sans groupe", []).append(Feed(title, xml_url))
            continue
        children = [o for o in outline.iter("outline") if o is not outline
                    and (o.get("xmlUrl") or o.get("xmlurl"))]
        if children:
            groups.setdefault(title, [])
            for child in children:
                url = child.get("xmlUrl") or child.get("xmlurl")
                name = (child.get("title") or child.get("text") or url).strip()
                groups[title].append(Feed(name, url))
    return groups


def recent(entries, days=7, today=None):
    """Ne garde que les entrées publiées dans la fenêtre, triées du plus récent."""
    today = today or datetime.date.today()
    limit = today - datetime.timedelta(days=days)
    kept = []
    for entry in entries:
        if not entry.date:
            continue
        try:
            when = datetime.date.fromisoformat(entry.date)
        except ValueError:
            continue
        if when <= today and when >= limit:
            kept.append(entry)
    kept.sort(key=lambda e: e.date, reverse=True)
    return kept