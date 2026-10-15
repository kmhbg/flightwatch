"""Configuration: ~/.config/flightwatch/config.toml (TOML, edited with tomlkit so comments survive)."""
import os
from datetime import date, timedelta
from pathlib import Path

import tomlkit

from . import system

CONFIG_DIR = system.config_dir()
CONFIG_PATH = Path(os.environ.get("FLIGHTWATCH_CONFIG", CONFIG_DIR / "config.toml"))
DATA_DIR = system.data_dir()
STATE_DIR = system.state_dir()
CACHE_DIR = system.cache_dir()
DB_PATH = DATA_DIR / "history.db"
STATUS_PATH = STATE_DIR / "status.json"
LOCK_PATH = STATE_DIR / "run.lock"

# Swedish (and nearby) departure airports. ving_id = Ving's internal departure id.
AIRPORTS = {
    "CPH": {"name": "Köpenhamn", "ving_id": 2583},
    "ARN": {"name": "Stockholm Arlanda", "ving_id": 2788},
    "GOT": {"name": "Göteborg Landvetter", "ving_id": 2770},
    "MMX": {"name": "Malmö Sturup", "ving_id": None},
    "BMA": {"name": "Stockholm Bromma", "ving_id": None},
    "NYO": {"name": "Stockholm Skavsta", "ving_id": 4041},
    "LLA": {"name": "Luleå", "ving_id": 2779},
    "UME": {"name": "Umeå", "ving_id": 2793},
    "VXO": {"name": "Växjö", "ving_id": 2795},
    "SDL": {"name": "Sundsvall", "ving_id": 2791},
    "BLL": {"name": "Billund", "ving_id": None},
}

GENERAL_DEFAULTS = {
    "language": "auto",          # auto | sv | en
    "currency": "SEK",
    "search_times": ["07:30", "19:30"],
    "notify": True,
    "notify_drop_pct": 3,
    "verify_top": 3,
    "default_origin": "CPH",
    "autostart": True,
}

# A new install starts without trips; they are added in the app (＋ New trip) or with `flightwatch new`.
DEFAULT_CONFIG = {
    "sv": """\
# Flightwatch – flygprisbevakning. Inställningarna under [general] ändras enklast i appen (⚙).
# Resor ([[watch]]) läggs till med ＋ Ny resa i appen eller `flightwatch new`.

[general]
language = "auto"           # auto (systemets språk) | sv | en
currency = "SEK"            # visningsvaluta; priserna hämtas i SEK och räknas om med ECB:s dagskurs
search_times = ["07:30", "19:30"]   # när appen söker (Windows/macOS; på Linux styr systemd-timern)
notify = true               # skrivbordsnotiser när priset blir bra eller sjunker
notify_drop_pct = 3         # notifiera när bästa flygpris sjunker minst så här många procent
verify_top = 3              # hur många av matrisens billigaste datumpar som verifieras med riktiga sökningar
default_origin = "CPH"      # avreseort för nya resor
autostart = true            # starta appen vid inloggning (Windows/macOS)

# Bagage som INTE ingår i biljetten prissätts med uppskattningar nedan (SEK per väska och riktning).
# Källor som själva redovisar bagaget (Kiwi, flygcity, Ving) går före. Kontrollera alltid hos flygbolaget.
[bags]
default_included_per_person = 1      # antagande för fullservicebolag när källan inte säger något (Google)
extra_bag_sek = 1000

[bags.carriers]
# IATA = { included = väskor/person i billigaste economy, extra_bag_sek = pris per väska och riktning }
# QR = { included = 1, extra_bag_sek = 1200 }
""",
    "en": """\
# Flightwatch – flight price watcher. The [general] settings are easiest to change in the app (⚙).
# Trips ([[watch]]) are added with ＋ New trip in the app or `flightwatch new`.

[general]
language = "auto"           # auto (system language) | sv | en
currency = "SEK"            # display currency; prices are fetched in SEK and converted at the ECB daily rate
search_times = ["07:30", "19:30"]   # when the app searches (Windows/macOS; on Linux the systemd timer decides)
notify = true               # desktop notifications when the price becomes good or drops
notify_drop_pct = 3         # notify when the best flight price drops at least this many percent
verify_top = 3              # how many of the matrix's cheapest date pairs are verified with real searches
default_origin = "CPH"      # departure airport for new trips
autostart = true            # start the app when you log in (Windows/macOS)

# Checked bags NOT included in the ticket are priced with the estimates below (SEK per bag and direction).
# Sources that state the baggage themselves (Kiwi, flygcity, Ving) take precedence. Always check with the airline.
[bags]
default_included_per_person = 1      # assumption for full-service airlines when the source says nothing (Google)
extra_bag_sek = 1000

[bags.carriers]
# IATA = { included = bags/person in the cheapest economy fare, extra_bag_sek = price per bag and direction }
# QR = { included = 1, extra_bag_sek = 1200 }
""",
}


