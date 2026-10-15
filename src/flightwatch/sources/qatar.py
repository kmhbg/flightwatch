"""Qatar Airways direct prices (qatarairways.com).

Reverse-engineered 2026-10-12. The booking page posts to /dapi/public/bff/web/flight-search/flight-offers;
the site runs Akamai bot management, so the API is not called directly – the normal flight-selection
page is loaded in headless Chromium and the response it receives is read. Prices are round-trip totals
for all passengers in the point-of-sale currency (DKK from Copenhagen), converted with ECB rates.
"""
import json
import re
from functools import lru_cache

import httpx

from ..i18n import t
from ..models import Leg, Offer
from .browser import click_if_present, page


def page_url(origin, watch):
    return ("https://www.qatarairways.com/app/booking/flight-selection?widget=QR&searchType=F&addTaxToFare=Y"
            f"&minPurTime=0&selLang=en&tripType=R&fromStation={origin}&toStation={watch['destination']}"
            f"&departing={watch['depart'].isoformat()}&returning={watch['return'].isoformat()}"
            f"&bookingClass=E&adults={watch['adults']}")


@lru_cache(maxsize=8)
def to_sek(currency):
    if currency == "SEK":
        return 1.0
    r = httpx.get("https://api.frankfurter.dev/v1/latest", params={"base": currency, "symbols": "SEK"}, timeout=20)
    return float(r.json()["rates"]["SEK"])


def _leg(fo):
    ids = [s["flightId"] for s in fo["segments"]]  # SEG-QR160-CPHDOH-2026-12-14-1505
    first = re.match(r"SEG-[^-]+-\w{6}-(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})", ids[0])
    leg = Leg(depart=f"{first.group(1)}T{first.group(2)}:{first.group(3)}" if first else "",
              duration_min=round(fo["duration"] / 60), stops=fo.get("numberOfStops", len(ids) - 1))
    for s in fo["segments"]:
        if s["operatingAirlineName"] not in leg.carriers:
            leg.carriers.append(s["operatingAirlineName"])
            leg.carrier_codes.append(s["flightNumber"][:2])
    leg.via = [re.match(r"SEG-[^-]+-(\w{3})", i).group(1) for i in ids[1:]]
    leg.layovers_min = [round(s.get("connectionTime", 0) / 60) for s in fo["segments"][:-1]]
    return leg


def _feature(fare, kind):
    f = next((x for x in fare.get("fareFamilyFeatures") or [] if x.get("type") == kind), None)
    return f.get("parameters") if f else None


def search(origin, watch, cfg):
    url = page_url(origin, watch)
    found = {}
    with page() as pg:
        def on_response(r):
            if "flight-search/flight-offers" in r.url and r.status == 200:
                try:
                    found["data"] = json.loads(r.text())
                except Exception:
                    pass
        pg.on("response", on_response)
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(2000)
        click_if_present(pg, "Accept", 3000)
        for _ in range(40):
            if "data" in found:
                break
            pg.wait_for_timeout(1000)
    if "data" not in found:
        raise RuntimeError("qatar: inget svar (blockerad eller ingen trafik på sträckan)")
    offers = []
    for fo in found["data"].get("flightOffers") or []:
        economy = [f for f in fo.get("fareOffers") or [] if f.get("cabinType") == "ECONOMY" and f.get("price")]
        if not economy:
            continue
        fare = min(economy, key=lambda f: f["price"]["total"])
        rate = to_sek(fare["price"]["currencyCode"])
        bag = _feature(fare, "CHECKIN_BAGGAGE")
        change = _feature(fare, "CHANGE_PENALTY")
        family = fare.get("fareFamilyCode", "").replace("ECONOMY_", "").title()
        out = _leg(fo)
        offers.append(Offer(
            source="airline", kind="flight", origin=origin, destination=watch["destination"],
            depart_date=watch["depart"].isoformat(), return_date=watch["return"].isoformat(),
            ticket_total=round(fare["price"]["total"] * rate), out=out,
            back=Leg(carriers=out.carriers, carrier_codes=out.carrier_codes, stops=out.stops),
            bags_included_pp=1 if bag else 0,
            bag_note=t("src.qatar_bag", family=family, kg=bag[0]) if bag else t("src.qatar_nobag", family=family),
            url=url, booking_via=t("src.qatar_via"),
            conditions=(t("src.qatar_ticket", family=family,
                          price=f"{fare['price']['total']:,} {fare['price']['currencyCode']}".replace(",", " "))
                        + (t("src.qatar_change") if change else "")
                        + t("src.qatar_return")),
        ))
    return offers
