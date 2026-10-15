"""Airbnb lodging price for the stay, used to compare packages with flight + own lodging.

The search page is server-rendered; results sit in <script id="data-deferred-state-0"> as JSON
(niobeClientData → staysSearch.results.searchResults). Plain GET, no login. Airbnb ranks by relevance,
not price, so a few pages are read (cursor from paginationInfo) and the cheapest qualifying listing wins.
Filters are Airbnb's own URL filters: Gästfavorit, amenities (pool, AC …), entire home, bedrooms.
"""
import base64
import json
import re
from datetime import date
from urllib.parse import urlencode

import httpx

from ..i18n import t
from ..places import _distance_km

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
# Airbnb amenity ids (verified 2026-10-12: they show up as selected "Pool"/"Luftkonditionering" filters).
AMENITIES = {"wifi": 4, "ac": 5, "kitchen": 8, "pool": 7}


def _amount(s):
    # "Totalt 5 881 kr SEK, ursprungligen 6 919 kr SEK" -> 5881 (first amount = what you pay)
    m = re.search(r"([\d\s  ]+)(?:,\d+)?\s*kr", s or "")
    return float(re.sub(r"\D", "", m.group(1))) if m else None


def _rating(s):
    m = re.match(r"([\d,]+)\s*\((\d+)\)", s or "")
    return (float(m.group(1).replace(",", ".")), int(m.group(2))) if m else (0.0, 0)


def _params(stay, checkin, checkout, guests):
    q = [("checkin", checkin.isoformat()), ("checkout", checkout.isoformat()), ("adults", guests),
         ("currency", "SEK")]
    if stay.get("guest_favorite", True):
        q.append(("guest_favorite", "true"))
    for a in stay.get("require", []):
        if a in AMENITIES:
            q.append(("amenities[]", AMENITIES[a]))
    if stay.get("entire_home", False):
        q.append(("room_types[]", "Entire home/apt"))
    if stay.get("min_bedrooms"):
        q.append(("min_bedrooms", stay["min_bedrooms"]))
    return q


def search_url(stay, checkin: date, checkout: date, guests):
    return f"https://www.airbnb.se/s/{stay['airbnb_location']}/homes?{urlencode(_params(stay, checkin, checkout, guests))}"


def _page(url):
    r = httpx.get(url, headers={"user-agent": UA, "accept-language": "sv-SE"}, timeout=60, follow_redirects=True)
    r.raise_for_status()
    m = re.search(r'<script id="data-deferred-state-0"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError(t("src.airbnb_none"))
    return json.loads(m.group(1))["niobeClientData"][0][1]["data"]["presentation"]["staysSearch"]["results"]


def search(stay, checkin: date, checkout: date, guests):
    """Qualifying listings sorted by total price: dicts with total, per_night, name, rating, beds, url."""
    url = search_url(stay, checkin, checkout, guests)
    nights = (checkout - checkin).days
    out, seen, cursor = [], set(), None
    for page in range(stay.get("pages", 3)):
        res = _page(url + (f"&cursor={cursor}" if cursor else ""))
        for r in res["searchResults"]:
            raw_id = (r.get("demandStayListing") or {}).get("id", "")
            if raw_id in seen:
                continue
            seen.add(raw_id)
            badges = [b.get("text", "") for b in r.get("badges") or []]
            if stay.get("guest_favorite", True) and not any(b in ("Gästfavorit", "Superhost", "Guest favorite") for b in badges):
                continue
            coord = ((r.get("demandStayListing") or {}).get("location") or {}).get("coordinate") or {}
            km = None
            if stay.get("lat") is not None and coord.get("latitude") is not None:
                km = _distance_km(stay["lat"], stay["lon"], coord["latitude"], coord["longitude"])
                if km > stay.get("max_km", 8):  # Airbnb's map area is wider than the town
                    continue
            rating, reviews = _rating(r.get("avgRatingLocalized"))
            if rating < stay.get("min_rating", 4.8) or reviews < stay.get("min_reviews", 10):
                continue
            total = _amount(r["structuredDisplayPrice"]["primaryLine"].get("accessibilityLabel"))
            if not total:
                continue
            try:
                lid = base64.b64decode(raw_id).decode().split(":")[-1]
            except Exception:
                lid = ""
            name = (r.get("nameLocalized") or {}).get("localizedStringWithTranslationPreference") or ""
            beds = [m.get("body", "") for m in ((r.get("structuredContent") or {}).get("mapPrimaryLine") or [])]
            out.append({
                "total": total, "per_night": round(total / nights), "nights": nights,
                "name": f"{r.get('title', '')}: {name}".strip(": "), "rating": rating, "reviews": reviews,
                "beds": ", ".join(b for b in beds if b), "badges": badges, "km": round(km, 1) if km is not None else None,
                "url": (f"https://www.airbnb.se/rooms/{lid}?check_in={checkin}&check_out={checkout}&adults={guests}"
                        if lid else url),
            })
        cursors = (res.get("paginationInfo") or {}).get("pageCursors") or []
        if len(cursors) <= page + 1:
            break
        cursor = cursors[page + 1]
    return sorted(out, key=lambda x: x["total"])
