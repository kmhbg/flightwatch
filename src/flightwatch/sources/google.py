"""Google Flights, read the same way the google-flights skill does: open the ?q= search URL and parse
the accessible 'link' labels of the result list. Google shows round-trip totals but no checked-bag
prices (in Sweden its Bags filter only covers carry-on), so bag cost is completed from config."""
import re
from datetime import datetime
from urllib.parse import quote_plus

from ..i18n import money, t
from ..models import Leg, Offer
from .browser import click_if_present, page

LABEL = re.compile(
    r"From (?P<price>[\d,]+) Swedish kronor round trip total\. (?P<stops>Nonstop|\d+ stops?) flight with (?P<air>.+?)\."
    r"(?: Operated by [^.]+\.)? Leaves (?P<from>.+?) at (?P<dt>[\d:]+\s?[AP]M) on \w+, (?P<dd>\w+ \d+) and arrives at"
    r" (?P<to>.+?) at (?P<at>[\d:]+\s?[AP]M) on \w+, (?P<ad>\w+ \d+)\. Total duration (?P<dur>[^.]+)\.(?P<rest>.*)")
IATA = {"Qatar Airways": "QR", "Emirates": "EK", "Etihad": "EY", "Turkish Airlines": "TK", "THAI": "TG",
        "Singapore Airlines": "SQ", "Scandinavian Airlines": "SK", "KLM": "KL", "Lufthansa": "LH",
        "Finnair": "AY", "Vietnam Airlines": "VN", "Malaysia Airlines": "MH", "Garuda Indonesia": "GA",
        "Cathay Pacific": "CX", "China Southern": "CZ", "China Eastern": "MU", "Air France": "AF",
        "British Airways": "BA", "Swiss": "LX", "Austrian": "OS", "Batik Air": "ID", "AirAsia": "AK",
        "Scoot": "TR", "Jetstar": "JQ", "Air China": "CA", "Saudia": "SV", "Oman Air": "WY"}
LAYOVER = re.compile(r"is a (?P<d>[\d hrmin]+?) (?:overnight )?layover at (?P<ap>.+?) in (?P<city>[^.]+)\.")


def search_url(origin, watch):
    q = (f"Flights from {origin} to {watch['destination']} on {watch['depart'].isoformat()} "
         f"returning {watch['return'].isoformat()} {watch['adults']} passengers")
    return f"https://www.google.com/travel/flights?q={quote_plus(q)}&curr=SEK&hl=en&gl=SE"


def _minutes(s):
    h = re.search(r"(\d+) hr", s)
    m = re.search(r"(\d+) min", s)
    return (int(h.group(1)) if h else 0) * 60 + (int(m.group(1)) if m else 0)


def _time24(t):
    hh, mm = re.match(r"(\d+):(\d+)", t).groups()
    hh = int(hh) % 12 + (12 if "PM" in t else 0)
    return f"{hh:02d}:{mm}"


def _date(md, ref):
    """'December 20' -> ISO date in the year that follows ref (handles new-year rollover)."""
    d = datetime.strptime(f"{md} {ref.year}", "%B %d %Y").date()
    return d.replace(year=ref.year + 1) if d < ref else d


BOOK = re.compile(r"Continue to book with (?P<who>.+?)(?P<airline> airline)? for (?P<price>[\d,]+) Swedish kronor")


def _leg(m, ref):
    """Leg from a parsed result label; dates are resolved relative to ref (the window start)."""
    stops = 0 if m["stops"] == "Nonstop" else int(m["stops"].split()[0])
    lays = list(LAYOVER.finditer(m["rest"]))
    air = [a.strip() for a in re.split(r",| and ", m["air"]) if a.strip()]
    return Leg(depart=f"{_date(m['dd'], ref).isoformat()}T{_time24(m['dt'])}",
               arrive=f"{_date(m['ad'], ref).isoformat()}T{_time24(m['at'])}", duration_min=_minutes(m["dur"]),
               stops=stops, via=[x["city"] for x in lays], layovers_min=[_minutes(x["d"]) for x in lays],
               carriers=air, carrier_codes=[IATA[a] for a in air if a in IATA])


def parse(labels, origin, watch, url, with_index=False):
    offers = []
    for idx, lab in enumerate(labels):
        m = LABEL.search(lab)
        if not m:
            continue
        out = _leg(m, watch["depart"])
        offers.append(Offer(
            source="google", kind="flight", origin=origin, destination=watch["destination"],
            depart_date=watch["depart"].isoformat(), return_date=watch["return"].isoformat(),
            ticket_total=float(m["price"].replace(",", "")), out=out,
            back=Leg(carriers=out.carriers, carrier_codes=out.carrier_codes),
            url=url, booking_via=t("src.google_via_ota"),
            conditions=t("src.google_next_step"),
        ))
        if with_index:
            offers[-1] = (idx, offers[-1])
    return offers


