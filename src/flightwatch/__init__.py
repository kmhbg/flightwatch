"""flightwatch – flight price watcher: bar widget on Omarchy, tray app on Windows/macOS."""
import argparse
import json
import sys

from . import config, i18n, system
from .i18n import money as _fmt
from .i18n import t


def _print_combo(v):
    if not v:
        return
    label = t("combo." + v["label"]) if "combo." + v["label"] in i18n.catalog() else v["label"]  # best2 … are internal
    print("\n" + t("cli.combo", label=label, dep=v["depart"], ret=v["return"],
                   days=t("unit.day", n=v["days"])))
    b = v["best"]
    if b:
        print(t("cli.best_flight", stops=b["max_stops"], total=_fmt(b["total"]), pp=_fmt(b["per_person"]),
                airlines="/".join(b["airlines"]), source=b["source"]))
        print(t("cli.ticket_bags", ticket=_fmt(b["ticket_total"]), bags=_fmt(b["bag_cost"]),
                est=t("cli.est") if b["bag_cost_estimated"] else "", note=b["bag_note"]))
        print(f"    {b['url']}")
    c = v.get("cheaper_two_stops")
    if c:
        print(t("cli.two_stops", total=_fmt(c["total"]), airlines="/".join(c["airlines"]), source=c["source"],
                cond=c["conditions"]))
    s = v["stay"]
    print(t("cli.stay", source=s["source"], nights=t("unit.night", n=s["nights"]), guests=t("unit.guest", n=s["guests"]),
            total=_fmt(s["total"]), name=s.get("name", ""))
          + (f" ★{s['rating']} · {s['beds']}" if s.get("rating") else ""))
    print(t("cli.flight_stay", total=_fmt(v["flight_plus_stay"])))
    p = v.get("best_package")
    if p:
        diff = v.get("package_minus_own")
        print(t("cli.package", total=_fmt(p["total"]), source=p["source"], hotel=p["hotel"])
              + (t("cli.own_cheaper" if diff > 0 else "cli.own_dearer", diff=_fmt(abs(diff))) if diff is not None else ""))


def cmd_status(args):
    from .runner import read_status
    st = read_status()
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return 0
    print(t("cli.updated", when=st.get("updated") or t("cli.never")) + (t("cli.running") if st.get("running") else ""))
    for w in st.get("watches", []):
        h = w.get("headline")
        print("\n" + t("cli.from", name=w["name"], origin=w.get("preferred_origin")))
        if h:
            print(t("cli.headline", dep=h["depart"], ret=h["return"], price=_fmt(h["total"]),
                    label=t("cat." + h["category"]), with_stay=_fmt(h["with_stay"])))
        if w.get("alert"):
            print(f"🔔 {w['alert']['text']}")
        for key in ("overall", "reference", "same_depart"):
            _print_combo(w.get(key))
        print("\n" + t("cli.other_airports"))
        for o in w.get("origins", []):
            ref, best = o.get("reference"), o.get("best")
            print(t("cli.airport_row", code=o["code"], name=o["name"], ref=_fmt(ref and ref["total"]),
                    best=_fmt(best and best["total"])))
        print("\n" + t("cli.alternatives"))
        for a in w.get("alternatives", [])[:8]:
            print(f"  {a['depart']} → {a['return']} ({a['days']} d): ✈ ≈{_fmt(a['flight_est'])} + 🏠 ≈{_fmt(a['stay_est'])}"
                  f" = ≈{_fmt(a['total_est'])}" + (f"  ✓ {_fmt(a['verified_total'])}" if a.get("verified_total") else ""))
        for e in w.get("errors", []):
            print(f"  ⚠ {e}")
    return 0


def cmd_origin(args):
    doc = config.load_doc()
    w = config.find_watch(doc, args.watch)
    code = args.code.upper()
    cmp_ = list(w.get("compare_origins", []))
    if args.action == "set":
        old = str(w["preferred_origin"])
        w["preferred_origin"] = code
        cmp_ = [c for c in cmp_ if c != code]
        if old != code and old not in cmp_:
            cmp_.insert(0, old)
    elif args.action == "toggle" and code != str(w["preferred_origin"]):
        cmp_ = [c for c in cmp_ if c != code] if code in cmp_ else cmp_ + [code]
    cmp_ = [c for c in cmp_ if c != str(w["preferred_origin"])]
    w["compare_origins"] = cmp_
    config.save_doc(doc)
    print(t("cli.origin_set", origin=w["preferred_origin"], compare=", ".join(cmp_) or "—"))
    return 0


def _slug(text):
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "resa"


