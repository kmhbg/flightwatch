"""Hotel prices for the stay, as an alternative to Airbnb: Booking.com, Hotels.com and Sembo.

Reverse-engineered 2026-10-13:
- Booking.com: the search page (AWS WAF JS check, so a real browser page) is server-rendered with the
  Apollo cache in <script data-capla-store-data="apollo">; results carry the total stay price in SEK
  (priceDisplayInfoIrene.displayPrice.amountPerStay), review score and coordinates. Filters are the
  site's own nflt codes: pool (hotelfacility=433), AC (roomfacility=11), review score.
- Hotels.com (Expedia): the search page fetches POST /graphql PropertyListingQuery; each LodgingCard has
  the heading, "x,y av 10" rating, the total price ("Priset är N kr för X nätter, R rum") and a
  link with latLong. Filters are URL parameters (amenities, guestRating).
- Sembo: plain GraphQL over websocket (wss://smart-search.sembo.com/graphql, graphql-transport-ws), no
  login. Places come from content-hc.sembo.com/CategorizedAutosuggestion (polygonId), hotel names and
  guest ratings from content-hc.sembo.com/Hotels/GetHotels.
All prices are for the whole stay, all rooms, in SEK. Hotels need rooms for everyone: guests are split
into rooms of two.
"""
import asyncio
import json
import re
import uuid
from datetime import date
from importlib.resources import files
from urllib.parse import quote, urlencode

import httpx

from ..i18n import t
from ..places import _distance_km
from .browser import page

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"


DORM = ("sovsal", "dorm", "hostel", "bunk", "delat rum", "shared room", "capsule")


