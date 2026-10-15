"""One monitoring run: find the cheapest date combination (flight + lodging) inside the
flexible window, verify it with real searches, compare packages and other airports, store history,
write status.json for the bar widget and send alerts."""
import json
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from filelock import FileLock, Timeout

from . import config, notify, pricing, store
from .i18n import money, t
from .sources import airbnb, apollo, flygcity, google, hotels, kiwi, momondo, qatar, sembo, sunweb, ving

# Slow sources (≈40 s per date pair, headless browser with clicks) only run for the preferred airport.
SLOW_SOURCES = {"google", "apollo"}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


def _with_dates(watch, dep, ret):
    return {**watch, "depart": dep, "return": ret}


# --- lodging -------------------------------------------------------------------------------

_STAYS = {}  # (watch, checkin, checkout) -> stay; the same dates come up for every departure airport


def _sembo_polygon(st):
    """Sembo's place id for the stay, looked up once per run."""
    if "sembo_polygon" not in st:
        try:
            hit = hotels.sembo_polygon(hotels.location(st).split(",")[0])
            st["sembo_polygon"] = hit["polygonId"] if hit else None
        except Exception:
            st["sembo_polygon"] = None
    return st["sembo_polygon"]


def stay_cost(watch, checkin: date, checkout: date):
    """Cheapest lodging for all guests that meets the quality bar: Airbnb (Gästfavorit, pool, AC …)
    and hotels from Booking.com, Hotels.com and Sembo (rating, pool, AC, rooms for everyone).
    Falls back to a per-week estimate when nothing answers."""
    key = (watch["id"], checkin, checkout)
    if key in _STAYS:
        return _STAYS[key]
    if "sembo" in watch["stay"].get("hotel_sources", ["sembo"]):
        _sembo_polygon(watch["stay"])
    st = watch["stay"]
    guests = st.get("guests", watch["adults"])
    nights = max(1, (checkout - checkin).days)
    base = {"checkin": checkin.isoformat(), "checkout": checkout.isoformat(), "nights": nights, "guests": guests,
            "search_url": airbnb.search_url(st, checkin, checkout, guests) if st.get("airbnb_location") else ""}
    cands, errors, by_source = [], {}, {}
    if st.get("airbnb_location"):
        try:
            listings = airbnb.search(st, checkin, checkout, guests)
            cands += [{**l, "source": "airbnb", "kind": "Airbnb"} for l in listings]
            if not listings:
                errors["airbnb"] = t("stay.no_match")
        except Exception as e:
            errors["airbnb"] = str(e)[:120]
    hotel_sources = st.get("hotel_sources", ["booking", "hotels.com", "sembo"])
    if hotel_sources and hotels.location(st):
        found, herr, n = hotels.search(st, checkin, checkout, guests, hotel_sources)
        errors.update(herr)
        cands += [{**h, "kind": t("stay.hotel"), "beds": t("unit.room", n=h["rooms"])} for h in found]
        for name in hotel_sources:
            if name not in herr and not any(h["source"] == name for h in found):
                errors.setdefault(name, t("stay.no_hotel", n=n) if n else t("stay.no_hits"))
    cands.sort(key=lambda c: c["total"])
    for c in cands:
        by_source.setdefault(c["source"], {k: c.get(k) for k in ("total", "name", "rating", "url")})
    if cands:
        top = cands[0]
        stay = {**base, "source": top["source"], "kind": top["kind"], "total": top["total"], "name": top["name"],
                "rating": top["rating"], "reviews": top.get("reviews", 0), "beds": top.get("beds", ""),
                "url": top["url"], "matches": len(cands), "by_source": by_source, "errors": errors,
                "alternatives": [{k: c.get(k) for k in ("total", "name", "rating", "beds", "url", "source", "kind")}
                                 for c in cands[1:6]]}
    else:
        week = st.get("fallback_per_week_sek", 3000)
        stay = {**base, "source": "fallback", "total": round(week * nights / 7), "name": t("stay.fallback", price=money(week)),
                "note": "; ".join(f"{k}: {v}" for k, v in errors.items()), "url": base["search_url"], "errors": errors}
    _STAYS[key] = stay
    return stay


