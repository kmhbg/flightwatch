"""Turn a place to stay ("Sitges", "Bali") into airports to fly to and ids for the travel sites.

- Geocoding: OpenStreetMap Nominatim (one request per new trip, with a descriptive User-Agent).
- Airports: OurAirports open data, cached in ~/.cache/flightwatch/airports.csv; large/medium airports
  with scheduled service, nearest first.
- Ving: its own destination search (by the airport's city name).
"""
import csv
import math

import httpx

from . import system

CACHE = system.cache_dir()
AIRPORTS_CSV = CACHE / "airports.csv"
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
UA = "flightwatch/1.0 (personal flight price watcher)"


def geocode(place):
    r = httpx.get("https://nominatim.openstreetmap.org/search",
                  params={"q": place, "format": "json", "limit": 1, "accept-language": "sv,en"},
                  headers={"user-agent": UA}, timeout=30)
    r.raise_for_status()
    hits = r.json()
    if not hits:
        from .i18n import t
        raise SystemExit(t("cli.place_not_found", place=place))
    h = hits[0]
    return float(h["lat"]), float(h["lon"]), h["display_name"]


def _distance_km(a_lat, a_lon, b_lat, b_lon):
    p = math.radians
    h = (math.sin(p(b_lat - a_lat) / 2) ** 2
         + math.cos(p(a_lat)) * math.cos(p(b_lat)) * math.sin(p(b_lon - a_lon) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))


def _airports():
    if not AIRPORTS_CSV.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        r = httpx.get(AIRPORTS_URL, timeout=120, follow_redirects=True)
        r.raise_for_status()
        AIRPORTS_CSV.write_bytes(r.content)
    with open(AIRPORTS_CSV, newline="", encoding="utf-8") as f:
        return [a for a in csv.DictReader(f)
                if a["iata_code"] and a["scheduled_service"] == "yes" and a["type"] in ("large_airport", "medium_airport")]


def nearest_airports(lat, lon, max_km=130, limit=3):
    """Nearest airports with scheduled flights; always returns at least the closest one."""
    ranked = sorted(((round(_distance_km(lat, lon, a["lat"], a["lon"])), a) for a in _airport_index()),
                    key=lambda x: x[0])
    picked = [x for x in ranked if x[0] <= max_km][:limit] or ranked[:1]
    return [{"code": a["code"], "name": a["name"], "city": a["city"], "km": km} for km, a in picked]


def ving_destination(city, ving_departure_id=2583):
    """Ving's flight destination id for a city, or None if Ving doesn't fly there."""
    try:
        r = httpx.get(f"https://bookingstart-horizontal.ving.se/bs/api/fo/search/destinations/1/{ving_departure_id}/{city}",
                      timeout=30)
        hits = (r.json().get("result") or {}).get("areaResorts") or []
    except Exception:
        return None
    hit = next((h for h in hits if h.get("isIndependent")), None)
    return {"ving_country_id": hit["countryId"], "ving_destination_id": hit["itemId"]} if hit else None


def airbnb_location(place):
    """Airbnb search slug: 'Sitges, Spanien' -> 'Sitges--Spanien'."""
    parts = [p.strip().replace(" ", "-") for p in place.split(",") if p.strip()]
    return "--".join(parts)


# --- suggestions for the panel's From/To fields -----------------------------------------------

