"""'New version available' notice: the latest GitHub release, checked at most once a day. Nothing is
downloaded or installed automatically; the app just links to the release page."""
import json
import time
from importlib.metadata import PackageNotFoundError, version

import httpx

from .config import CACHE_DIR

REPO = "kmhbg/flightwatch"  # GitHub releases; empty = no update check
CACHE = CACHE_DIR / "update.json"


def current():
    try:
        return version("flightwatch")
    except PackageNotFoundError:
        return "0"


def _tuple(v):
    return tuple(int(x) if x.isdigit() else 0 for x in v.lstrip("v").split("."))


def check():
    """{"available": bool, "version": "1.2.0", "url": release page}."""
    if not REPO:
        return {"available": False}
    try:
        cached = json.loads(CACHE.read_text())
    except Exception:
        cached = None
    if not cached or time.time() - cached.get("fetched", 0) > 24 * 3600:
        try:
            r = httpx.get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=10,
                          headers={"accept": "application/vnd.github+json"})
            r.raise_for_status()
            j = r.json()
            cached = {"fetched": time.time(), "version": j["tag_name"], "url": j["html_url"]}
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cached))
        except Exception:
            return {"available": False}
    newer = _tuple(cached["version"]) > _tuple(current())
    return {"available": newer, "version": cached["version"].lstrip("v"), "url": cached["url"]}