# --- flights per date combination ------------------------------------------------------------

def gather(origin, watch, cfg, sources, errors, pool):
    """Run the configured sources for one origin + date pair; returns completed offers."""
    bags = watch["checked_bags_per_person"]
    jobs = {}
    if "kiwi" in sources:
        jobs["kiwi"] = pool.submit(kiwi.search, origin, watch, cfg, bags, watch["max_stops"])
        if watch.get("show_two_stops"):
            jobs["kiwi2"] = pool.submit(kiwi.search, origin, watch, cfg, bags, 2)
    if "flygcity" in sources:
        jobs["flygcity"] = pool.submit(flygcity.search, origin, watch, cfg, watch["max_stops"])
    if "ving" in sources:
        jobs["ving"] = pool.submit(ving.search, origin, watch, cfg)
    if "sunweb" in sources:
        jobs["sunweb"] = pool.submit(sunweb.search, origin, watch, cfg)
    if "sembo" in sources and _sembo_polygon(watch["stay"]):
        jobs["sembo"] = pool.submit(sembo.search, origin, watch, cfg)
    # Browser sources run one at a time (each starts a Chromium).
    serial = [("momondo", momondo.search), ("qatar", qatar.search), ("google", google.search),
              ("apollo", apollo.search)]
    offers = []
    for name, fn in serial:
        if name in sources:
            try:
                offers += fn(origin, watch, cfg)
            except Exception as e:
                errors.append(f"{name} {origin} {watch['depart']}: {str(e)[:160]}")
    for name, fut in jobs.items():
        try:
            offers += fut.result()
        except Exception as e:
            errors.append(f"{name} {origin} {watch['depart']}: {str(e)[:160]}")
    seen, out = set(), []
    for o in offers:
        if o.key() in seen:
            continue
        seen.add(o.key())
        out.append(pricing.complete(o, watch, cfg))
    return sorted(out, key=lambda o: o.total)


def summarize(label, watch, cfg, offers, stay):
    flights = [o for o in offers if o.kind == "flight"]
    packages = [o for o in offers if o.kind == "package"]
    ok = [o for o in flights if o.max_stops <= watch["max_stops"]]
    two = [o for o in flights if o.max_stops > watch["max_stops"]]
    best = ok[0] if ok else None
    cheaper2 = two[0] if two and (not best or two[0].total < best.total) else None
    pkg = packages[0] if packages else None
    own = round(best.total + stay["total"]) if best and stay else None
    return {
        "label": label, "depart": watch["depart"].isoformat(), "return": watch["return"].isoformat(),
        "days": (watch["return"] - watch["depart"]).days,
        "best": best.to_dict() if best else None,
        "cheaper_two_stops": cheaper2.to_dict() if cheaper2 else None,
        "flights": [o.to_dict() for o in ok[:8]],
        "two_stops": [o.to_dict() for o in two[:4]],
        "stay": stay,
        "flight_plus_stay": own,
        "packages": [o.to_dict() for o in packages[:4]],
        "best_package": pkg.to_dict() if pkg else None,
        # positive = own arrangement is cheaper than the package (packages include hotel for 2 only)
        "package_minus_own": round(pkg.total - own) if pkg and own else None,
    }


# --- whole watch ---------------------------------------------------------------------------