AIRPORTS_JSON = CACHE / "airports.json"
# Swedish exonyms that neither OurAirports nor Photon know.
SWEDISH_NAMES = {
    "köpenhamn": "CPH", "göteborg": "GOT", "stockholm": "ARN", "malmö": "MMX", "helsingfors": "HEL",
    "oslo": "OSL", "bryssel": "BRU", "aten": "ATH", "rom": "FCO", "lissabon": "LIS", "prag": "PRG",
    "wien": "VIE", "neapel": "NAP", "venedig": "VCE", "florens": "FLR", "milano": "MXP", "genève": "GVA",
    "zürich": "ZRH", "münchen": "MUC", "warszawa": "WAW", "kairo": "CAI", "peking": "PEK",
    "mallorca": "PMI", "teneriffa": "TFS", "gran canaria": "LPA", "kreta": "HER", "rhodos": "RHO",
    "cypern": "LCA", "bali": "DPS", "phuket": "HKT", "bangkok": "BKK", "nice": "NCE", "london": "LHR",
    "paris": "CDG", "new york": "JFK", "billund": "BLL",
}
NORDIC = {"SE", "DK", "NO", "FI"}
# Countries/regions people type as a destination ("Kap Verde") -> the airports travellers usually fly to.
# Swedish names first; English names come from OurAirports' countries.csv (any country, largest airports).
REGIONS = {
    "kap verde": ("Kap Verde", ["SID", "BVC", "RAI"]), "kanarieöarna": ("Kanarieöarna", ["LPA", "TFS", "ACE", "FUE", "SPC"]),
    "maldiverna": ("Maldiverna", ["MLE"]), "thailand": ("Thailand", ["BKK", "HKT", "KBV", "USM", "CNX"]),
    "spanien": ("Spanien", ["AGP", "ALC", "PMI", "BCN", "LPA", "TFS"]), "grekland": ("Grekland", ["ATH", "HER", "RHO", "CHQ", "KGS", "CFU"]),
    "italien": ("Italien", ["FCO", "NAP", "CTA", "PMO", "OLB", "MXP"]), "portugal": ("Portugal", ["LIS", "FAO", "FNC", "OPO"]),
    "turkiet": ("Turkiet", ["AYT", "DLM", "BJV", "IST"]), "cypern": ("Cypern", ["LCA", "PFO"]), "kroatien": ("Kroatien", ["SPU", "DBV", "ZAG"]),
    "egypten": ("Egypten", ["HRG", "SSH", "CAI"]), "marocko": ("Marocko", ["RAK", "AGA"]), "frankrike": ("Frankrike", ["NCE", "CDG"]),
    "förenade arabemiraten": ("Förenade Arabemiraten", ["DXB", "AUH"]), "dubai": ("Dubai", ["DXB"]),
    "mauritius": ("Mauritius", ["MRU"]), "seychellerna": ("Seychellerna", ["SEZ"]), "sri lanka": ("Sri Lanka", ["CMB"]),
    "indonesien": ("Indonesien", ["DPS", "CGK"]), "vietnam": ("Vietnam", ["SGN", "HAN", "DAD", "PQC"]),
    "filippinerna": ("Filippinerna", ["MNL", "CEB"]), "malaysia": ("Malaysia", ["KUL", "PEN", "LGK"]),
    "mexiko": ("Mexiko", ["CUN", "MEX"]), "karibien": ("Karibien", ["PUJ", "MBJ", "HAV", "BGI", "AUA"]),
    "dominikanska republiken": ("Dominikanska republiken", ["PUJ", "SDQ"]), "kuba": ("Kuba", ["HAV", "VRA"]),
    "jamaica": ("Jamaica", ["MBJ", "KIN"]), "usa": ("USA", ["JFK", "MIA", "LAX", "MCO"]), "florida": ("Florida", ["MIA", "MCO", "TPA"]),
    "sydafrika": ("Sydafrika", ["CPT", "JNB"]), "gambia": ("Gambia", ["BJL"]), "zanzibar": ("Zanzibar", ["ZNZ"]),
    "tanzania": ("Tanzania", ["ZNZ", "JRO", "DAR"]), "kenya": ("Kenya", ["MBA", "NBO"]), "madeira": ("Madeira", ["FNC"]),
    "azorerna": ("Azorerna", ["PDL"]), "sicilien": ("Sicilien", ["CTA", "PMO"]), "sardinien": ("Sardinien", ["OLB", "CAG"]),
    "korsika": ("Korsika", ["AJA", "BIA"]), "balearerna": ("Balearerna", ["PMI", "IBZ", "MAH"]), "malta": ("Malta", ["MLA"]),
    "island": ("Island", ["KEF"]), "japan": ("Japan", ["NRT", "HND", "KIX"]), "australien": ("Australien", ["SYD", "MEL"]),
}
REGION_ALIASES = {
    "cape verde": "kap verde", "cabo verde": "kap verde", "canary islands": "kanarieöarna", "kanarieoarna": "kanarieöarna",
    "maldives": "maldiverna", "spain": "spanien", "greece": "grekland", "italy": "italien", "turkey": "turkiet",
    "türkiye": "turkiet", "cyprus": "cypern", "croatia": "kroatien", "egypt": "egypten", "morocco": "marocko",
    "france": "frankrike", "uae": "förenade arabemiraten", "emiraten": "förenade arabemiraten", "seychelles": "seychellerna",
    "indonesia": "indonesien", "philippines": "filippinerna", "mexico": "mexiko", "caribbean": "karibien",
    "dominican republic": "dominikanska republiken", "cuba": "kuba", "south africa": "sydafrika", "azores": "azorerna",
    "sicily": "sicilien", "sardinia": "sardinien", "corsica": "korsika", "balearic islands": "balearerna",
    "iceland": "island", "australia": "australien",
}
# Better names than OurAirports' municipality for the region airports (also where lodging is searched).
AIRPORT_NAMES = {
    "SID": "Sal", "BVC": "Boa Vista", "RAI": "Praia", "LPA": "Gran Canaria", "TFS": "Teneriffa", "ACE": "Lanzarote",
    "FUE": "Fuerteventura", "SPC": "La Palma", "USM": "Koh Samui", "HKT": "Phuket", "KBV": "Krabi", "AGP": "Málaga",
    "PMI": "Mallorca", "IBZ": "Ibiza", "MAH": "Menorca", "HER": "Kreta (Heraklion)", "CHQ": "Kreta (Chania)",
    "RHO": "Rhodos", "KGS": "Kos", "CFU": "Korfu", "CTA": "Catania", "OLB": "Olbia", "FAO": "Algarve (Faro)",
    "FNC": "Madeira", "AYT": "Antalya", "DLM": "Dalaman", "BJV": "Bodrum", "HRG": "Hurghada", "SSH": "Sharm el-Sheikh",
    "RAK": "Marrakech", "AGA": "Agadir", "PUJ": "Punta Cana", "MBJ": "Montego Bay", "VRA": "Varadero", "CUN": "Cancún",
    "BJL": "Gambia (Banjul)", "ZNZ": "Zanzibar", "MBA": "Mombasa", "PQC": "Phu Quoc", "DAD": "Da Nang", "DPS": "Bali",
    "LGK": "Langkawi", "PEN": "Penang", "MRU": "Mauritius", "SEZ": "Mahé", "CMB": "Colombo", "PDL": "Ponta Delgada",
    "ATH": "Aten", "FCO": "Rom", "NAP": "Neapel", "PMO": "Palermo", "MXP": "Milano", "CAG": "Cagliari", "AJA": "Ajaccio",
    "BIA": "Bastia", "BCN": "Barcelona", "ALC": "Alicante", "LIS": "Lissabon", "OPO": "Porto", "ZAG": "Zagreb",
    "CDG": "Paris", "IST": "Istanbul", "CAI": "Kairo", "DXB": "Dubai", "AUH": "Abu Dhabi", "CGK": "Jakarta",
    "SGN": "Ho Chi Minh-staden", "HAN": "Hanoi", "MNL": "Manila", "CEB": "Cebu", "KUL": "Kuala Lumpur", "HAV": "Havanna",
    "SDQ": "Santo Domingo", "KIN": "Kingston", "BGI": "Barbados", "AUA": "Aruba", "JRO": "Kilimanjaro",
    "DAR": "Dar es Salaam", "NBO": "Nairobi", "JNB": "Johannesburg", "CPT": "Kapstaden", "KEF": "Reykjavik",
    "NRT": "Tokyo (Narita)", "HND": "Tokyo (Haneda)", "KIX": "Osaka", "SYD": "Sydney", "MEL": "Melbourne",
    "JFK": "New York", "MIA": "Miami", "LAX": "Los Angeles", "MCO": "Orlando", "TPA": "Tampa", "BKK": "Bangkok",
    "CNX": "Chiang Mai", "MEX": "Mexico City",
    "MLE": "Malé", "LCA": "Larnaca", "PFO": "Paphos", "SPU": "Split", "DBV": "Dubrovnik", "NCE": "Nice", "MLA": "Malta",
}
# English UI: region and airport names where English differs from the Swedish above.
REGION_NAMES_EN = {
    "kap verde": "Cape Verde", "kanarieöarna": "Canary Islands", "maldiverna": "Maldives", "spanien": "Spain",
    "grekland": "Greece", "italien": "Italy", "turkiet": "Turkey", "cypern": "Cyprus", "kroatien": "Croatia",
    "egypten": "Egypt", "marocko": "Morocco", "frankrike": "France", "förenade arabemiraten": "United Arab Emirates",
    "seychellerna": "Seychelles", "indonesien": "Indonesia", "filippinerna": "Philippines", "mexiko": "Mexico",
    "karibien": "Caribbean", "dominikanska republiken": "Dominican Republic", "kuba": "Cuba", "sydafrika": "South Africa",
    "azorerna": "Azores", "sicilien": "Sicily", "sardinien": "Sardinia", "korsika": "Corsica",
    "balearerna": "Balearic Islands", "island": "Iceland", "australien": "Australia",
}
AIRPORT_NAMES_EN = {
    "TFS": "Tenerife", "HER": "Crete (Heraklion)", "CHQ": "Crete (Chania)", "RHO": "Rhodes", "CFU": "Corfu",
    "ATH": "Athens", "FCO": "Rome", "NAP": "Naples", "MXP": "Milan", "LIS": "Lisbon", "CAI": "Cairo",
    "SGN": "Ho Chi Minh City", "HAV": "Havana", "CPT": "Cape Town", "BJL": "Gambia (Banjul)",
}
COUNTRIES_CSV = CACHE / "countries.csv"
COUNTRIES_URL = "https://davidmegginson.github.io/ourairports-data/countries.csv"
PLACE_TYPES = {"city", "town", "village", "suburb", "region", "island", "county", "municipality", "hamlet",
               "neighbourhood", "quarter", "state"}


