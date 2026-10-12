"""Configuration : réglages généraux et profils de sites."""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEFAULT_SETTINGS = {
    "book": {
        "lang": "fr",
        "author": "Auteur inconnu",
        "title": "Anthologie",
    },
    "translate": {
        # Liste de modèles opencode essayés dans l'ordre. Vide = celui
        # configuré dans opencode. Le repli évite les modèles dépréciés.
        "model": ["opencode/space-bunny-free", "opencode/ling-3.1-flash-free"],
        "timeout": 900,
        "attempts": 2,
        # En dessous de single_shot mots, un seul appel ; au-dessus, découpe
        "single_shot": 2500,
        "chunk_words": 600,
    },
    "opml": {
        "days": 7,
    },
    "images": {
        "quality": 88,
        "max_width": 1600,
    },
    "epub": {
        "outdir": "out",
    },
}

DEFAULT_SITES = {
    "_comment": [
        "Profils de sites. La détection générique (voir extract.CASCADE) suffit à la",
        "majorité des blogs ; ces profils ne servent qu'aux cas particuliers.",
        "Clés reconnues par profil : container, remove, keep, title, date, author.",
        "Les sélecteurs acceptent tag, .classe, #id, tag.classe et le combinateur",
        "descendant (espace). Une liste séparée par des virgules est acceptée.",
    ],
    "sites": [
        {
            "host": "ploum.net",
            "container": "article",
            "remove": "div.signature, nav, .navbar",
            "title": "h1",
            "author": "p.subtitle",
            "permalink": "gemini",
        },
        {
            "host": "framablog.org",
            "container": "article, .entry-content",
            "remove": ".sharedaddy, .jp-relatedposts, nav, footer",
            "title": "h1.entry-title, h1",
        },
        {
            "host": "simonwillison.net",
            "container": "#primary",
            "remove": "#secondary, #smallhead, #ft, nav",
            "title": "h2, h1",
        },
    ],
}


def _deep_merge(base, override):
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class Config:
    def __init__(self, root=None):
        self.root = os.path.abspath(root or ROOT)
        self.settings = _deep_merge(
            DEFAULT_SETTINGS,
            _read_json(os.path.join(self.root, "config", "settings.json"), {}))
        self.sites = _read_json(os.path.join(self.root, "config", "sites.json"),
                                DEFAULT_SITES).get("sites", [])

    # -- chemins ------------------------------------------------------------
    def path(self, *parts):
        return os.path.join(self.root, *parts)

    @property
    def catalog_path(self):
        return self.path("catalog.jsonl")

    @property
    def archive_dir(self):
        return self.path("archive")

    @property
    def fr_dir(self):
        return self.path("fr")

    @property
    def outdir(self):
        out = self.settings["epub"]["outdir"]
        return out if os.path.isabs(out) else self.path(out)

    # -- profils ------------------------------------------------------------
    def profile_for(self, host):
        """Profil du site correspondant à un hôte (correspondance par suffixe)."""
        host = (host or "").lower().split(":")[0]
        best = None
        for site in self.sites:
            pattern = str(site.get("host", "")).lower().lstrip(".")
            if not pattern:
                continue
            if host == pattern or host.endswith("." + pattern):
                if best is None or len(pattern) > len(best.get("host", "")):
                    best = site
        return best or {}