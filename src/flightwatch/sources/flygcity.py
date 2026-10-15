"""flygcity.se (Swedish OTA, Rails app).

Reverse-engineered 2026-10-12. The site's own flow, done with a normal session:
GET / (session cookie + csrf-token) → POST /new_search (the search form) → {"url": "/flyg/steg-1/<id>"}
→ poll POST /capi/SearchChannel/status → POST /capi/SearchChannel/run_filter (itinerary JSON).
With search[only_with_bags]=true every result includes checked baggage.
"""
import re
import time
from datetime import datetime

import httpx

from ..i18n import t
from ..models import Leg, Offer

BASE = "https://www.flygcity.se"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"


def _place_id(c, kind, iata):
    j = c.get(f"{BASE}/autocomplete/{kind}/flight", params={"term": iata}).json()
    for group in ("cities", "airports"):
        for p in j.get(group) or []:
            if p.get("iata") == iata:
                return str(p["id"]), p["fullname"]
    raise RuntimeError(f"flygcity: hittar inte {iata}")


def _csrf(html):
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def _minutes(s):
    h = re.search(r"(\d+)h", s or "")
    m = re.search(r"(\d+)m", s or "")
    return (int(h.group(1)) if h else 0) * 60 + (int(m.group(1)) if m else 0)


def _leg(l):
    segs = l["segments"]
    # *_time_raw is local wall-clock time tagged as Z.
    leg = Leg(depart=segs[0]["dep_time_raw"][:16], arrive=segs[-1]["arr_time_raw"][:16],
              duration_min=_minutes(l.get("travel_time")), stops=len(segs) - 1,
              self_transfer=bool(l.get("change_airport")))
    for i, s in enumerate(segs):
        if s["op_carrier"] not in leg.carriers:
            leg.carriers.append(s["op_carrier"])
            leg.carrier_codes.append(s["op_carrier_code"])
        if i < len(segs) - 1:
            leg.via.append(s["destination_code"])
            leg.layovers_min.append(segs[i + 1].get("connection_time") or 0)
    if not leg.duration_min:
        leg.duration_min = int((datetime.fromisoformat(leg.arrive) - datetime.fromisoformat(leg.depart)).total_seconds() // 60)
    return leg


def search(origin, watch, cfg, max_stops=1, pages=3):
    dep, ret = watch["depart"], watch["return"]
    with httpx.Client(headers={"user-agent": UA}, timeout=60) as c:
        home = c.get(BASE + "/").text
        o_id, o_text = _place_id(c, "origin", origin)
        d_id, d_text = _place_id(c, "destination", watch["destination"])
        form = {
            "authenticity_token": _csrf(home), "search[type]": "return",
            "search[legs][0][origin_id]": o_id, "search[legs][0][origin_text]": o_text,
            "search[legs][0][destination_id]": d_id, "search[legs][0][destination_text]": d_text,
            "search[legs][0][date]": dep.isoformat(), "search[legs][1][date]": ret.isoformat(),
            "search[adults]": str(watch["adults"]), "search[no_children]": "0", "search[youths]": "0",
            "search[cabin]": "EC", "search[only_with_bags]": "true", "search[airline]": "", "commit": "Sök flyg",
        }
        if max_stops is not None and max_stops <= 1:
            form["search[max_one_stop]"] = "true"
        r = c.post(BASE + "/new_search", data=form, headers={
            "x-csrf-token": form["authenticity_token"], "x-requested-with": "XMLHttpRequest",
            "accept": "application/json, text/javascript", "referer": BASE + "/"})
        m = re.search(r"steg-1/(\d+)", r.text)
        if not m:
            raise RuntimeError(f"flygcity: oväntat svar på sökningen ({r.status_code})")
        sid = m.group(1)
        url = f"{BASE}/flyg/steg-1/{sid}"
        hdr = {"x-csrf-token": _csrf(c.get(url).text), "content-type": "application/json",
               "x-requested-with": "XMLHttpRequest"}
        for _ in range(45):
            st = c.post(f"{BASE}/capi/SearchChannel/status?search_id={sid}", content="{}", headers=hdr).json()
            if st.get("items") != "searching":
                break
            time.sleep(2)
        seen, offers = set(), []
        body = "{}"
        for _ in range(pages):
            j = c.post(f"{BASE}/capi/SearchChannel/run_filter?search_id={sid}", content=body, headers=hdr).json()
            items = j.get("items") or {}
            data = (items.get("itineraries") or {}).get("data") or []
            new = [it for it in data if it["attributes"]["uuid"] not in seen]
            if not new:
                break
            for it in new:
                a = it["attributes"]
                seen.add(a["uuid"])
                out, back = _leg(a["itinerary"][0]), _leg(a["itinerary"][1])
                bag = a["itinerary"][0]["segments"][0].get("baggage") or {}
                offers.append(Offer(
                    source="flygcity", kind="flight", origin=origin, destination=watch["destination"],
                    depart_date=dep.isoformat(), return_date=ret.isoformat(),
                    ticket_total=float(a["price_raw"]), out=out, back=back,
                    bags_included_pp=1 if a.get("bags_included") else 0,
                    bag_note=t("src.flygcity_bags", what=bag.get("text", "?")) if a.get("bags_included") else "",
                    url=url, booking_via="flygcity.se",
                    conditions=t("src.flygcity_cond", kind=a.get("search_type", ""), seats=a.get("seats", "?"))
                               + (t("src.airport_change") if out.self_transfer or back.self_transfer else ""),
                ))
            body = '{"offset": %d}' % (items.get("current_offset") or len(seen))
        return offers
