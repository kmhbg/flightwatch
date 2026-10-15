"""Price history in SQLite (~/.local/share/flightwatch/history.db)."""
import json
import sqlite3

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, ts TEXT, watch TEXT, ok INTEGER, errors TEXT, best_total REAL, best_json TEXT);
CREATE TABLE IF NOT EXISTS offers (
  run_id INTEGER, ts TEXT, watch TEXT, origin TEXT, source TEXT, kind TEXT, depart TEXT, ret TEXT,
  total REAL, ticket_total REAL, bag_cost REAL, max_stops INTEGER, airlines TEXT, category TEXT, url TEXT, json TEXT);
CREATE INDEX IF NOT EXISTS offers_watch ON offers(watch, depart, ret, ts);
CREATE TABLE IF NOT EXISTS matrix (
  run_id INTEGER, ts TEXT, watch TEXT, origin TEXT, max_stops INTEGER, depart TEXT, ret TEXT, price REAL);
CREATE TABLE IF NOT EXISTS stays (
  run_id INTEGER, ts TEXT, watch TEXT, checkin TEXT, checkout TEXT, source TEXT, total REAL, our_cost REAL,
  name TEXT, url TEXT);
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    return db


def start_run(db, ts, watch):
    cur = db.execute("INSERT INTO runs (ts, watch, ok) VALUES (?, ?, 0)", (ts, watch))
    return cur.lastrowid


def finish_run(db, run_id, ok, errors, best):
    db.execute("UPDATE runs SET ok=?, errors=?, best_total=?, best_json=? WHERE id=?",
               (int(ok), json.dumps(errors, ensure_ascii=False), best["total"] if best else None,
                json.dumps(best, ensure_ascii=False) if best else None, run_id))
    db.commit()


def add_offers(db, run_id, ts, watch, offers):
    db.executemany(
        "INSERT INTO offers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(run_id, ts, watch, o.origin, o.source, o.kind, o.depart_date, o.return_date, o.total, o.ticket_total,
          o.bag_cost, o.max_stops, "/".join(o.airlines), o.category, o.url,
          json.dumps(o.to_dict(), ensure_ascii=False)) for o in offers])


def add_matrix(db, run_id, ts, watch, origin, max_stops, matrix):
    db.executemany("INSERT INTO matrix VALUES (?,?,?,?,?,?,?,?)",
                   [(run_id, ts, watch, origin, max_stops, d, r, p) for (d, r), p in matrix.items()])


def add_stay(db, run_id, ts, watch, stay):
    db.execute("INSERT INTO stays VALUES (?,?,?,?,?,?,?,?,?,?)",
               (run_id, ts, watch, stay["checkin"], stay["checkout"], stay["source"], stay["total"],
                stay["total"], stay.get("name", ""), stay.get("url", "")))


def best_history(db, watch, limit=60):
    """[(ts, best_total)] for the sparkline/trend, oldest first."""
    rows = db.execute("SELECT ts, best_total FROM runs WHERE watch=? AND best_total IS NOT NULL "
                      "ORDER BY id DESC LIMIT ?", (watch, limit)).fetchall()
    return list(reversed(rows))


def lowest_seen(db, watch, depart, ret, max_stops):
    row = db.execute("SELECT MIN(total) FROM offers WHERE watch=? AND depart=? AND ret=? AND kind='flight' "
                     "AND max_stops<=?", (watch, depart, ret, max_stops)).fetchone()
    return row[0] if row else None