def _fold(t):
    import unicodedata
    return unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()


def _airport_index():
    """Compact airport list (scheduled service only), cached as JSON for fast keystroke lookups."""
    if AIRPORTS_JSON.exists():
        import json
        return json.loads(AIRPORTS_JSON.read_text())
    rows = [{"code": a["iata_code"], "name": a["name"], "city": a["municipality"], "country": a["iso_country"],
             "lat": float(a["latitude_deg"]), "lon": float(a["longitude_deg"]), "large": a["type"] == "large_airport"}
            for a in _airports()]
    import json
    AIRPORTS_JSON.write_text(json.dumps(rows, ensure_ascii=False))
    return rows


def _airport_hits(text, nordic_first):
    q = _fold(text.strip())
    if not q:
        return []
    idx = _airport_index()
    alias = SWEDISH_NAMES.get(text.strip().lower())
    hits = []
    for a in idx:
        code, name, city = a["code"].lower(), _fold(a["name"]), _fold(a["city"])
        if alias and a["code"] == alias:
            score = 0
        elif q == code:
            score = 1
        elif city.startswith(q) or name.startswith(q):
            score = 2
        elif len(q) >= 3 and (q in city or q in name):
            score = 3
        else:
            continue
        rank = (score, 0 if (nordic_first and a["country"] in NORDIC) else 1, 0 if a["large"] else 1)
        hits.append((rank, a))
    hits.sort(key=lambda x: x[0])
    return [{"kind": "airport", "code": a["code"], "label": f"{a['code']} – {a['city'] or a['name']}",
             "detail": a["name"], "country": a["country"]} for _, a in hits[:6]]


