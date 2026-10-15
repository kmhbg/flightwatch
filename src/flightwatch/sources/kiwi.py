"""Kiwi.com via its public (anonymous) GraphQL endpoint, the same call kiwi.com makes in the browser.

Reverse-engineered 2026-10-12: POST api.skypicker.com/umbrella/v2/graphql?featureName=...
with only content-type set; no auth or tokens needed. Prices include the requested checked bags.
"""
from datetime import timedelta
from importlib.resources import files

import httpx

from ..i18n import t
from ..models import Leg, Offer

URL = "https://api.skypicker.com/umbrella/v2/graphql?featureName="
_Q = files("flightwatch").joinpath("queries")
SEARCH_Q = _Q.joinpath("search_return.graphql").read_text()
MATRIX_Q = _Q.joinpath("price_matrix.graphql").read_text()
HEADERS = {"content-type": "application/json", "user-agent": "Mozilla/5.0 (X11; Linux x86_64) flightwatch"}


def _variables(origin, dest, dep, ret, adults, bags_pp, cabin, max_stops, currency, dep_span=0, ret_span=0):
    def window(d, span):
        return {"start": f"{(d - timedelta(days=span)).isoformat()}T00:00:00",
                "end": f"{(d + timedelta(days=span)).isoformat()}T23:59:59"}
    flt = {
        "allowReturnFromDifferentCity": False, "allowChangeInboundDestination": False,
        "allowChangeInboundSource": False, "allowDifferentStationConnection": True,
        "enableSelfTransfer": True, "enableThrowAwayTicketing": False, "enableTrueHiddenCity": False,
        "transportTypes": ["FLIGHT"], "contentProviders": ["KIWI", "FRESH"], "flightsApiLimit": 25, "limit": 30,
    }
    if max_stops is not None:
        flt["maxStopsCount"] = max_stops
    return {
        "search": {
            "itinerary": {"source": {"ids": [f"Station:airport:{origin}"]},
                          "destination": {"ids": [f"Station:airport:{d}" for d in ([dest] if isinstance(dest, str) else dest)]},
                          "outboundDepartureDate": window(dep, dep_span),
                          "inboundDepartureDate": window(ret, ret_span)},
            "passengers": {"adults": adults, "children": 0, "infants": 0,
                           "adultsHoldBags": [bags_pp] * adults, "adultsHandBags": [0] * adults,
                           "childrenHoldBags": [], "childrenHandBags": []},
            "cabinClass": {"cabinClass": cabin, "applyMixedClasses": False},
        },
        "filter": flt,
        "options": {"sortBy": "PRICE", "mergePriceDiffRule": "INCREASED", "contentProviders": ["KIWI", "FRESH"],
                    "currency": currency.lower(), "apiUrl": None, "locale": "en", "market": "se",
                    "partner": "skypicker", "partnerMarket": "se", "affilID": "skypicker", "storeSearch": False,
                    "searchStrategy": "REDUCED",
                    "kiwiClub": {"isKiwiClubMember": False, "isPhoneVerified": False, "kiwiClubPerksEligible": False}},
        "conditions": False,
    }


