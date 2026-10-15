"""Core logic without network or GUI: translations, money, the app's scheduler and alerts."""
import json
from datetime import datetime
from importlib.resources import files

import pytest

from flightwatch import i18n
from flightwatch.app import due_slot, new_alerts


def _catalog(code):
    return json.loads(files("flightwatch").joinpath("i18n", f"{code}.json").read_text(encoding="utf-8"))


def test_catalogs_have_the_same_keys_and_placeholders():
    import re
    sv, en = _catalog("sv"), _catalog("en")
    assert set(sv) == set(en)
    ph = lambda v: sorted(re.findall(r"\{(\w+)", json.dumps(v)))  # noqa: E731
    for k in sv:
        assert ph(sv[k]) == ph(en[k]), k
        assert isinstance(sv[k], dict) == isinstance(en[k], dict), k


@pytest.fixture
def lang(monkeypatch):
    def use(code):
        monkeypatch.setenv("FLIGHTWATCH_LANG", code)
        i18n.reset()
    yield use
    i18n.reset()


def test_translate_and_plural(lang):
    lang("sv")
    assert i18n.t("unit.night", n=1) == "1 natt"
    assert i18n.t("unit.night", n=5) == "5 nätter"
    lang("en")
    assert i18n.t("unit.night", n=5) == "5 nights"
    assert i18n.t("no.such.key") == "no.such.key"


def test_money_format():
    assert i18n.fmt_money(6294.4, "SEK", "sv") == "6 294 kr"
    assert i18n.fmt_money(6294.4, "SEK", "en") == "SEK 6,294"
    assert i18n.fmt_money(563, "EUR", "en") == "€563"
    assert i18n.fmt_money(563, "EUR", "sv") == "563 €"
    assert i18n.fmt_money(None) == "—"


TIMES = ["07:30", "19:30"]


@pytest.mark.parametrize("times, now, last, expected", [
    # the 07:30 slot has passed and was not run yet
    (TIMES, "2026-10-16 07:31", "2026-10-15 19:30", "2026-10-16 07:30"),
    # already handled
    (TIMES, "2026-10-16 07:31", "2026-10-16 07:30", None),
    # computer was off overnight: yesterday evening's slot is run once in the morning (11.5 h late)
    (TIMES, "2026-10-18 07:00", "2026-10-15 19:30", "2026-10-17 19:30"),
    # the newest missed slot is more than 12 h old – skip it rather than search at an odd time
    (["07:30"], "2026-10-18 20:00", "2026-10-15 07:30", None),
])
def test_due_slot(times, now, last, expected):
    p = datetime.fromisoformat
    got = due_slot(times, p(now), p(last))
    assert got == (p(expected) if expected else None)


def test_new_alerts_only_unread_and_unseen(lang):
    lang("en")
    st = {"watches": [
        {"id": "a", "name": "A", "destination_name": "Bali", "alert": {"text": "cheap", "time": "t1", "unread": True}},
        {"id": "b", "name": "B", "alert": {"text": "old", "time": "t0", "unread": False}},
        {"id": "c", "name": "C", "alert": None},
    ]}
    got = new_alerts(st, set())
    assert got == [("a|t1", "Flight price ✈ Bali", "cheap")]
    assert new_alerts(st, {"a|t1"}) == []
