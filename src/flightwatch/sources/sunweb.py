"""Sunweb package trips (charter flight + hotel) as a comparison point.

Reverse-engineered 2026-10-13 from sunweb.se/solresor/sog: the page calls a plain GET
/api/sitecore/SearchApi/GetSearchResponse (no cookies or tokens). Participants are given as birth
dates, Duration as days incl. both travel days ("8-8" = 7 nights), DepartureDate as one exact day.
The City filter carries coordinates, so the cities near the stay are picked automatically. Sunweb only
sells the Mediterranean, the Canaries, Egypt etc.; other destinations simply return nothing.
"""
import re
from datetime import date, timedelta

import httpx

from ..i18n import t
from ..models import Leg, Offer
from ..places import _distance_km

BASE = "https://www.sunweb.se"
API = BASE + "/api/sitecore/SearchApi/GetSearchResponse"
CONTEXT = "09c57296-0f69-40b3-941d-af0030bc8f85"   # the /solresor/sog page item
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"


def _params(origin, watch, extra=()):
    days = (watch["return"] - watch["depart"]).days + 1
    p = [("Duration[0]", f"{days}-{days}"), ("DepartureDate", watch["depart"].isoformat()),
         ("DepartureAirport[0]", origin), ("TransportType", "Flight"), ("contextItemId", CONTEXT),
         ("sort", "Price"), ("limit", "20"), ("offset", "0"),
         ("requiredFilters", "City+DepartureAirport+DepartureDate+Duration")]
    for i in range(watch["adults"]):
        p.append((f"Participants[0][{i}]", "1985-01-01"))
    return p + list(extra)


def _get(params):
    r = httpx.get(API, params=params, headers={"user-agent": UA, "accept": "application/json"}, timeout=60)
    r.raise_for_status()
    return r.json()


def _point(st, watch):
    if st.get("lat") is not None:
        return st["lat"], st["lon"]
    from ..places import _airport_index
    a = next((a for a in _airport_index() if a["code"] == watch["destination"]), None)
    return (a["lat"], a["lon"]) if a else (None, None)


def nearby_cities(origin, watch, km=60):
    st = watch.get("stay", {})
    lat, lon = _point(st, watch)
    if lat is None:
        return []
    d = _get(_params(origin, watch))
    out = []
    for f in d.get("filters", []):
        if f.get("type") != "City":
            continue
        for v in f["values"]:
            m = re.search(r"Latitude:([-\d.]+) \|\| Longitude:([-\d.]+)", v.get("metadata") or "")
            if m and _distance_km(lat, lon, float(m.group(1)), float(m.group(2))) <= km:
                out.append(v["value"])
    return out


def search(origin, watch, cfg, limit=5):
    cities = nearby_cities(origin, watch)
    if not cities:
        return []
    d = _get(_params(origin, watch, [(f"City[{i}]", c) for i, c in enumerate(cities)]))
    offers = []
    for x in d.get("results", [])[:limit]:
        if x.get("isUnavailable") or x.get("isFlightOnly"):
            continue
        acm = x["price"].get("acmInformation") or {}
        dep = date.fromisoformat(acm.get("departureDateRaw", watch["depart"].isoformat())[:10])
        back = dep + timedelta(days=(acm.get("durationRaw") or 1) - 1)
        nights = (x.get("featuredFilters") or {}).get("duration", "")
        offers.append(Offer(
            source="sunweb", kind="package", origin=origin, destination=watch["destination"],
            depart_date=dep.isoformat(), return_date=back.isoformat(),
            ticket_total=float(x["price"]["totalPrice"]),
            out=Leg(), back=Leg(),
            bags_included_pp=0, bag_note=t("src.sunweb_bag"),
            url=BASE + (x.get("urlWithFilters") or x.get("url", "")), booking_via=t("src.sunweb_via"),
            hotel=t("src.sunweb_hotel", name=x["name"], city=x.get("cityName", ""), nights=nights,
                    meal=(x.get("featuredFilters") or {}).get("mealplan", ""), rating=x.get("userRating") or "?"),
            conditions=t("src.sunweb_cond"),
        ))
    return offers
