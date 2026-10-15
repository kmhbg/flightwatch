"""Sembo "Flyg + hotell": scheduled flights + a hotel booked together, as a package comparison.

Uses the same GraphQL-over-websocket API as the hotel search (see hotels.py). A recipe of
[flight out, hotel, flight home] priced for one day returns real flights (legs, bags) and the
cheapest hotel that meets the stay's pool/AC requirements. Packages house the travellers only
(two per room), like the other package sources.
"""
from datetime import date

from ..i18n import t
from ..models import Leg, Offer
from .hotels import DORM, _hotel_ingredient, rooms_for, sembo_hotels, sembo_page_url, sembo_recipe, sembo_subscribe


def _transport(a, b, stops):
    return {"transportTypes": ["FLIGHT"], "ingredientType": "TRANSPORT", "fromIata": a, "toIata": b,
            "maxNumberOfStops": stops, "suggestedBy": "CHEAPEST", "includeAlternativeResults": True}


def _leg(L):
    segs = L.get("segments") or []
    leg = Leg(depart=segs[0]["departureDateTime"][:16], arrive=segs[-1]["arrivalDateTime"][:16],
              duration_min=L.get("durationInMinutes") or 0, stops=max(0, len(segs) - 1))
    for i, s in enumerate(segs):
        code = s.get("operatingCarrier") or s.get("carrier")
        if code and code not in leg.carrier_codes:
            leg.carrier_codes.append(code)
            leg.carriers.append(code)
        if i < len(segs) - 1:
            leg.via.append(s["arrivalIata"])
            leg.layovers_min.append(s.get("layoverTimeUntilNextSegmentInMinutes") or 0)
    return leg


def _nights(origin, watch):
    """Hotel nights: long-haul flights land the day after departure."""
    from ..places import _airport_index, _distance_km
    idx = {a["code"]: a for a in _airport_index()}
    o, d = idx.get(origin), idx.get(watch["destination"])
    far = o and d and _distance_km(o["lat"], o["lon"], d["lat"], d["lon"]) > 4000
    return (watch["return"] - watch["depart"]).days - (1 if far else 0)


def search(origin, watch, cfg):
    st = watch.get("stay", {})
    if not st.get("sembo_polygon"):
        return []
    nights = _nights(origin, watch)
    if nights < 1:
        return []
    hotel = _hotel_ingredient(st, nights, suggestions=40)
    dest = watch["destination"]
    recipe = sembo_recipe(watch["depart"], rooms_for(watch["adults"]),
                          [_transport(origin, dest, watch["max_stops"]), hotel, _transport(dest, origin, watch["max_stops"])])
    its = sembo_subscribe(recipe, "searchItineraries")
    min_rating, min_reviews = st.get("hotel_min_rating", 8.5), st.get("hotel_min_reviews", 20)
    offers = []
    for it in its:
        if it.get("itineraryKey") != watch["depart"].strftime("%Y%m%d"):
            continue
        res = it.get("result") or []
        tr = [r for r in res if r.get("__typename") == "TransportIngredientResponseQL" and r.get("legs")]
        ho = [r for r in res if r.get("__typename") == "HotelIngredientResponseQL" and r.get("suggested")]
        if not tr or not ho:
            continue
        out = _leg(tr[0]["legs"][tr[0].get("legIndex") or 0])
        back = _leg(tr[-1]["legs"][tr[-1].get("legIndex") or -1])
        bags = tr[0]["legs"][0].get("luggageInformation") or []
        checked = next((b for b in bags if b.get("type") == "CheckedBag"), None)
        base = float(it["prices"]["totalPrice"]["amount"])
        # The suggested hotel is simply the cheapest; pick the cheapest one that meets the quality bar.
        sug = ho[0]["suggested"]
        cands = [(0.0, sug)] + [((s.get("prices") or {}).get("deltaPrice", {}).get("amount", 0.0), s)
                                for s in ho[0].get("suggestions") or [] if s["code"] != sug["code"]]
        info = sembo_hotels([c["code"] for _, c in cands])
        good = []
        for delta, c in cands:
            h = info.get(c["code"], {})
            gr = h.get("GuestRatings") or {}
            room = (c.get("rooms") or [{}])[0].get("description", "")
            if (gr.get("OverallDuplicated") or 0) >= min_rating and (gr.get("Count") or 0) >= min_reviews \
                    and not any(w in (room + h.get("Name", "")).lower() for w in DORM):
                good.append((base + delta, h, gr, room))
        for total, h, gr, room in sorted(good, key=lambda g: g[0])[:2]:
            offers.append(Offer(
                source="sembo", kind="package", origin=origin, destination=dest,
                depart_date=out.depart[:10], return_date=back.depart[:10],
                ticket_total=total, out=out, back=back,
                bags_included_pp=1 if checked and checked.get("included") else 0,
                bag_note=t("src.sembo_bag", kg=checked.get("weight") or "") if checked and checked.get("included")
                else t("src.sembo_nobag"),
                url=sembo_page_url(st, date.fromisoformat(out.arrive[:10]), nights, watch["adults"]),
                booking_via=t("src.sembo_via"),
                hotel=t("src.sembo_hotel", name=h.get("Name", "?"), nights=t("unit.night", n=nights), room=room,
                        rating=gr.get("OverallDuplicated")),
                conditions=t("src.sembo_cond", route=f"{origin}–{dest}")
                           + ("" if it["prices"].get("priceIsWithTaxesIncluded", True) else t("src.local_taxes")),
            ))
    return offers