def rooms_for(guests):
    return [2] * (guests // 2) + ([1] if guests % 2 else [])


def _num(s):
    m = re.search(r"\d[\d\s  ]*", s or "")
    return float(re.sub(r"\D", "", m.group(0))) if m else None


def _near(st, lat, lon):
    """Within max_km of the place (when the trip has coordinates)."""
    if st.get("lat") is None or lat is None:
        return True
    return _distance_km(st["lat"], st["lon"], lat, lon) <= st.get("hotel_max_km", st.get("max_km", 8) * 2)


def location(st):
    return st.get("hotel_location") or st.get("place") or st.get("airbnb_location", "").replace("--", ", ")


# --- Booking.com ---------------------------------------------------------------------------------

def booking_url(st, checkin, checkout, guests):
    nflt = []
    if "pool" in st.get("require", []):
        nflt.append("hotelfacility=433")
    if "ac" in st.get("require", []):
        nflt.append("roomfacility=11")
    score = st.get("hotel_min_rating", 8.5)
    nflt.append(f"review_score={90 if score >= 9 else 80 if score >= 8 else 70}")
    q = {"ss": location(st), "checkin": checkin.isoformat(), "checkout": checkout.isoformat(),
         "group_adults": guests, "no_rooms": len(rooms_for(guests)), "group_children": 0,
         "selected_currency": "SEK", "order": "price", "nflt": ";".join(nflt), "lang": "sv"}
    return "https://www.booking.com/searchresults.sv.html?" + urlencode(q)


def _find_results(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "results" and isinstance(v, list) and v and isinstance(v[0], dict) and "basicPropertyData" in v[0]:
                return v
            r = _find_results(v)
            if r:
                return r
    elif isinstance(o, list):
        for x in o:
            r = _find_results(x)
            if r:
                return r
    return None


def booking(st, checkin, checkout, guests):
    url = booking_url(st, checkin, checkout, guests)
    html = ""
    with page() as pg:
        pg.goto(url, timeout=60000)
        # The page runs a JS check first and reloads itself; wait until the result data is there.
        for _ in range(45):
            try:
                html = pg.content()
            except Exception:  # mid-navigation
                html = ""
            if "basicPropertyData" in html or "data-testid=\"property-card\"" in html:
                break
            pg.wait_for_timeout(1000)
    out = []
    for m in re.finditer(r'<script[^>]*data-capla-store-data="apollo"[^>]*>(.*?)</script>', html, re.S):
        if "basicPropertyData" not in m.group(1):
            continue
        for r in _find_results(json.loads(m.group(1))) or []:
            b = r.get("basicPropertyData") or {}
            price = (((r.get("priceDisplayInfoIrene") or {}).get("displayPrice") or {}).get("amountPerStay") or {})
            if price.get("currency") != "SEK" or not price.get("amountUnformatted"):
                continue
            rev = b.get("reviews") or b.get("reviewScore") or {}
            loc = b.get("location") or {}
            out.append({"source": "booking", "total": round(price["amountUnformatted"]),
                        "name": (r.get("displayName") or {}).get("text", ""),
                        "rating": rev.get("totalScore") or 0, "reviews": rev.get("reviewsCount") or 0,
                        "lat": loc.get("latitude"), "lon": loc.get("longitude"),
                        "url": f"https://www.booking.com/hotel/{loc.get('countryCode', 'xx')}/{b.get('pageName')}.sv.html?"
                               + urlencode({"checkin": checkin.isoformat(), "checkout": checkout.isoformat(),
                                            "group_adults": guests, "no_rooms": len(rooms_for(guests)),
                                            "selected_currency": "SEK"})})
        break
    if not out and "basicPropertyData" not in html:
        raise RuntimeError(t("src.booking_none"))
    return out


# --- Hotels.com ----------------------------------------------------------------------------------

def hotelscom_url(st, checkin, checkout, guests):
    q = [("destination", location(st)), ("startDate", checkin.isoformat()), ("endDate", checkout.isoformat()),
         ("adults", ",".join(str(n) for n in rooms_for(guests))), ("sort", "PRICE_LOW_TO_HIGH")]
    if "pool" in st.get("require", []):
        q.append(("amenities", "POOL"))
    if "ac" in st.get("require", []):
        q.append(("amenities", "AIR_CONDITIONING"))
    score = st.get("hotel_min_rating", 8.5)
    q.append(("guestRating", "45" if score >= 9 else "40" if score >= 8 else "35"))
    return "https://sv.hotels.com/Hotel-Search?" + urlencode(q)


def _strings(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v, path)
    elif isinstance(o, str):
        yield path, o


_BLOCKED = set()  # sources that showed a bot check this run: not asked again until the next run


def hotelscom(st, checkin, checkout, guests):
    if "hotels.com" in _BLOCKED:
        raise RuntimeError(t("src.hotelscom_bot_earlier"))
    url = hotelscom_url(st, checkin, checkout, guests)
    cards, title = [], ""
    with page() as pg:
        def on(r):
            if r.url.endswith("/graphql") and r.request.method == "POST":
                try:
                    rq = r.request.post_data_json
                    rq = rq[0] if isinstance(rq, list) else rq
                    if rq.get("operationName") == "PropertyListingQuery":
                        cards.extend(r.json()["data"]["propertySearch"]["propertySearchListings"])
                except Exception:
                    pass
        pg.on("response", on)
        pg.goto(url, timeout=60000)
        for _ in range(30):
            if cards:
                break
            pg.wait_for_timeout(1000)
        pg.wait_for_timeout(1000)
        try:
            title = pg.title()
        except Exception:
            pass
    out = []
    for c in cards:
        if c.get("__typename") != "LodgingCard":
            continue
        name = ((c.get("headingSection") or {}).get("heading")) or ""
        total = rating = reviews = None
        for p, s in _strings(c):
            if total is None and p.endswith("options.accessibilityLabel") and "nätter" in s:
                total = _num(s.split("är", 1)[-1])
            elif rating is None and p.endswith("reviewSummary.graphic.accessibility") and "av 10" in s:
                rating = float(s.split(" av")[0].replace(",", "."))
            elif reviews is None and "recension" in s and p.endswith(".text"):
                reviews = int(_num(s) or 0)
        link = ((c.get("cardLink") or {}).get("resource") or {}).get("value", "")
        ll = re.search(r"latLong=(-?[\d.]+)%2C(-?[\d.]+)", link)
        if total:
            out.append({"source": "hotels.com", "total": round(total), "name": name, "rating": rating or 0,
                        "reviews": reviews or 0, "lat": float(ll.group(1)) if ll else None,
                        "lon": float(ll.group(2)) if ll else None, "url": link.split("&pwa_ts")[0] or url})
    if not cards and "bot" in title.lower():
        _BLOCKED.add("hotels.com")
        raise RuntimeError(t("src.hotelscom_bot"))
    if not cards:
        raise RuntimeError(t("src.hotelscom_none"))
    return out


# --- Sembo ---------------------------------------------------------------------------------------

SEMBO_WS = "wss://smart-search.sembo.com/graphql"
SEMBO_CONTENT = "https://content-hc.sembo.com"


def sembo_polygon(text):
    r = httpx.get(f"{SEMBO_CONTENT}/CategorizedAutosuggestion", params={"term": text},
                  headers={"user-agent": UA}, timeout=30)
    r.raise_for_status()
    hits = [h for h in r.json() if h.get("polygonId")]
    return hits[0] if hits else None


def _hotel_ingredient(st, nights, suggestions=200):
    req = st.get("require", [])
    return {"polygonId": st["sembo_polygon"], "selectedHotelTypes": ["APARTMENT", "HOTEL", "HOUSE_OR_COTTAGE"],
            "maxNumberOfHotels": 200, "starRating": 0, "hasParking": False, "hasPool": "pool" in req,
            "hasSpa": False, "hasGym": False, "hasInternet": "wifi" in req, "hasElectricVehicleChargingStation": False,
            "hasAirConditioning": "ac" in req, "petsAreAllowed": False, "isBusinessProperty": False,
            "isFamilyProperty": False, "isGreenSustainableProperty": False, "freeCancellation": False,
            "boardBasis": [], "polygonIds": [], "ingredientType": "HOTEL", "numberOfNights": nights,
            "numberOfSuggestions": suggestions, "heartedHotels": [], "subIngredients": [], "suggestedBy": "CHEAPEST",
            "includeAlternativeResults": True}


def _sembo_query(name):
    return files("flightwatch").joinpath("queries", f"sembo_{name}.graphql").read_text()


def sembo_subscribe(recipe, query, timeout=120):
    """One subscription; returns the itineraries Sembo streams back."""
    import websockets

    async def run():
        payload = {"operationName": query, "query": _sembo_query(query), "variables": {"recipe": recipe}}
        async with websockets.connect(SEMBO_WS, subprotocols=["graphql-transport-ws"], origin="https://www.sembo.se",
                                      user_agent_header=UA, max_size=2 ** 25) as ws:
            await ws.send(json.dumps({"type": "connection_init"}))
            await asyncio.wait_for(ws.recv(), 30)
            await ws.send(json.dumps({"id": "1", "type": "subscribe", "payload": payload}))
            got = []
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                if m["type"] == "next":
                    got.append(m["payload"]["data"]["searchRecipeByItinerary"])
                elif m["type"] == "error":
                    raise RuntimeError(f"sembo: {str(m.get('payload'))[:160]}")
                else:
                    return got
    return asyncio.run(run())


def sembo_recipe(day: date, pax, ingredients):
    d = day.isoformat()
    return {"market": "https://www.sembo.se", "featureToggles": [], "skipCache": False,
            "returnEmptyIngredientResults": True, "sessionId": str(uuid.uuid4()), "metadata": {"sourceType": "PLANNER"},
            "bypassRoundtripLogic": False, "dontGroupByFlightNumbers": True, "avoidDateShift": True,
            "searchOnlyLiveSelectedDay": True, "pax": [{"numberOfAdults": n, "childAges": []} for n in pax],
            "startDateOnly": d, "endDateOnly": d, "selectedDate": d, "ingredients": ingredients}


def sembo_hotels(codes):
    if not codes:
        return {}
    inc = ["Hotels.HotelCode", "Hotels.Name", "Hotels.Position.Latitude.DecimalDegrees",
           "Hotels.Position.Longitude.DecimalDegrees", "Hotels.TypeOfHotel", "Hotels.MainPolygon.FullName"]
    q = [("SearchText", "hotel-code:" + ",".join(codes)), ("MaxNumberOfHotels", len(codes))] + \
        [("Include", i) for i in inc] + [("IncludeGroup", "Hotels.GuestRatings")]
    r = httpx.get(f"{SEMBO_CONTENT}/Hotels/GetHotels", params=q, headers={"user-agent": UA}, timeout=60)
    r.raise_for_status()
    return {h["HotelCode"]: h for h in r.json().get("Hotels", [])}


def sembo_page_url(st, checkin, nights, guests):
    import base64
    rec = {"market": "https://www.sembo.se", "ingredients": [{"ingredientType": "HOTEL", "numberOfNights": nights,
                                                              "polygonId": st["sembo_polygon"]}],
           "pax": [{"numberOfAdults": n, "childAges": []} for n in rooms_for(guests)]}
    b = base64.b64encode(quote(json.dumps(rec, separators=(",", ":"))).encode()).decode()
    return "https://www.sembo.se/travel/plan/hotel-selection/h0?" + urlencode({"recipe": b, "day": checkin.isoformat()})


def sembo(st, checkin, checkout, guests):
    if not st.get("sembo_polygon"):
        return []
    nights = (checkout - checkin).days
    its = sembo_subscribe(sembo_recipe(checkin, rooms_for(guests), [_hotel_ingredient(st, nights)]),
                          "searchItinerariesHotelSelection")
    hits = []
    for it in its:
        for res in it.get("result") or []:
            if not str(res.get("date", "")).startswith(checkin.isoformat()):
                continue
            for s in (res.get("suggestions") or []) + ([res["suggested"]] if res.get("suggested") else []):
                price = (s.get("prices") or {}).get("totalPrice") or s.get("totalPrice")
                if price and price.get("currency") == "SEK":
                    hits.append((s["code"], price["amount"], s.get("isRefundable")))
    hits = sorted({c: (c, p, rf) for c, p, rf in hits}.values(), key=lambda h: h[1])[:40]
    info = sembo_hotels([h[0] for h in hits])
    link = sembo_page_url(st, checkin, nights, guests)
    out = []
    for code, price, refundable in hits:
        h = info.get(code) or {}
        gr = h.get("GuestRatings") or {}
        pos = h.get("Position") or {}
        out.append({"source": "sembo", "total": round(price), "name": h.get("Name", code),
                    "rating": gr.get("OverallDuplicated") or 0, "reviews": gr.get("Count") or 0,
                    "lat": (pos.get("Latitude") or {}).get("DecimalDegrees"),
                    "lon": (pos.get("Longitude") or {}).get("DecimalDegrees"),
                    "refundable": refundable, "url": link})
    return out


SOURCES = {"booking": booking, "hotels.com": hotelscom, "sembo": sembo}


def search(st, checkin, checkout, guests, sources):
    """Qualifying hotels from every source, cheapest first, plus per-source errors."""
    found, errors = [], {}
    for name in sources:
        fn = SOURCES.get(name)
        if not fn:
            continue
        try:
            found += fn(st, checkin, checkout, guests)
        except Exception as e:
            errors[name] = str(e)[:140]
    min_rating = st.get("hotel_min_rating", 8.5)
    min_reviews = st.get("hotel_min_reviews", 20)
    ok = [h for h in found if h["rating"] >= min_rating and h["reviews"] >= min_reviews and _near(st, h["lat"], h["lon"])
          and not any(w in h["name"].lower() for w in DORM)]
    for h in ok:
        h["nights"] = (checkout - checkin).days
        h["rooms"] = len(rooms_for(guests))
    return sorted(ok, key=lambda h: h["total"]), errors, len(found)