def _countries():
    if not COUNTRIES_CSV.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        r = httpx.get(COUNTRIES_URL, timeout=60, follow_redirects=True)
        r.raise_for_status()
        COUNTRIES_CSV.write_bytes(r.content)
    with open(COUNTRIES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _region_hits(text):
    """A country or region typed as destination -> one suggestion per main airport there (lodging near it)."""
    q = _fold(text.strip())
    if len(q) < 3:
        return []
    idx = {a["code"]: a for a in _airport_index()}
    from .i18n import lang
    en = lang() != "sv"
    keys = [k for k in REGIONS if _fold(k).startswith(q)]
    keys += [v for k, v in REGION_ALIASES.items() if _fold(k).startswith(q) and v not in keys]
    found = [((REGION_NAMES_EN.get(k) if en else None) or REGIONS[k][0], REGIONS[k][1]) for k in keys][:2]
    if not found:
        try:
            countries = _countries()
        except Exception:
            countries = []
        for c in countries:
            if _fold(c["name"]).startswith(q) or any(_fold(k.strip()) == q for k in c["keywords"].split(",") if k.strip()):
                aps = sorted((a for a in idx.values() if a["country"] == c["code"] and a["city"]),
                             key=lambda a: not a["large"])
                found.append((c["name"], [a["code"] for a in aps[:4]]))
            if len(found) == 2:
                break
    out = []
    for name, codes in found:
        for code in codes:
            a = idx.get(code)
            if not a:
                continue
            city = (AIRPORT_NAMES_EN.get(code) if en else None) or AIRPORT_NAMES.get(code) or a["city"] or a["name"]
            out.append({"kind": "place", "code": code, "place": f"{city}, {name}", "label": f"{name}: {city} ({code})",
                        "detail": a["name"], "lat": round(a["lat"], 5), "lon": round(a["lon"], 5)})
    return out[:6]


def _place_hits(text):
    try:
        r = httpx.get("https://photon.komoot.io/api/", params={"q": text, "limit": 6},
                      headers={"user-agent": UA}, timeout=15)
        feats = r.json().get("features") or []
    except Exception:
        return []
    out, seen = [], set()
    for f in feats:
        p = f["properties"]
        if p.get("osm_value") not in PLACE_TYPES or not p.get("name"):
            continue
        lon, lat = f["geometry"]["coordinates"]
        near = nearest_airports(lat, lon, limit=1)[0]
        key = (p["name"], p.get("country"))
        if key in seen:
            continue
        seen.add(key)
        where = ", ".join(x for x in (p.get("state"), p.get("country")) if x)
        out.append({"kind": "place", "code": near["code"], "place": f"{p['name']}, {p.get('country', '')}".strip(", "),
                    "label": f"{p['name']} ({where})", "detail": f"flyg till {near['code']} {near['city']}, {near['km']} km",
                    "lat": round(lat, 5), "lon": round(lon, 5)})
    return out[:4]


def suggest(text, kind="to"):
    """Suggestions while typing. kind='from': airports (Nordic first). kind='to': airports + places;
    a place without an airport carries its nearest airport, lodging is searched in the place."""
    text = (text or "").strip()
    if len(text) < 2:
        return []
    air = _airport_hits(text, nordic_first=(kind == "from"))
    if kind == "from" or len(text) < 3:
        return air
    # A country/region match is what was meant; skip the (sometimes slow) place search then.
    regions = _region_hits(text)
    places = regions or _place_hits(text)
    # An exact airport code first, then places (towns are what people usually mean), then other airports.
    exact = [a for a in air if a["code"].lower() == text.lower() or SWEDISH_NAMES.get(text.lower()) == a["code"]]
    rest = [a for a in air if a not in exact]
    return (exact + places + rest)[:8]
