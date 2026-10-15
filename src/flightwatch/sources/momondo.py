"""momondo (KAYAK group) – meta search over airlines and agencies.

Reverse-engineered 2026-10-12. The results page polls POST /i/api/search/dynamic/flights/poll with a
page-issued x-csrf token and session, so it is not called directly: the normal results page is loaded
in headless Chromium and the poll responses it receives are read. Each booking option carries the
provider, whether it is the airline itself (flags.isDirect), total price and included checked bags.
"""
import json

from ..i18n import money, t
from ..models import Leg, Offer
from .browser import click_if_present, page

BASE = "https://www.momondo.se"


def search_url(origin, watch):
    return (f"{BASE}/flight-search/{origin}-{watch['destination']}/{watch['depart'].isoformat()}/"
            f"{watch['return'].isoformat()}/{watch['adults']}adults?sort=price_a"
            + ("&fs=stops=0,1" if watch.get("max_stops", 1) <= 1 else ""))


def _leg(data, leg_id):
    lg = data["legs"][leg_id]
    segs = [data["segments"][s["id"]] for s in lg["segments"]]
    leg = Leg(depart=lg["departure"][:16], arrive=lg["arrival"][:16], duration_min=lg.get("duration", 0),
              stops=len(segs) - 1)
    for i, s in enumerate(segs):
        name = s.get("operationalDisplay") or (data.get("airlines", {}).get(s["airline"]) or {}).get("name", s["airline"])
        if name not in leg.carriers:
            leg.carriers.append(name)
            leg.carrier_codes.append(s["airline"])
        if i < len(segs) - 1:
            leg.via.append(s["destination"])
            leg.layovers_min.append((lg["segments"][i].get("layover") or {}).get("duration", 0))
    return leg


def _bags(option):
    """(included checked bags per person or None, price for an extra bag or None)."""
    for a in option.get("fareAmenities") or []:
        if a.get("type") == "CHECKED_BAG":
            if a.get("restriction") == "INCLUDED":
                return a.get("includedCheckedBagCount", 1), None
            fee = ((a.get("prices") or {}).get("FIRST_BAG") or {}).get("price")
            return 0, fee
    return None, None


def parse(data, origin, watch):
    offers = []
    for r in data.get("results") or []:
        if r.get("type") != "core" or len(r.get("legs") or []) != 2 or not r.get("bookingOptions"):
            continue
        out, back = _leg(data, r["legs"][0]["id"]), _leg(data, r["legs"][1]["id"])
        for opt in r["bookingOptions"][:1] + [o for o in r["bookingOptions"][1:] if (o.get("flags") or {}).get("isDirect")][:1]:
            total = ((opt.get("fees") or {}).get("totalPrice") or {}).get("price")
            if not total:
                continue
            provider = (data.get("providers", {}).get(opt.get("providerCode")) or {}).get("displayName") or opt.get("providerCode", "")
            direct = bool((opt.get("flags") or {}).get("isDirect"))
            included, fee = _bags(opt)
            fare = ", ".join((opt.get("detailedFareAttributes") or [{}])[0].get("localizedFareDisplayNames") or [])
            offers.append(Offer(
                source="airline" if direct else "momondo", kind="flight", origin=origin, destination=watch["destination"],
                depart_date=watch["depart"].isoformat(), return_date=watch["return"].isoformat(),
                ticket_total=float(total), out=out, back=back,
                bags_included_pp=included, extra_bag_fee=fee,
                bag_note=(t("src.momondo_incl", n=included) if included else
                          t("src.momondo_fee", fee=money(fee)) if fee else
                          t("src.momondo_none") if included == 0 else ""),
                url=BASE + r["shareableUrl"] if r.get("shareableUrl") else search_url(origin, watch),
                booking_via=t("src.via_momondo", who=f"{provider}{t('src.direct_suffix') if direct else ''}"),
                conditions=(f"Biljettyp: {fare}" if fare else "") + ("; bokas hos flygbolaget" if direct else ""),
            ))
    return offers


def search(origin, watch, cfg):
    url = search_url(origin, watch)
    polls = []
    with page() as pg:
        def on_response(r):
            if "/flights/poll" in r.url and r.status == 200:
                try:
                    polls.append(json.loads(r.text()))
                except Exception:
                    pass
        pg.on("response", on_response)
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        click_if_present(pg, "Avvisa alla", 3000) or click_if_present(pg, "Acceptera alla", 2000)
        for _ in range(50):  # the search streams in; stop when momondo says it's complete
            if any(p.get("status") == "complete" for p in polls):
                break
            pg.wait_for_timeout(1000)
    full = [p for p in polls if p.get("results")]
    if not full:
        raise RuntimeError("momondo: inga resultat (blockerad eller tomt svar)")
    best = max(full, key=lambda p: (p.get("status") == "complete", len(p["results"])))
    return parse(best, origin, watch)