def cmd_new(args):
    """Create a trip from a place to stay: airports and site ids are looked up automatically."""
    import tomlkit
    from datetime import date
    from . import places
    if args.lat is not None and args.lon is not None:
        lat, lon, display = args.lat, args.lon, args.to
    else:
        lat, lon, display = places.geocode(args.to)
    airports = places.nearest_airports(lat, lon)
    if args.airport:
        airports = [a for a in airports if a["code"] == args.airport.upper()] or [{"code": args.airport.upper(), "name": args.airport.upper(), "city": "", "km": None}]
    primary = airports[0]
    doc = config.load_doc()
    origin = (args.origin or str(doc.get("general", {}).get("default_origin", "CPH"))).upper()
    ids = {str(w["id"]) for w in doc.get("watch", [])}
    wid, n = _slug(args.name or args.to.split(",")[0]), 2
    while wid in ids:
        wid, n = f"{_slug(args.name or args.to.split(',')[0])}-{n}", n + 1
    w = tomlkit.table()
    w["id"] = wid
    w["name"] = args.name or args.to.split(",")[0].strip()
    w["active"] = True
    w["destination"] = primary["code"]
    w["destinations"] = [a["code"] for a in airports]
    w["destinations"].comment(t("cfg.destinations"))
    w["destination_name"] = f"{args.to.split(',')[0].strip()} via {primary['code']}"
    w["adults"] = args.adults
    w["checked_bags_per_person"] = args.bags
    w["max_stops"] = 1
    w["show_two_stops"] = True
    w["preferred_origin"] = origin
    w["compare_origins"] = [c for c in ("CPH", "ARN", "GOT") if c != origin][:2]
    w["sources"] = ["kiwi", "flygcity", "momondo", "google", "ving", "sembo", "sunweb"]
    dep, ret = date.fromisoformat(args.depart), date.fromisoformat(args.ret)
    w["depart"], w["return"] = dep, ret
    flex, shorten = _flex_for(origin, primary["code"], dep, ret, args.flex)
    w["flex_days"] = tomlkit.item(flex).comment(t("cfg.flex_days"))
    w["shorten_days"] = tomlkit.item(shorten).comment(t("cfg.shorten_days"))
    w["thresholds"] = tomlkit.table()  # empty = automatic from the price spread
    stay = tomlkit.table()
    stay["place"] = args.to
    stay["lat"], stay["lon"] = round(lat, 5), round(lon, 5)
    # A country/region pick ("Kap Verde: Sal") centres on the airport itself; resorts are further out.
    max_km = args.max_km if args.max_km is not None else (40 if primary.get("km") == 0 else 8)
    stay["max_km"] = tomlkit.item(max_km).comment(t("cfg.max_km"))
    stay["airbnb_location"] = places.airbnb_location(args.to)
    stay["guests"] = args.guests or args.adults
    stay["guest_favorite"] = True
    stay["min_rating"] = 4.8
    stay["min_reviews"] = 10
    stay["require"] = [r for r in args.require.split(",") if r] if args.require is not None else ["ac"]
    stay["entire_home"] = True
    stay["min_bedrooms"] = max(1, (args.guests or args.adults) // 2)
    stay["pages"] = 3
    stay["fallback_per_week_sek"] = args.fallback_week
    stay["hotel_sources"] = tomlkit.item(["booking", "hotels.com", "sembo"]).comment(t("cfg.hotel_sources"))
    stay["hotel_min_rating"] = tomlkit.item(8.5).comment(t("cfg.hotel_rating"))
    stay["hotel_min_reviews"] = 20
    w["stay"] = stay
    charter = places.ving_destination(args.to.split(",")[0].strip()) or places.ving_destination(primary["city"]) or {}
    w["charter"] = tomlkit.table()
    for k, v in charter.items():
        w["charter"][k] = v
    info = tomlkit.array()
    for a in airports:
        row = tomlkit.inline_table()
        row.update({"code": a["code"], "name": a["name"], "km": a["km"] or 0})
        info.append(row)
    w["destination_info"] = info
    if "watch" not in doc:
        doc["watch"] = tomlkit.aot()
    doc["watch"].append(w)
    if args.select:
        doc["general"]["selected"] = wid
    config.save_doc(doc)
    # Show the trip in the app/bar right away ("söker …") instead of only after its first search finishes.
    from .runner import read_status, watch_meta, write_status
    new = next(x for x in config.load()["watch"] if x["id"] == wid)
    st = read_status()
    st["watches"] = [x for x in st.get("watches", []) if x["id"] != wid] + [{**watch_meta(new), "by_origin": {}, "origins": [],
                                                                               "trend": [], "alert": None, "errors": []}]
    if args.select:
        st["selected"] = wid
    write_status(st)
    print(json.dumps({"id": wid, "place": display, "airports": airports, "ving": bool(charter)}, ensure_ascii=False))
    return 0


def _flex_for(origin, destination, dep, ret, flex):
    """(flex_days, shorten_days): explicit ± days, or the default from trip length and flight distance."""
    from . import places
    if flex is not None:
        return flex, flex
    idx = {a["code"]: a for a in places._airport_index()}
    o, d = idx.get(origin), idx.get(destination)
    km = places._distance_km(o["lat"], o["lon"], d["lat"], d["lon"]) if o and d else None
    return config.default_flex((ret - dep).days, km)


def cmd_dates(args):
    """Move a trip to new planned dates (keeps everything else) so several trips can be planned."""
    import tomlkit
    from datetime import date
    dep, ret = date.fromisoformat(args.depart), date.fromisoformat(args.ret)
    if ret <= dep:
        raise SystemExit(t("cli.return_after"))
    if dep <= date.today():
        raise SystemExit(t("cli.depart_future"))
    doc = config.load_doc()
    w = config.find_watch(doc, args.id)
    flex, shorten = _flex_for(str(w.get("preferred_origin", "CPH")), str(w["destination"]), dep, ret, args.flex)
    w["depart"], w["return"] = dep, ret
    for k in ("earliest_depart", "latest_return"):  # old explicit windows would override the new dates
        if k in w:
            del w[k]
    w["flex_days"] = tomlkit.item(flex).comment(t("cfg.flex_days"))
    w["shorten_days"] = tomlkit.item(shorten).comment(t("cfg.shorten_days"))
    config.save_doc(doc)
    print(json.dumps({"id": args.id, "depart": dep.isoformat(), "return": ret.isoformat(), "flex_days": flex,
                      "shorten_days": shorten}))
    return 0


def cmd_select(args):
    doc = config.load_doc()
    config.find_watch(doc, args.id)
    doc["general"]["selected"] = args.id
    config.save_doc(doc)
    from .runner import read_status, write_status
    st = read_status()
    st["selected"] = args.id
    write_status(st)
    return 0


def cmd_remove(args):
    doc = config.load_doc()
    keep = [w for w in doc["watch"] if w["id"] != args.id]
    if len(keep) == len(doc["watch"]):
        raise SystemExit(t("cli.unknown_trip", id=args.id))
    import tomlkit
    aot = tomlkit.aot()
    for w in keep:
        aot.append(w)
    doc["watch"] = aot
    if doc["general"].get("selected") == args.id:
        doc["general"]["selected"] = keep[0]["id"] if keep else ""
    config.save_doc(doc)
    from .runner import read_status, write_status
    st = read_status()
    st["watches"] = [w for w in st.get("watches", []) if w["id"] != args.id]
    st["selected"] = doc["general"].get("selected")
    write_status(st)
    return 0


def cmd_trips(args):
    cfg = config.load()
    sel = cfg["general"].get("selected") or (cfg["watch"][0]["id"] if cfg["watch"] else "")
    print(json.dumps([{"id": w["id"], "name": w["name"], "destination": w["destination"],
                       "selected": w["id"] == sel} for w in cfg["watch"]], ensure_ascii=False))
    return 0


def cmd_ack(args):
    from .runner import read_status, write_status
    st = read_status()
    for w in st.get("watches", []):
        if w.get("alert"):
            w["alert"]["unread"] = False
    write_status(st)
    return 0


def cmd_history(args):
    from . import store
    db = store.connect()
    watches = config.load()["watch"]
    if not watches:
        return 0
    for ts, total in store.best_history(db, args.watch or watches[0]["id"], 200):
        print(ts, _fmt(total))
    return 0


def cmd_doctor(args):
    """Check the things that differ per computer: folders, language, currency, the browser for page sources."""
    from . import fx, i18n
    print(f"flightwatch {__import__('flightwatch.update', fromlist=['current']).current()} · {sys.platform}"
          f"{' (frozen)' if system.FROZEN else ''}")
    print(f"config  {config.CONFIG_PATH}\nstate   {config.STATE_DIR}\ndata    {config.DATA_DIR}\ncache   {config.CACHE_DIR}")
    print(f"command {' '.join(system.self_cmd())}")
    print(f"language {i18n.lang()} (system: {i18n.system_language()}) · currency {fx.current()}")
    print(f"systemd {system.has_systemd()}")
    try:
        launch = system.browser_launch_args()
        from .sources.browser import page
        with page() as pg:
            pg.set_content("<title>ok</title>")
            print(f"browser OK {launch or '(downloaded Chromium)'} · {pg.title()}")
    except Exception as e:
        print(f"browser FAILED: {e}")
        return 1
    return 0


def _log_to_file_without_console():
    """A windowed build (no console) has no stdout/stderr; keep messages in a log file instead."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log = config.STATE_DIR / "flightwatch.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists() and log.stat().st_size > 2_000_000:
        log.replace(log.with_suffix(".log.old"))
    f = open(log, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or f
    sys.stderr = sys.stderr or f


def main():
    _log_to_file_without_console()
    ap = argparse.ArgumentParser(prog="flightwatch", description=t("cli.description"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help=t("cli.h.run"))
    r.add_argument("--watch")
    r.add_argument("--quick", action="store_true", help=t("cli.h.quick"))
    r.add_argument("--origin", help=t("cli.h.origin"))
    sg = sub.add_parser("suggest", help=t("cli.h.suggest"))
    sg.add_argument("text")
    sg.add_argument("--kind", choices=["from", "to"], default="to")
    s = sub.add_parser("status", help=t("cli.h.status"))
    s.add_argument("--json", action="store_true")
    o = sub.add_parser("origin", help=t("cli.h.origin_cmd"))
    o.add_argument("action", choices=["set", "toggle"])
    o.add_argument("code")
    o.add_argument("--watch")
    sub.add_parser("ack", help=t("cli.h.ack"))
    h = sub.add_parser("history", help=t("cli.h.history"))
    h.add_argument("--watch")
    sub.add_parser("config", help=t("cli.h.config"))
    sub.add_parser("airports", help=t("cli.h.airports"))
    n = sub.add_parser("new", help=t("cli.h.new"))
    n.add_argument("--to", required=True, help=t("cli.h.to"))
    n.add_argument("--name")
    n.add_argument("--from", dest="origin", default=None)
    n.add_argument("--depart", required=True, help=t("cli.h.depart"))
    n.add_argument("--return", dest="ret", required=True, help=t("cli.h.return"))
    n.add_argument("--flex", type=int, help=t("cli.h.flex"))
    n.add_argument("--adults", type=int, default=2)
    n.add_argument("--guests", type=int, help=t("cli.h.guests"))
    n.add_argument("--bags", type=int, default=1)
    n.add_argument("--airport", help=t("cli.h.airport"))
    n.add_argument("--require", help=t("cli.h.require"))
    n.add_argument("--lat", type=float, help=t("cli.h.lat"))
    n.add_argument("--lon", type=float)
    n.add_argument("--select", action="store_true", help=t("cli.h.select"))
    n.add_argument("--max-km", type=float, default=None, help=t("cli.h.max_km"))
    n.add_argument("--fallback-week", type=int, default=3000, help=t("cli.h.fallback_week"))
    dt = sub.add_parser("dates", help=t("cli.h.dates"))
    dt.add_argument("id")
    dt.add_argument("--depart", required=True, help=t("cli.h.date"))
    dt.add_argument("--return", dest="ret", required=True, help=t("cli.h.date"))
    dt.add_argument("--flex", type=int, help=t("cli.h.flex_auto"))
    sel = sub.add_parser("select", help=t("cli.h.select_cmd"))
    sel.add_argument("id")
    rm = sub.add_parser("remove", help=t("cli.h.remove"))
    rm.add_argument("id")
    sub.add_parser("trips", help=t("cli.h.trips"))
    sub.add_parser("doctor", help="check folders, language, currency and the browser")
    sv = sub.add_parser("serve", help=t("cli.h.serve"))
    sv.add_argument("--port", type=int, default=8765)
    ap_app = sub.add_parser("app", help=t("cli.h.app"))
    ap_app.add_argument("--background", action="store_true", help=argparse.SUPPRESS)  # login start: tray only
    ap_app.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)  # no tray/window (tests)
    argv = sys.argv[1:]
    if system.FROZEN and not argv:  # double-clicked Flightwatch.exe / Flightwatch.app
        argv = ["app"]
    a = ap.parse_args(argv)

    if a.cmd == "run":
        from .runner import run
        return run(a.watch, a.quick, a.origin.upper() if a.origin else None)
    if a.cmd == "app":
        from .app import main as app_main
        return app_main(a.background, a.headless)
    if a.cmd == "serve":
        from .web import serve
        serve(a.port)
        return 0
    if a.cmd == "suggest":
        from . import places
        print(json.dumps(places.suggest(a.text, a.kind), ensure_ascii=False))
        return 0
    if a.cmd == "status":
        return cmd_status(a)
    if a.cmd == "origin":
        return cmd_origin(a)
    if a.cmd == "ack":
        return cmd_ack(a)
    if a.cmd in ("new", "select", "remove", "trips", "dates"):
        return {"new": cmd_new, "select": cmd_select, "remove": cmd_remove, "trips": cmd_trips, "dates": cmd_dates}[a.cmd](a)
    if a.cmd == "doctor":
        return cmd_doctor(a)
    if a.cmd == "history":
        return cmd_history(a)
    if a.cmd == "airports":
        print(json.dumps([{"code": k, "name": v["name"]} for k, v in config.AIRPORTS.items()], ensure_ascii=False))
        return 0
    if a.cmd == "config":
        config.load_doc()
        print(config.CONFIG_PATH)
        return 0


if __name__ == "__main__":
    sys.exit(main())