def analyze_origin(w, cfg, db, run_id, ts, origin, sources, verify_n, pool, errors):
    """Everything the panel shows for one departure airport: cheapest combination incl. lodging,
    reference trip, same departure date, alternative dates. Returns (view, offers)."""
    bags = w["checked_bags_per_person"]
    ref = (w["depart"], w["return"]) if w.get("depart") else None

    log(f"{w['id']}: prismatris {origin} {w['earliest_depart']}–{w['latest_return']}")
    matrix = {}
    try:
        matrix = kiwi.price_matrix(origin, w, cfg, bags, w["max_stops"])
        store.add_matrix(db, run_id, ts, w["id"], origin, w["max_stops"], matrix)
    except Exception as e:
        errors.append(f"kiwi-matris {origin}: {e}")

    # No price targets configured: derive them from this window's price spread (cheapest 10 % = target,
    # 30 % = good, 60 % = acceptable), so "bra pris" means good for this trip.
    if not w["thresholds"] and matrix:
        prices = sorted(matrix.values())
        pick = lambda q: round(prices[min(len(prices) - 1, int(len(prices) * q))])
        w = {**w, "thresholds": {"target": pick(0.1), "good": pick(0.3), "acceptable": pick(0.6), "auto": True}}
    elif not w["thresholds"]:
        w = {**w, "thresholds": {"target": 0, "good": 0, "acceptable": 0, "auto": True}}
    else:
        w = {**w, "thresholds": dict(w["thresholds"])}

    # Per-night lodging estimate (reference stay, else a min-length stay at the window start) ranks the matrix.
    est_dep = ref[0] if ref else w["earliest_depart"]
    est_ret = ref[1] if ref else est_dep + timedelta(days=w["min_days"])
    ref_stay = stay_cost(w, est_dep + timedelta(days=1), est_ret)
    per_night = ref_stay["total"] / ref_stay["nights"]

    def valid(d, r):
        days = (r - d).days
        return (w["depart_range"][0] <= d <= w["depart_range"][1] and w["return_range"][0] <= r <= w["return_range"][1]
                and w["min_days"] <= days <= w["max_days"])

    ranked = []
    for (ds, rs), price in matrix.items():
        d, r = date.fromisoformat(ds), date.fromisoformat(rs)
        if valid(d, r):
            nights = (r - d).days - 1
            ranked.append({"depart": ds, "return": rs, "days": (r - d).days, "flight_est": round(price),
                           "stay_est": round(per_night * nights), "total_est": round(price + per_night * nights)})
    ranked.sort(key=lambda x: x["total_est"])

    combos = {"reference": ref} if ref else {}
    for c in ranked[:verify_n]:
        combos.setdefault(f"best{len(combos) + 1}", (date.fromisoformat(c["depart"]), date.fromisoformat(c["return"])))
    same_dep = [c for c in ranked if ref and c["depart"] == ref[0].isoformat()]
    if same_dep:
        combos["same_depart"] = (ref[0], date.fromisoformat(same_dep[0]["return"]))

    results, by_pair, all_offers = {}, {}, []
    for key, (d, r) in combos.items():
        if (d, r) in by_pair:  # same dates as an earlier combo: reuse
            results[key] = {**by_pair[(d, r)], "label": key}
            continue
        cw = _with_dates(w, d, r)
        log(f"{w['id']}: {key} {origin} {d}–{r}")
        offers = gather(origin, cw, cfg, sources, errors, pool)
        all_offers += offers
        best = next((o for o in offers if o.kind == "flight" and o.max_stops <= w["max_stops"]), None)
        checkin = date.fromisoformat(best.out.arrive[:10]) if best and best.out.arrive else d + timedelta(days=1)
        same = (checkin.isoformat(), r.isoformat()) == (ref_stay["checkin"], ref_stay["checkout"])
        stay = ref_stay if same else stay_cost(w, checkin, r)
        store.add_stay(db, run_id, ts, w["id"], stay)
        results[key] = by_pair[(d, r)] = summarize(key, cw, cfg, offers, stay)

    # Automatic thresholds come from Kiwi's cached matrix, which can be far off; scale them by how
    # verified prices compare with the matrix for the same dates, then re-label the offers.
    if w["thresholds"].get("auto"):
        ratios = [v["best"]["total"] / matrix[(v["depart"], v["return"])]
                  for v in by_pair.values() if v["best"] and matrix.get((v["depart"], v["return"]))]
        if ratios:
            f = sorted(ratios)[len(ratios) // 2]
            w["thresholds"].update({k: round(w["thresholds"][k] * f) for k in ("target", "good", "acceptable")})
            for v in by_pair.values():
                for o in [v["best"], v["cheaper_two_stops"], *v["flights"], *v["two_stops"]]:
                    if o:
                        o["category"] = pricing.classify(o["total"], w["thresholds"])

    candidates = [v for v in results.values() if v["flight_plus_stay"]]
    overall = min(candidates, key=lambda v: v["flight_plus_stay"]) if candidates else None
    headline = None
    if overall and overall["best"]:
        b = overall["best"]
        headline = {"total": b["total"], "per_person": b["per_person"], "category": b["category"],
                    "label": pricing.label(b["category"]), "origin": origin, "airlines": b["airlines"],
                    "depart": overall["depart"], "return": overall["return"], "source": b["source"], "url": b["url"],
                    "with_stay": overall["flight_plus_stay"], "stops": b["max_stops"]}
    verified = {(v["depart"], v["return"]): v for v in results.values()}
    alternatives = []
    for c in ranked[:10]:
        v = verified.get((c["depart"], c["return"]))
        alternatives.append({**c, "verified_flight": v["best"]["total"] if v and v["best"] else None,
                             "verified_total": v["flight_plus_stay"] if v else None})
    view = {"origin": origin, "name": config.airport_name(origin), "updated": ts,
            "sources": sources, "thresholds": w["thresholds"], "headline": headline, "overall": overall,
            "reference": results.get("reference"), "same_depart": results.get("same_depart"),
            "alternatives": alternatives}
    return view, all_offers


def run_watch(w, cfg, db, ts, quick=False, prev=None, only_origin=None):
    """Analyze every departure airport of a watch. The preferred one uses all sources; compare airports
    use the API sources. Results are cached per airport (status.json → by_origin) so the panel can
    switch airport instantly; an airport that fails keeps its previous cached view."""
    errors = []
    run_id = store.start_run(db, ts, w["id"])
    preferred = w["preferred_origin"]
    origins = [preferred] + [c for c in w["compare_origins"] if c != preferred]
    if only_origin:
        origins = [only_origin]
    api_sources = [s for s in w["sources"] if s not in SLOW_SOURCES]
    cache = dict((prev or {}).get("by_origin") or {})
    all_offers = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for code in origins:
            full = code == preferred and not quick
            n = cfg["general"].get("verify_top", 3) if full else 1
            try:
                view, offers = analyze_origin(w, cfg, db, run_id, ts, code, w["sources"] if full else api_sources,
                                              n, pool, errors)
                all_offers += offers
                view["full"] = full
                view["window_key"] = [w["earliest_depart"].isoformat(), w["latest_return"].isoformat(),
                                      w["min_days"], w["max_days"]]
                old = cache.get(code) or {}
                # A quick run (API sources only) must not replace a full run's result for the same dates:
                # it lacks Qatar/Google and would show a worse price as if it were the best found.
                keep_full = (not full and old.get("full") and old.get("headline")
                             and old.get("window_key") == view["window_key"])
                if (view["headline"] or code not in cache) and not keep_full:
                    cache[code] = view
            except Exception as e:
                traceback.print_exc()
                errors.append(f"{code}: {e}")

    store.add_offers(db, run_id, ts, w["id"], all_offers)
    main = cache.get(preferred) or {}
    headline = main.get("headline")
    store.finish_run(db, run_id, not errors, errors, headline)

    alert = None
    if not only_origin or only_origin == preferred:
        alert = notify.evaluate(w, headline, cfg["general"].get("notify_drop_pct", 3))
        if alert and cfg["general"].get("notify", True):
            notify.send(t("notify.title", dest=w["destination_name"]), alert, headline["url"],
                        "critical" if headline["category"] == "target" else "normal")

    def pick(v, key):
        b = v and v.get(key) and v[key].get("best")
        return {"total": b["total"], "airlines": b["airlines"], "source": b["source"], "url": b["url"],
                "depart": v[key]["depart"], "return": v[key]["return"]} if b else None

    summary = [{"code": c, "name": config.airport_name(c), "preferred": c == preferred,
                "reference": pick(cache.get(c), "reference"), "best": pick(cache.get(c), "overall"),
                "with_stay": (cache.get(c) or {}).get("headline", {}) and cache[c]["headline"]["with_stay"],
                "updated": (cache.get(c) or {}).get("updated")}
               for c in [preferred] + [x for x in w["compare_origins"] if x != preferred] if c in cache]
    return {
        **watch_meta(w),
        # Default view = preferred airport; by_origin holds every cached airport.
        **{k: main.get(k) for k in ("thresholds", "headline", "overall", "reference", "same_depart", "alternatives")},
        "by_origin": cache, "origins": summary,
        "trend": [{"ts": t, "total": v} for t, v in store.best_history(db, w["id"])],
        "alert": {"text": alert, "time": ts, "unread": True} if alert else None,
        "errors": errors,
    }


def watch_meta(w):
    """The trip's settings as the app/bar show them; a new trip gets just this until its first search."""
    preferred = w["preferred_origin"]
    ref = (w["depart"], w["return"]) if w.get("depart") else None
    return {
        "id": w["id"], "name": w["name"], "active": w["active"], "destination": w["destination"],
        "destinations": w["destinations"], "destination_info": w.get("destination_info", []),
        "reference_dates": {"depart": ref[0].isoformat(), "return": ref[1].isoformat()} if ref else None,
        "destination_name": w["destination_name"], "adults": w["adults"], "bags": w["checked_bags_per_person"],
        "preferred_origin": preferred, "compare_origins": w["compare_origins"],
        "window": {"earliest_depart": w["earliest_depart"].isoformat(), "latest_return": w["latest_return"].isoformat(),
                   "min_days": w["min_days"], "max_days": w["max_days"], "flex_days": w.get("flex_days"),
                   "depart_range": [d.isoformat() for d in w["depart_range"]],
                   "return_range": [d.isoformat() for d in w["return_range"]]},
        "stay_cfg": w["stay"],
    }


def write_status(status):
    config.STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=1, default=str))
    tmp.replace(config.STATUS_PATH)