RESULT = "[aria-label^='From ']"


def _open_results(pg, url):
    pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    if "consent.google" in pg.url:
        click_if_present(pg, "Reject all", 8000)
    pg.wait_for_selector(RESULT, timeout=45000)
    pg.wait_for_timeout(1500)


def _booking(pg, url, index, offer, watch):
    """Select outbound #index and the cheapest return, then read Google's 'Booking options'.
    Returns (back_leg, [{"who", "price", "airline"}], booking_url)."""
    _open_results(pg, url)
    pg.locator(RESULT).nth(index).evaluate("e => e.click()")
    pg.wait_for_selector("text=Returning flights", timeout=30000)
    ret_sel = f"{RESULT}[aria-label*='Leaves'][aria-label*='{watch['return'].strftime('%B')} {watch['return'].day}']"
    pg.wait_for_selector(ret_sel, timeout=30000)
    labels = pg.eval_on_selector_all(ret_sel, "els => els.map(e => e.getAttribute('aria-label'))")
    parsed = [(i, LABEL.search(l)) for i, l in enumerate(labels)]
    parsed = [(i, m) for i, m in parsed if m]
    if not parsed:
        return None, [], ""
    # Cheapest return that respects the stop limit (round-trip totals are shown per return option).
    ok = [(i, m) for i, m in parsed if (0 if m["stops"] == "Nonstop" else int(m["stops"].split()[0])) <= watch["max_stops"]] or parsed
    i, m = min(ok, key=lambda x: float(x[1]["price"].replace(",", "")))
    back = _leg(m, watch["depart"])
    pg.locator(ret_sel).nth(i).evaluate("e => e.click()")
    pg.wait_for_selector("text=Booking options", timeout=40000)
    pg.wait_for_timeout(2500)
    texts = pg.eval_on_selector_all("[aria-label^='Continue to book with']", "els => els.map(e => e.getAttribute('aria-label'))")
    opts = []
    for label in texts:
        b = BOOK.search(label)
        if b:
            # Airlines selling directly show up either as "<X> airline" or with their fare brand
            # ("Turkish Airlines, Ecofly").
            direct = bool(b["airline"]) or any(b["who"].startswith(c) for c in offer.out.carriers)
            opts.append({"who": b["who"], "price": float(b["price"].replace(",", "")), "airline": direct})
    return back, opts, pg.url


def search(origin, watch, cfg):
    url = search_url(origin, watch)
    with page() as pg:
        try:
            _open_results(pg, url)
        except Exception:
            pass
        labels = pg.eval_on_selector_all(RESULT, "els => els.map(e => e.getAttribute('aria-label'))")
        indexed = parse(labels, origin, watch, url, with_index=True)
        offers = [o for _, o in indexed]
        if not offers and labels:
            raise RuntimeError(f"google: kunde inte tolka {len(labels)} resultat (format ändrat?)")
        # Booking options (airline direct vs. agencies) for the cheapest few within the stop limit.
        details = cfg["general"].get("google_booking_details", 2)
        picked = sorted([(i, o) for i, o in indexed if o.out.stops <= watch["max_stops"]],
                        key=lambda x: x[1].ticket_total)[:details]
        extra = []
        for i, o in picked:
            try:
                back, opts, burl = _booking(pg, url, i, o, watch)
            except Exception:
                continue
            if back:
                o.back = back
                o.conditions = t("src.google_return_picked")
            if burl:
                o.url = burl
            if opts:
                o.booking_options = opts
                cheapest = min(opts, key=lambda x: x["price"])
                o.ticket_total = cheapest["price"]
                o.booking_via = t("src.google_via", who=cheapest["who"])
                for a in sorted([x for x in opts if x["airline"]], key=lambda x: x["price"])[:1]:
                    extra.append(Offer(
                        source="airline", kind="flight", origin=origin, destination=o.destination,
                        depart_date=o.depart_date, return_date=o.return_date, ticket_total=a["price"],
                        out=o.out, back=o.back, url=burl, booking_via=t("src.google_airline", who=a["who"]),
                        booking_options=opts,
                        conditions=t("src.google_direct", levels=" · ".join(
                            f"{x['who'].split(', ')[-1]} {money(x['price'])}"
                            for x in sorted(opts, key=lambda x: x["price"]) if x["airline"]))))
    return offers + extra
