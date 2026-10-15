"""Display currency. Prices are fetched and stored in SEK (the sources are Swedish); `general.currency`
only changes what is shown. Rates: ECB reference rates via frankfurter.dev, cached for a day."""
import json
import time

import httpx

from .config import CACHE_DIR

CACHE = CACHE_DIR / "fx.json"
URL = "https://api.frankfurter.dev/v1/latest"
MAX_AGE = 24 * 3600
CURRENCIES = ["SEK", "EUR", "USD", "GBP", "NOK", "DKK", "CHF", "PLN"]


def _rates():
    """SEK -> other currency rates, refreshed at most daily; stale cache beats no rates when offline."""
    try:
        cached = json.loads(CACHE.read_text())
    except Exception:
        cached = None
    if cached and time.time() - cached.get("fetched", 0) < MAX_AGE:
        return cached["rates"]
    try:
        r = httpx.get(URL, params={"base": "SEK"}, timeout=10, follow_redirects=True)
        r.raise_for_status()
        rates = r.json()["rates"]
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"fetched": time.time(), "rates": rates}))
        return rates
    except Exception:
        return cached["rates"] if cached else {}


def rate(currency):
    """How many `currency` one SEK buys; None if unknown."""
    if currency == "SEK":
        return 1.0
    return _rates().get(currency)


def current():
    """(currency, rate) to display with; falls back to SEK when no rate is available."""
    from . import config
    try:
        cur = str(config.load_doc().get("general", {}).get("currency", "SEK")).upper()
    except Exception:
        cur = "SEK"
    r = rate(cur)
    return (cur, r) if r else ("SEK", 1.0)