def load_doc():
    if not CONFIG_PATH.exists():
        from .i18n import lang
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(DEFAULT_CONFIG.get(lang(), DEFAULT_CONFIG["en"]), encoding="utf-8")
    return tomlkit.parse(CONFIG_PATH.read_text(encoding="utf-8"))


def save_doc(doc):
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def load():
    """Plain-python view of the config. A watch needs destination + a date window; a reference
    trip (depart/return), thresholds and travel-agency ids are optional."""
    cfg = load_doc().unwrap()
    general = cfg.setdefault("general", {})
    for k, v in GENERAL_DEFAULTS.items():
        general.setdefault(k, v)
    cfg.setdefault("watch", [])
    for w in cfg["watch"]:
        for k in ("depart", "return", "earliest_depart", "latest_return"):
            if isinstance(w.get(k), str):
                w[k] = date.fromisoformat(w[k])
        if w.get("depart") and "flex_days" in w:
            # Planned trip ± flex_days on each date, at most shorten_days shorter (never longer
            # unless extend_days is set). The search window and trip lengths follow from that.
            flex, ref_days = int(w["flex_days"]), (w["return"] - w["depart"]).days
            w["earliest_depart"] = w["depart"] - timedelta(days=flex)
            w["latest_return"] = w["return"] + timedelta(days=flex)
            w["min_days"] = ref_days - int(w.get("shorten_days", flex))
            w["max_days"] = ref_days + int(w.get("extend_days", 0))
            w["depart_range"] = (w["depart"] - timedelta(days=flex), w["depart"] + timedelta(days=flex))
            w["return_range"] = (w["return"] - timedelta(days=flex), w["return"] + timedelta(days=flex))
        w.setdefault("earliest_depart", w.get("depart"))
        w.setdefault("latest_return", w.get("return"))
        w.setdefault("depart_range", (w["earliest_depart"], w["latest_return"] - timedelta(days=w.get("min_days", 1))))
        w.setdefault("return_range", (w["earliest_depart"] + timedelta(days=w.get("min_days", 1)), w["latest_return"]))
        if not w.get("depart"):  # no reference trip: use the start of the window for the per-night estimate
            w["depart"] = w["return"] = None
        span = (w["latest_return"] - w["earliest_depart"]).days
        w.setdefault("min_days", min(7, span))
        w.setdefault("max_days", span)
        w.setdefault("destinations", [w["destination"]])
        w.setdefault("destination_name", w["destination"])
        w.setdefault("adults", 2)
        w.setdefault("cabin", "ECONOMY")
        w.setdefault("checked_bags_per_person", 1)
        w.setdefault("active", True)
        w.setdefault("compare_origins", [])
        w.setdefault("stay", {})
        w.setdefault("max_stops", 1)
        w.setdefault("show_two_stops", True)
        w.setdefault("sources", ["kiwi", "flygcity", "momondo", "google", "ving", "apollo"])
        w.setdefault("charter", {})
        w.setdefault("thresholds", {})  # empty = automatic from the price spread (see runner)
    return cfg


def default_flex(trip_days, distance_km=None):
    """How flexible to be around a planned trip: long trips / long-haul flights ±2 days and up to
    2 days shorter; short trips with short flights ±1 day and up to 1 day shorter."""
    long_trip = trip_days >= 10 or (distance_km or 0) > 4000
    return (2, 2) if long_trip else (1, 1)


def find_watch(doc, watch_id):
    for w in doc["watch"]:
        if watch_id in (None, w["id"]):
            return w
    from .i18n import t
    raise SystemExit(t("cli.unknown_trip", id=watch_id))


def airport_name(code):
    return AIRPORTS.get(code, {}).get("name", code)