def _post(feature, query, variables, timeout=90):
    r = httpx.post(URL + feature, json={"query": query, "variables": variables}, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(f"kiwi: {j['errors'][0].get('message')}")
    return j["data"]


def _leg(sector):
    segs = sector["sectorSegments"]
    first, last = segs[0]["segment"], segs[-1]["segment"]
    leg = Leg(depart=first["source"]["localTime"][:16], arrive=last["destination"]["localTime"][:16],
              duration_min=round(sector["duration"] / 60), stops=len(segs) - 1)
    for s in segs:
        seg = s["segment"]
        if seg["carrier"]["name"] not in leg.carriers:
            leg.carriers.append(seg["carrier"]["name"])
            leg.carrier_codes.append(seg["carrier"]["code"])
        lay = s.get("layover")
        if lay:
            leg.via.append(seg["source"]["station"]["code"])
            leg.layovers_min.append(round(lay["duration"] / 60))
            if lay.get("isBaggageRecheck"):
                leg.self_transfer = True
    return leg


def search(origin, watch, cfg, bags_pp, max_stops):
    """Itineraries for the exact dates. Kiwi can rarely sell 2 checked bags/person on these
    routes (the search then returns nothing), so the runner asks for what Kiwi can sell."""
    dep, ret = watch["depart"], watch["return"]
    v = _variables(origin, watch["destinations"], dep, ret, watch["adults"], bags_pp, watch["cabin"],
                   max_stops, "SEK")
    data = _post("SearchReturnItinerariesQuery", SEARCH_Q, v)["returnItineraries"]
    if "itineraries" not in data:
        raise RuntimeError(f"kiwi: {data.get('error') or data}")
    offers = []
    for it in data["itineraries"]:
        bi = it.get("bagsInfo") or {}
        node = (it.get("bookingOptions") or {}).get("edges", [{}])[0].get("node") or {}
        out, back = _leg(it["outbound"]), _leg(it["inbound"])
        pnr = it.get("pnrCount") or 1
        hacks = it.get("travelHack") or {}
        warn = []
        if pnr > 1:
            warn.append(t("src.separate_tickets", n=pnr))
        if out.self_transfer or back.self_transfer:
            warn.append(t("src.kiwi_self_transfer"))
        if hacks.get("isVirtualInterlining"):
            warn.append(t("src.kiwi_virtual"))
        included = bi.get("includedCheckedBags")
        offers.append(Offer(
            source="kiwi", kind="flight", origin=origin,
            destination=it["outbound"]["sectorSegments"][-1]["segment"]["destination"]["station"]["code"],
            depart_date=dep.isoformat(), return_date=ret.isoformat(),
            ticket_total=float(it["price"]["amount"]), currency="SEK",
            out=out, back=back,
            # includedCheckedBags counts the whole booking (all passengers).
            bags_included_pp=included // watch["adults"] if included is not None else bags_pp,
            bag_note=t("src.kiwi_bags", n=bags_pp),
            url="https://www.kiwi.com" + node["bookingUrl"] if node.get("bookingUrl") else search_url(origin, watch, bags_pp),
            booking_via=(it.get("provider") or {}).get("name") or "Kiwi.com",
            tickets=pnr, conditions="; ".join(warn) or "Ordinarie biljett via Kiwi.com",
        ))
    return offers


def search_url(origin, watch, bags_pp):
    return (f"https://www.kiwi.com/en/search/results/{origin.lower()}/{watch['destination'].lower()}/"
            f"{watch['depart'].isoformat()}/{watch['return'].isoformat()}"
            f"?adults={watch['adults']}&bags={'-'.join(['0.%d' % bags_pp] * watch['adults'])}&currency=sek")


def price_matrix(origin, watch, cfg, bags_pp, max_stops):
    """Whole flexible window in one call: {(dep_iso, ret_iso): total incl. bags_pp checked bags}.
    These are Kiwi's cached prices; the runner verifies the best pairs with real searches."""
    w = watch
    v = _variables(origin, w["destinations"], w["earliest_depart"], w["latest_return"], w["adults"], bags_pp,
                   w["cabin"], max_stops, "SEK")
    (d0, d1), (r0, r1) = w["depart_range"], w["return_range"]
    v["search"]["itinerary"]["outboundDepartureDate"] = {"start": f"{d0}T00:00:00", "end": f"{d1}T23:59:59"}
    v["search"]["itinerary"]["inboundDepartureDate"] = {"start": f"{r0}T00:00:00", "end": f"{r1}T23:59:59"}
    v["filter"].pop("limit", None)
    data = _post("PriceMatrixRendererQuery", MATRIX_Q, v)["itineraryPriceTable"]
    out = {}
    for p in data.get("priceList") or []:
        if p and p.get("price") and p["price"].get("amount"):
            out[(p["outboundDate"][:10], p["inboundDate"][:10])] = float(p["price"]["amount"])
    return out
