"""Translations (Swedish + English) and money formatting.

Language: FLIGHTWATCH_LANG, else `general.language` in the config ("auto" | "sv" | "en"), else the system
language, else English. Catalogs live in i18n/<lang>.json as flat keys; a value is a string with {name}
placeholders or a plural pair {"one": …, "other": …} picked by `n`.
"""
import json
import locale
import os
import subprocess
from functools import lru_cache
from importlib.resources import files

LANGS = ("sv", "en")
DEFAULT = "en"


def _configured():
    """general.language from the config file, read without importing config (which uses this module)."""
    try:
        import tomllib
        from .config import CONFIG_PATH
        with open(CONFIG_PATH, "rb") as f:
            return str(tomllib.load(f).get("general", {}).get("language", "auto"))
    except Exception:
        return "auto"


def system_language():
    """Two-letter UI language of the operating system (None if unknown)."""
    from . import system
    try:
        if system.WINDOWS:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return (locale.windows_locale.get(lcid) or "")[:2] or None
        if system.MACOS:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True,
                                 timeout=5).stdout
            first = next((x.strip(' "\n,') for x in out.splitlines()[1:] if x.strip(' "\n,()')), "")
            return first[:2] or None
    except Exception:
        pass
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v and v not in ("C", "POSIX") and not v.startswith("C."):
            return v.split(":")[0][:2]
    loc = locale.getlocale()[0]
    return loc[:2] if loc else None


@lru_cache(maxsize=1)
def lang():
    for choice in (os.environ.get("FLIGHTWATCH_LANG"), _configured(), system_language()):
        if choice and choice != "auto" and choice[:2] in LANGS:
            return choice[:2]
    return DEFAULT


def reset():
    """Forget the cached language (after the setting changed in a long-running process)."""
    lang.cache_clear()
    catalog.cache_clear()


@lru_cache(maxsize=4)
def catalog(code=None):
    code = code or lang()
    data = json.loads(files("flightwatch").joinpath("i18n", f"{code}.json").read_text(encoding="utf-8"))
    if code != DEFAULT:
        base = json.loads(files("flightwatch").joinpath("i18n", f"{DEFAULT}.json").read_text(encoding="utf-8"))
        data = {**base, **data}
    return data


def t(key, n=None, **kw):
    v = catalog().get(key, key)
    if isinstance(v, dict):
        v = v["one"] if n == 1 else v["other"]
    if n is not None:
        kw.setdefault("n", n)
    return v.format(**kw) if kw else v


# --- money ----------------------------------------------------------------------------------

SYMBOLS = {"SEK": "kr", "NOK": "kr", "DKK": "kr", "ISK": "kr", "EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF",
           "JPY": "¥", "AUD": "A$", "CAD": "C$", "PLN": "zł", "THB": "฿"}


def fmt_money(amount, currency="SEK", code=None):
    """12 345 kr / 1 234 € (sv), SEK 12,345 / €1,234 (en). `amount` is already in `currency`."""
    if amount is None:
        return "—"
    code = code or lang()
    sym = SYMBOLS.get(currency, currency)
    n = f"{round(amount):,}"
    if code == "sv":
        return n.replace(",", " ") + " " + sym
    if sym == "kr":
        return f"{currency} {n}"
    return f"{sym}{n}" if len(sym) <= 2 else f"{sym} {n}"


def money(sek):
    """A price stored in SEK, shown in the chosen currency."""
    if sek is None:
        return "—"
    from . import fx
    cur, rate = fx.current()
    return fmt_money(sek * rate, cur)
