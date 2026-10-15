"""Apollo package trips (scheduled flight + hotel) as a comparison point.

Reverse-engineered 2026-10-12. Apollo's BFF sits behind a Cloudflare challenge, so it is NOT called
directly; we load the normal search page in headless Chromium, press "Sök" like a visitor would and
read the AccommodationListSearchByTravelAreaUri response the page receives.
"""
import json
from datetime import datetime

from ..i18n import t
from ..models import Leg, Offer
from .browser import click_if_present, page


def page_url(origin, watch, duration):
    ages = ",".join(["42"] * watch["adults"])
    return (f"https://www.apollo.se/booking-guide/core/list?departureAirportCode={origin}"
            f"&departureDate={watch['depart'].isoformat()}&duration={duration}&paxAges={ages}"
            f"&travelAreaUri={watch['charter']['apollo_travel_area']}")


def _leg(f):
    legs = f.get("Legs") or []
    leg = Leg(depart=f["DepartureDateTime"][:16], arrive=f["ArrivalDateTime"][:16],
              duration_min=f.get("DurationHours", 0) * 60 + f.get("DurationMinutes", 0), stops=max(0, len(legs) - 1))
    for i, l in enumerate(legs):
        if l["OperatingCarrierName"] not in leg.carriers:
            leg.carriers.append(l["OperatingCarrierName"])
            leg.carrier_codes.append(l.get("IataOperatingCarrierCode") or l.get("OperatingCarrierCode"))
        if i < len(legs) - 1:
            leg.via.append(l["ArrivalAirportName"])
            nxt = legs[i + 1]
            gap = datetime.fromisoformat(nxt["DepartureDateTime"]) - datetime.fromisoformat(l["ArrivalDateTime"])
            leg.layovers_min.append(int(gap.total_seconds() // 60))
    return leg


def search(origin, watch, cfg, limit=5):
    area = watch["charter"].get("apollo_travel_area")
    if not area:
        return []
    # Apollo's "duration" is counted from departure to hotel check-out; the flight home can leave
    # after midnight, so days-1 lands closest to the wanted return. Real dates are read back.
    duration = max(1, (watch["return"] - watch["depart"]).days - 1)
    url = page_url(origin, watch, duration)
    found = {}
    with page() as pg:
        def on_response(r):
            if "AccommodationListSearchByTravelAreaUri" in r.url and r.status == 200:
                try:
                    body = json.loads(r.text())
                except Exception:
                    return
                if body.get("SelectableAccommodations"):
                    found["data"] = body
        pg.on("response", on_response)
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(4000)
        click_if_present(pg, "Acceptera")
        pg.wait_for_timeout(1500)
        pg.get_by_role("button", name="Sök", exact=True).last.click(timeout=15000)
        for _ in range(45):
            if "data" in found:
                break
            pg.wait_for_timeout(1000)
    if "data" not in found:
        raise RuntimeError("apollo: inga paket hittades (eller sidan svarade inte)")
    want = watch["return"].isoformat()

    def miss(a):  # days between the package's flight home and the wanted return date
        home = a["FlightPackage"]["Inbound"]["DepartureDateTime"][:10]
        return abs((datetime.fromisoformat(home) - datetime.fromisoformat(want)).days)
    accs = sorted(found["data"]["SelectableAccommodations"], key=lambda a: (miss(a) > 1, a["Price"]))
    offers = []
    for a in accs[:limit]:
        fp = a["FlightPackage"]
        out, back = _leg(fp["Outbound"]), _leg(fp["Inbound"])
        stay = a.get("HotelStay") or {}
        offers.append(Offer(
            source="apollo", kind="package", origin=origin, destination=watch["destination"],
            depart_date=out.depart[:10], return_date=back.depart[:10],
            ticket_total=float(a["Price"]), out=out, back=back,
            url=url, booking_via=t("src.apollo_via"),
            hotel=t("src.hotel_nights_class", name=a["Content"]["Name"],
                    nights=t("unit.night", n=stay["Stay"]) if stay.get("Stay") else "?",
                    cls=a["Content"].get("Classification", "?")),
            conditions=t("src.package_cond"),
        ))
    return offers