def read_status():
    try:
        return json.loads(config.STATUS_PATH.read_text())
    except Exception:
        return {"watches": []}


def run(watch_id=None, quick=False, origin=None):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = FileLock(config.LOCK_PATH)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        if not quick:  # a full run is already doing the work
            log("en körning pågår redan")
            return 0
        # Quick runs follow a settings change (e.g. new airport) and must not be lost: wait.
        log("väntar på pågående körning")
        lock.acquire()
    cfg = config.load()
    prev = read_status()
    prev_alerts = {w["id"]: w.get("alert") for w in prev.get("watches", [])}
    prev["running"] = True
    write_status(prev)
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    db = store.connect()
    out = []
    try:
        for w in cfg["watch"]:
            if watch_id and w["id"] != watch_id:
                continue
            if not w["active"]:
                old = next((x for x in prev.get("watches", []) if x["id"] == w["id"]), None)
                if old:
                    out.append({**old, "active": False})
                continue
            try:
                old = next((x for x in prev.get("watches", []) if x["id"] == w["id"]), None)
                res = run_watch(w, cfg, db, ts, quick, old, origin)
            except Exception as e:
                traceback.print_exc()
                res = next((x for x in prev.get("watches", []) if x["id"] == w["id"]), {"id": w["id"], "name": w["name"]})
                res["errors"] = [t("run.failed", err=e)]
            # Keep an unread alert from an earlier run until it is acknowledged.
            if not res.get("alert") and prev_alerts.get(w["id"], {}) and prev_alerts[w["id"]].get("unread"):
                res["alert"] = prev_alerts[w["id"]]
            out.append(res)
        if watch_id:
            known = {w["id"] for w in cfg["watch"]}
            out += [x for x in prev.get("watches", []) if x["id"] != watch_id and x["id"] in known]
    finally:
        # Trips created while this run was going (`flightwatch new`) are in the file but not in `prev`.
        now = config.load()
        known = {w["id"] for w in now["watch"]}
        done = {x["id"] for x in out}
        out += [x for x in read_status().get("watches", []) if x["id"] not in done and x["id"] in known]
        write_status({"updated": ts, "running": False, "quick": quick, "selected": now["general"].get("selected"),
                      "watches": [x for x in out if x["id"] in known] or prev.get("watches", [])})
        db.close()
    return 0
