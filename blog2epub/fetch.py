"""Téléchargement HTTP : User-Agent, reprises, respect d'une limite de débit."""

import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124 Safari/537.36 blog2epub")

_LAST = [0.0]


class FetchError(Exception):
    pass


def throttle(delay=0.4):
    """Pause minimale entre deux requêtes, pour ne pas marteler les serveurs."""
    wait = _LAST[0] + delay - time.time()
    if wait > 0:
        time.sleep(wait)
    _LAST[0] = time.time()


def fetch(url, retries=3, timeout=45, delay=1.0, accept="*/*"):
    last = None
    for attempt in range(retries):
        throttle()
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": accept,
                "Accept-Language": "fr,en;q=0.8,*;q=0.5",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (401, 403, 404, 410):
                raise FetchError("HTTP %s sur %s" % (exc.code, url)) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = exc
        time.sleep(delay * (attempt + 1))
    raise FetchError("échec de téléchargement %s : %s" % (url, last))


def fetch_text(url, **kwargs):
    raw, headers = fetch(url, **kwargs)
    charset = None
    ctype = headers.get("Content-Type", "")
    if "charset=" in ctype:
        charset = ctype.split("charset=")[1].split(";")[0].strip()
    for guess in (charset, "utf-8", "latin-1"):
        if not guess:
            continue
        try:
            return raw.decode(guess)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")