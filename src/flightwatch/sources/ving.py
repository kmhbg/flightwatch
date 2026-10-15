"""Ving (Nordic Leisure Travel Group) flight-only search with scheduled flights.

Reverse-engineered 2026-10-12 from ving.se/boka-flyg: the page calls a plain GET through
independentweb.nltg.com/api/proxy, which works without cookies or tokens.
Ving's texts say one checked bag (18–23 kg) is included on these flights.
"""
import re
from datetime import date, timedelta
from urllib.parse import quote

import httpx

from ..config import AIRPORTS
from ..i18n import money
from ..i18n import t as tr
from ..models import Leg, Offer

API = "https://independentweb.nltg.com/api/proxy?url="
INNER = ("//bwoty-independentwebapi-prd.azurewebsites.net/api/flight?adults={adults}&departureAirportId={dep}"
         "&destinationAirportId={dest}&departureDate={d1}&returnDate={d2}&siteId=1&userId=Z01&newCheckout=true")


def page_url(ving_id, watch):
    ch = watch["charter"]
    ages = ",".join(["42"] * watch["adults"])
    return (f"https://www.ving.se/boka-flyg?QueryDepID={ving_id}&QueryCtryID={ch['ving_country_id']}"
            f"&QueryDestID={ch['ving_destination_id']}&QueryDepDate={watch['depart']:%Y%m%d}"
            f"&QueryDur={(watch['return'] - watch['depart']).days}&QueryRetDate={watch['return']:%Y%m%d}"
            f"&CategoryId=5&QueryRoomAges=|{ages}&QueryAdults={watch['adults']}&QueryChildrenAges=")


def _minutes(s):
    h = re.search(r"(\d+) tim", s or "")
    m = re.search(r"(\d+) min", s or "")
    return (int(h.group(1)) if h else 0) * 60 + (int(m.group(1)) if m else 0)


def _leg(f):
    dep = f["departureDateTime"][:16]
    arr_day = date.fromisoformat(dep[:10]) + timedelta(days=f.get("arrivalDaysAfterDeparture") or 0)
    legs = f.get("legs") or []
    leg = Leg(depart=dep, arrive=f"{arr_day.isoformat()}T{f['arrivalTime']}", duration_min=_minutes(f["flightTime"]),
              stops=int(f.get("totalNumberOfStops") or max(0, len(legs) - 1)))
    for i, l in enumerate(legs):
        name = l.get("operatingCarrierName") or l["carrierName"]
        if name not in leg.carriers:
            leg.carriers.append(name)
        if i < len(legs) - 1:
            leg.via.append(l["arrivalLocation"])
            leg.layovers_min.append(_minutes(l.get("timeOnStopOver")))
    return leg


def _tax(text):
    """Ving writes "1 234:-"; show it in the chosen currency."""
    digits = re.sub(r"\D", "", text.split(",")[0])
    return money(int(digits)) if digits else text


def search(origin, watch, cfg):
    ving_id = AIRPORTS.get(origin, {}).get("ving_id")
    if not ving_id or not watch["charter"].get("ving_destination_id"):
        return []
    inner = INNER.format(adults=watch["adults"], dep=ving_id, dest=watch["charter"]["ving_destination_id"],
                         d1=watch["depart"].isoformat(), d2=watch["return"].isoformat())
    r = httpx.get(API + quote(inner, safe=""), headers={"user-agent": "Mozilla/5.0 flightwatch",
                                                        "referer": "https://www.ving.se/"}, timeout=90)
    r.raise_for_status()
    j = r.json()
    if not j.get("result"):
        raise RuntimeError(f"ving: {j.get('errorMessage') or 'tomt svar'}")
    url = page_url(ving_id, watch)
    offers = []
    for t in j["result"].get("transports") or []:
        if not t.get("outBoundFlights") or not t.get("homeBoundFlights"):
            continue
        out, back = _leg(t["outBoundFlights"][0]), _leg(t["homeBoundFlights"][0])
        code = t.get("carrierCode")
        if code:
            out.carrier_codes = back.carrier_codes = [code]
        pb = t["priceBreakDown"]
        offers.append(Offer(
            source="ving", kind="flight", origin=origin, destination=watch["destination"],
            depart_date=watch["depart"].isoformat(), return_date=watch["return"].isoformat(),
            ticket_total=float(pb["totalPriceDouble"]), out=out, back=back,
            bags_included_pp=1 if t.get("luggageIncluded") else 0,
            bag_note=tr("src.ving_bag") if t.get("luggageIncluded") else tr("src.ving_nobag"),
            url=url, booking_via=tr("src.ving_via"),
            conditions=tr("src.ving_cond", tax=_tax(pb.get("flightTax", ""))),
        ))
    return offers
