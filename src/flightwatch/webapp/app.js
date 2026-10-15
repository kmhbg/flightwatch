// Flightwatch app: reads /api/status (same data as the bar panel) and shows what each option includes.
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// --- language and money (/api/i18n) ----------------------------------------------------------
// Prices arrive in SEK; I.rate converts to the display currency the user chose.
const I = { s: {}, lang: "sv", locale: "sv-SE", currency: "SEK", rate: 1, times: ["07:30", "19:30"] };
function t(key, vars = {}) {
  let v = I.s[key] ?? key;
  if (typeof v === "object") v = vars.n === 1 ? v.one : v.other;
  return v.replace(/\{(\w+)\}/g, (m, k) => (vars[k] ?? m));
}
const tn = (key, n) => t(key, { n });
let moneyFmt = null;
const money = (sek) => (sek === null || sek === undefined) ? "—" : moneyFmt.format(sek * I.rate);
let dayFmt = null;
const day = (iso) => iso ? dayFmt.format(new Date(iso.slice(0, 10) + "T12:00:00")).replace(/\.$/, "") : "";
const hm = (iso) => iso && iso.length >= 16 ? iso.slice(11, 16) : "";
const dur = (m) => m ? `${Math.floor(m / 60)} h ${m % 60} min` : "";
const stops = (n) => n === 0 ? t("unit.direct") : tn("unit.stops", n);
const joinAnd = (xs) => xs.length > 1 ? xs.slice(0, -1).join(", ") + " " + t("word.and") + " " + xs[xs.length - 1] : xs.join("");
const SRC = { kiwi: "Kiwi.com", flygcity: "flygcity", google: "Google Flights", ving: "Ving", apollo: "Apollo", momondo: "momondo",
  qatar: "Qatar Airways", sembo: "Sembo", sunweb: "Sunweb", airbnb: "Airbnb", booking: "Booking.com", "hotels.com": "Hotels.com" };
const src = (k) => SRC[k] || ((k === "airline" || k === "fallback") ? t("src." + k) : k);
const rating = (s, r) => r ? (s === "airbnb" ? `★ ${r}/5` : `${r}/10`) : "";
const LABEL = (c) => c ? t("cat." + c) : "";
const COMBOS = ["overall", "reference", "same_depart"];

async function loadI18n() {
  const d = await api("/api/i18n");
  Object.assign(I, d);
  document.documentElement.lang = I.lang;
  moneyFmt = new Intl.NumberFormat(I.locale, { style: "currency", currency: I.currency, maximumFractionDigits: 0 });
  dayFmt = new Intl.DateTimeFormat(I.locale, { day: "numeric", month: "short" });
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-title]")) el.title = t(el.dataset.i18nTitle);
  for (const el of document.querySelectorAll("[data-i18n-aria]")) el.setAttribute("aria-label", t(el.dataset.i18nAria));
  for (const el of document.querySelectorAll("[data-i18n-n]")) {
    const [key, n] = el.dataset.i18nN.split(":");
    el.textContent = tn(key, Number(n));
  }
}

const state = { status: null, raw: "", trip: "", origin: "", combo: "overall", key: "f:0", uiSeq: -1 };

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json", "x-flightwatch": "1" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

// --- navigation (also driven from the bar panel through /api/ui) -------------------------------
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (p.get("w")) state.trip = p.get("w");
  if (p.get("o")) state.origin = p.get("o");
  if (p.get("c")) state.combo = p.get("c");
  if (p.get("k")) state.key = p.get("k");
}
function writeHash() {
  const p = new URLSearchParams({ w: state.trip, o: state.origin, c: state.combo, k: state.key });
  history.replaceState(null, "", "#" + p.toString());
}

// --- data helpers ------------------------------------------------------------------------------
const trips = () => (state.status && state.status.watches) || [];
function trip() {
  const ts = trips();
  return ts.find((t) => t.id === state.trip) || ts.find((t) => t.id === state.status.selected) || ts[0] || null;
}
function view(t) {
  if (!t) return null;
  const o = state.origin || t.preferred_origin;
  return (t.by_origin || {})[o] || (o === t.preferred_origin ? t : null);
}
function combo(v) { return v ? v[state.combo] || v.overall : null; }
function optionByKey(c, key) {
  if (!c) return null;
  const [kind, i] = key.split(":");
  const n = Number(i || 0);
  if (kind === "f") return c.flights && c.flights[n] ? { kind: "flight", o: c.flights[n] } : null;
  if (kind === "t") return c.two_stops && c.two_stops[n] ? { kind: "flight", o: c.two_stops[n] } : null;
  if (kind === "p") return c.packages && c.packages[n] ? { kind: "package", o: c.packages[n] } : null;
  if (kind === "s") return c.stay ? { kind: "stay", o: c.stay } : null;
  return null;
}

// --- rendering ---------------------------------------------------------------------------------
function windowText(tr) {
  const w = tr.window, r = tr.reference_dates;
  const range = t("unit.days_range", { min: w.min_days, max: w.max_days });
  if (r && w.flex_days !== null && w.flex_days !== undefined)
    return t("app.window_flex", { dep: day(r.depart), ret: day(r.return), flex: tn("unit.day", w.flex_days), range });
  return t("app.window_range", { from: day(w.earliest_depart), to: day(w.latest_return), range });
}

function render() {
  const tr = trip();
  document.body.classList.toggle("empty", !tr);
  if (!tr) {
    for (const id of ["#trips", "#origins", "#headline", "#combos", "#alternatives"]) $(id).innerHTML = "";
    $("#statusline").textContent = "";
    $("#options").innerHTML = `<div class="welcome"><p>${esc(t("app.no_trips"))}</p>
      <button class="primary" onclick="openDialog('new')">${esc(t("app.new"))}</button></div>`;
    return;
  }
  state.trip = tr.id;
  if (!state.origin || !((tr.by_origin || {})[state.origin] || state.origin === tr.preferred_origin)) state.origin = tr.preferred_origin;
  const v = view(tr);
  const sel = state.status.selected;

  $("#trips").innerHTML = trips().map((x) =>
    `<button data-trip="${esc(x.id)}" class="${x.id === tr.id ? "selected" : ""}" title="${esc(x.id === sel ? t("app.trip_default") : t("app.trip_make_default"))}">${esc(x.name)}${x.reference_dates ? ` <small>${day(x.reference_dates.depart)}–${day(x.reference_dates.return)}</small>` : ""}${x.id === sel ? " ★" : ""}</button>`).join("");

  const up = (v && v.updated) || state.status.updated;
  const times = joinAnd(I.times);
  $("#statusline").textContent = [tr.name, tr.destination_name, tn("unit.adult", tr.adults), tn("unit.bag_pp", tr.bags), windowText(tr),
    state.status.running ? t("app.searching") : up ? t("app.updated", { date: day(up), time: hm(up), times }) : t("app.updated_never", { times })].join(" · ");
  const al = $("#alert");
  al.hidden = !(tr.alert && tr.alert.unread);
  if (tr.alert) al.textContent = "🔔 " + tr.alert.text + " " + t("app.alert_click");

  const origins = [tr.preferred_origin, ...(tr.compare_origins || [])];
  Object.keys(tr.by_origin || {}).forEach((k) => { if (!origins.includes(k)) origins.push(k); });
  $("#origins").innerHTML = origins.map((code) => {
    const c = (tr.by_origin || {})[code];
    const h = c && c.headline;
    const title = c ? t("app.origin_saved", { date: day(c.updated), time: hm(c.updated) }) : t("app.origin_none");
    return `<button data-origin="${esc(code)}" class="${code === state.origin ? "selected" : ""}" title="${esc(title)}">` +
      `${esc(code)}${code === tr.preferred_origin ? " ★" : ""} <span class="${h ? "cat-" + h.category : ""}">${h ? money(h.total) : "…"}</span></button>`;
  }).join("");

  if (!v || !(v.headline || v.overall)) {
    $("#headline").innerHTML = ""; $("#combos").innerHTML = "";
    const rest = state.status.running ? t("app.no_prices_running") : t("app.no_prices_next");
    $("#options").innerHTML = `<p class="muted">${esc(t("app.no_prices", { origin: state.origin, rest }))}</p>`;
    $("#alternatives").innerHTML = ""; renderDetail(null, null); return;
  }
  const h = v.headline;
  const th = v.thresholds || {};
  $("#headline").innerHTML = h ? `
    <div class="stat"><small>${esc(t("app.best_flight"))}</small><div class="big cat-${h.category}">${money(h.total)}</div>
      <small>${LABEL(h.category)} · ${t("unit.per_person", { price: money(h.per_person) })} · ${day(h.depart)}–${day(h.return)}</small></div>
    <div class="stat"><small>${esc(t("app.flight_stay_total"))}</small><div class="big">${money(h.with_stay)}</div>
      <small>${th.auto ? t("app.target_auto") : t("app.target")} ≤ ${money(th.target)} · ${t("app.good")} ≤ ${money(th.good)} · ${t("app.ok")} ≤ ${money(th.acceptable)}</small></div>` : "";

  $("#combos").innerHTML = COMBOS.filter((k) => v[k]).map((k) =>
    `<button data-combo="${k}" class="${k === state.combo ? "selected" : ""}">${esc(t("combo." + k))} · ${day(v[k].depart)}–${day(v[k].return)}</button>`).join("");
  if (!v[state.combo]) state.combo = "overall";
  const c = combo(v);
  $("#options").innerHTML = c ? renderOptions(c) : "";

  $("#alternatives").innerHTML = (v.alternatives || []).slice(0, 10).map((a) =>
    `<div>${day(a.depart)} – ${day(a.return)} (${a.days} d)</div><div class="v ${a.verified_total ? "" : "est"}">${a.verified_total ? "✓ " + money(a.verified_total) : "≈ " + money(a.total_est)}</div>`).join("");

  if (!optionByKey(c, state.key)) state.key = "f:0";
  renderDetail(c, optionByKey(c, state.key));
  writeHash();
}

function optRow(key, title, price, cat, sub) {
  return `<div class="opt ${key === state.key ? "active" : ""}" data-key="${key}">
    <div class="title">${title}</div><div class="price ${cat ? "cat-" + cat : ""}">${price}</div><div class="sub">${sub}</div></div>`;
}

function renderOptions(c) {
  let html = "";
  const flightSub = (o) => `${hm(o.out.depart)} → ${day(o.out.arrive)} ${hm(o.out.arrive)}${o.out.via.length ? " via " + o.out.via.join(", ") : ""} · ` +
    `${esc(o.booking_via || src(o.source))} · ${o.bag_cost_estimated ? t("app.bag_estimated") : t("app.bag_included")}`;
  if (c.flights && c.flights.length) {
    html += `<div class="group-title">${esc(t("app.group_flights"))}</div>`;
    html += c.flights.map((o, i) => optRow(`f:${i}`, `${esc(o.airlines.join(" / "))} · ${stops(o.max_stops)} · ${dur(o.out.duration_min)}`,
      money(o.total), o.category, flightSub(o))).join("");
  }
  if (c.two_stops && c.two_stops.length) {
    html += `<div class="group-title">${esc(t("app.group_two_stops"))}</div>`;
    html += c.two_stops.map((o, i) => optRow(`t:${i}`, `${esc(o.airlines.join(" / "))} · ${stops(o.max_stops)}`,
      money(o.total), o.category, flightSub(o))).join("");
  }
  if (c.stay) {
    const s = c.stay;
    html += `<div class="group-title">${esc(t("app.group_stay"))}</div>`;
    html += optRow("s", esc(s.name), money(s.total), "",
      `${esc(src(s.source))} · ${tn("unit.night", s.nights)} · ${tn("unit.guest", s.guests)}${s.beds ? " · " + esc(s.beds) : ""}${s.rating ? " · " + rating(s.source, s.rating) : ""}`);
  }
  if (c.packages && c.packages.length) {
    html += `<div class="group-title">${esc(t("app.group_packages"))}</div>`;
    html += c.packages.map((o, i) => optRow(`p:${i}`, esc(o.hotel), money(o.total), "",
      `${esc(src(o.source))} · ${esc(o.airlines.join(" / "))} · ${day(o.depart_date)}–${day(o.return_date)}`)).join("");
  }
  return html;
}

function legHtml(label, l) {
  if (!l || !l.depart) return `<div class="leg"><b>${label}</b><br><span class="muted">${esc(t("app.leg_no_times"))}</span></div>`;
  const lay = (l.via || []).map((v, i) => `${esc(v)}${l.layovers_min && l.layovers_min[i] ? " (" + dur(l.layovers_min[i]) + ")" : ""}`).join(", ");
  return `<div class="leg"><b>${label}</b> · ${day(l.depart)}
    <div class="times">${hm(l.depart)} → ${l.arrive ? day(l.arrive) + " " + hm(l.arrive) : "?"}</div>
    <div>${esc((l.carriers || []).join(" / "))} · ${stops(l.stops)}${l.duration_min ? " · " + dur(l.duration_min) : ""}</div>
    ${lay ? `<div class="muted">${t("app.leg_layover", { list: lay })}</div>` : ""}
    ${l.self_transfer ? `<div class="warn">${esc(t("app.leg_self_transfer"))}</div>` : ""}</div>`;
}

function renderDetail(c, sel) {
  const d = $("#detail");
  if (!c || !sel) { d.innerHTML = `<p class="muted">${esc(t("app.pick_option"))}</p>`; return; }
  const o = sel.o;
  const stay = c.stay;
  const row = (k, v) => `<tr><td>${k}</td><td>${v}</td></tr>`;
  let html = "";
  if (sel.kind === "flight") {
    const withStay = stay ? o.total + stay.total : null;
    html = `<h2>${esc(o.airlines.join(" / "))}</h2>
      <div class="muted">${day(c.depart)} – ${day(c.return)} · ${tn("unit.day", c.days)} · ${esc(t("app.sold_by", { who: o.booking_via || src(o.source) }))}</div>
      <div class="total cat-${o.category}">${money(o.total)} <span class="badge">${LABEL(o.category)}</span></div>
      <table>
        ${row(esc(t("app.ticket", { what: o.tickets > 1 ? tn("unit.ticket", o.tickets) : t("app.all_travellers") })), money(o.ticket_total))}
        ${row(esc(t("app.checked_bags")) + (o.bag_cost_estimated ? " " + esc(t("app.estimated")) : ""), money(o.bag_cost))}
        ${o.fees ? row(esc(t("app.fees")), money(o.fees)) : ""}
        ${row(`<b>${esc(t("app.flight_total"))}</b>`, `<b>${money(o.total)}</b>`)}
        ${row(esc(t("app.per_person")), money(o.per_person))}
        ${stay ? row(esc(t("app.stay_total", { nights: tn("unit.night", stay.nights) })), money(stay.total)) +
          row(`<b>${esc(t("app.flight_stay"))}</b>`, `<b>${money(withStay)}</b>`) : ""}
      </table>
      ${legHtml(esc(t("app.leg_out")), o.out)}
      ${legHtml(esc(t("app.leg_back")), o.back)}
      <div class="section"><b>${esc(t("app.bags"))}</b>${esc(o.bag_note || "–")}</div>
      <div class="section"><b>${esc(t("app.conditions"))}</b>${esc(o.conditions || "–")}</div>
      ${o.tickets > 1 ? `<div class="section warn">${esc(t("app.separate_tickets", { n: o.tickets }))}</div>` : ""}
      ${o.booking_options && o.booking_options.length ? `<div class="section"><b>${esc(t("app.booking_options"))}</b><table>` +
        o.booking_options.map((b) => row(esc(b.who) + (b.airline ? " · " + esc(t("app.airline")) : ""), money(b.price))).join("") + "</table></div>" : ""}
      <div class="row"><button class="primary" data-open="${esc(o.url)}">${esc(t("app.open_booking"))}</button></div>`;
  } else if (sel.kind === "stay") {
    const bySrc = Object.entries(o.by_source || {});
    const errs = Object.entries(o.errors || {});
    html = `<h2>${esc(o.name)}</h2>
      <div class="muted">${esc(src(o.source))} · ${day(o.checkin)} – ${day(o.checkout)} · ${tn("unit.night", o.nights)} · ${tn("unit.guest", o.guests)}</div>
      <div class="total">${money(o.total)}</div>
      <table>
        ${row(esc(t("app.per_night")), money(o.total / o.nights))}
        ${o.rating ? row(esc(t("app.rating")), rating(o.source, o.rating) + (o.reviews ? ` (${tn("unit.review", o.reviews)})` : "")) : ""}
        ${o.beds ? row(esc(t("app.place")), esc(o.beds)) : ""}
        ${row(esc(t("app.source")), o.source === "airbnb" ? esc(t("app.airbnb_fav")) : esc(src(o.source)))}
        ${o.matches ? row(esc(t("app.matches")), o.matches) : ""}
      </table>
      ${o.note ? `<div class="section warn">${esc(o.note)}</div>` : ""}
      ${bySrc.length ? `<div class="section"><b>${esc(t("app.cheapest_per_source"))}</b><table>` +
        bySrc.map(([k, a]) => row(`${esc(src(k))} · <a href="#" data-open="${esc(a.url)}">${esc(a.name)}</a> ${rating(k, a.rating)}`, money(a.total))).join("") +
        errs.map(([k, e]) => `<tr><td>${esc(src(k))}</td><td class="muted">${esc(e)}</td></tr>`).join("") + "</table></div>" : ""}
      ${(o.alternatives || []).length ? `<div class="section"><b>${esc(t("app.other_options"))}</b><table>` +
        o.alternatives.map((a) => row(`${esc(src(a.source || ""))} · <a href="#" data-open="${esc(a.url)}">${esc(a.name)}</a> ${rating(a.source, a.rating)}`, money(a.total))).join("") + "</table></div>" : ""}
      <div class="muted">${esc(t("app.stay_rules"))}</div>
      <div class="row">${o.search_url ? `<button class="ghost" data-open="${esc(o.search_url)}">${esc(t("app.all_airbnb"))}</button>` : ""}
        <button class="primary" data-open="${esc(o.url)}">${esc(t("app.open_stay"))}</button></div>`;
  } else {
    const own = c.flight_plus_stay;
    html = `<h2>${esc(o.hotel)}</h2>
      <div class="muted">${esc(src(o.source))} · ${esc(t("app.package"))} · ${day(o.depart_date)} – ${day(o.return_date)}</div>
      <div class="total">${money(o.total)}</div>
      <table>
        ${row(esc(t("app.per_person")), money(o.per_person))}
        ${own ? row(esc(t("app.own")), money(own)) +
          row(`<b>${esc(t(o.total > own ? "app.own_cheaper" : "app.package_cheaper"))}</b>`, `<b>${money(Math.abs(o.total - own))}</b>`) : ""}
      </table>
      ${legHtml(esc(t("app.leg_out")), o.out)}
      ${legHtml(esc(t("app.leg_back")), o.back)}
      <div class="section"><b>${esc(t("app.bags"))}</b>${esc(o.bag_note || "–")}</div>
      <div class="section"><b>${esc(t("app.conditions"))}</b>${esc(o.conditions)}</div>
      <div class="row"><button class="primary" data-open="${esc(o.url)}">${esc(t("app.open_at", { who: src(o.source) }))}</button></div>`;
  }
  d.innerHTML = html;
}

function renderTrend(points) {
  const svg = $("#trend");
  if (!points.length) { svg.innerHTML = ""; return; }
  const vals = points.map((p) => p.total);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const pts = points.map((p, i) => `${(i / Math.max(1, points.length - 1)) * 400},${70 - ((p.total - lo) / span) * 60}`).join(" ");
  svg.innerHTML = `<polyline points="${pts}"/><title>${money(lo)} – ${money(hi)}</title>`;
}

// --- loading / polling -------------------------------------------------------------------------
async function load(force) {
  try {
    const r = await fetch("/api/status", { cache: "no-store" });
    const text = await r.text();
    if (!force && text === state.raw) return;
    state.raw = text;
    state.status = JSON.parse(text);
    render();
    const tr = trip();
    if (tr) renderTrend(await api(`/api/history?watch=${encodeURIComponent(tr.id)}`));
    else renderTrend([]);
  } catch (e) {
    $("#statusline").textContent = t("app.status_error", { msg: e.message });
  }
}

async function pollUi() {
  try {
    const u = await api("/api/ui");
    if (u.seq !== state.uiSeq) {
      const first = state.uiSeq === -1;
      state.uiSeq = u.seq;
      if (!first && u.nav) { location.hash = u.nav; readHash(); render(); }
    }
  } catch (e) { /* server restarting */ }
}

// --- events ------------------------------------------------------------------------------------
document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-trip],[data-origin],[data-combo],[data-key],[data-open],#alert");
  if (!el) return;
  if (el.dataset.open) { ev.preventDefault(); await api("/api/open", { url: el.dataset.open }); return; }
  if (el.id === "alert") { await api("/api/ack", {}); return load(true); }
  if (el.dataset.trip) { state.trip = el.dataset.trip; state.origin = ""; state.combo = "overall"; state.key = "f:0"; }
  if (el.dataset.origin) { state.origin = el.dataset.origin; state.key = "f:0"; }
  if (el.dataset.combo) { state.combo = el.dataset.combo; state.key = "f:0"; }
  if (el.dataset.key) state.key = el.dataset.key;
  render();
});
document.addEventListener("contextmenu", async (ev) => {
  const el = ev.target.closest("[data-trip]");
  if (!el) return;
  ev.preventDefault();
  await api("/api/select", { watch: el.dataset.trip });
  load(true);
});
$("#btn-search").onclick = async () => { await api("/api/search", { watch: "" }); load(true); };

// Suggestions while typing (airports, places, countries)
const picked = { from: null, to: null, origin: null };
function suggestField(input, kind, slot, onPick) {
  const ul = input.nextElementSibling;
  let timer = null, seq = 0, items = [];
  input.addEventListener("input", () => {
    picked[slot] = null;
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { ul.innerHTML = ""; return; }
    timer = setTimeout(async () => {
      const my = ++seq;
      items = await api(`/api/suggest?q=${encodeURIComponent(q)}&kind=${kind}`);
      if (my !== seq) return;
      ul.innerHTML = items.map((s, i) => `<li data-i="${i}">${s.kind === "place" ? "📍" : "✈"} ${esc(s.label)}<small>${esc(s.detail)}</small></li>`).join("");
    }, 300);
  });
  ul.addEventListener("click", (ev) => {
    const li = ev.target.closest("li");
    if (!li) return;
    picked[slot] = items[Number(li.dataset.i)];
    input.value = onPick ? onPick(picked[slot]) : picked[slot].label;
    ul.innerHTML = "";
    updateWindow();
  });
}
// Dates: a planned trip + flexibility. Mirrors config.default_flex: long trips/long-haul ±2 and at most
// 2 days shorter, short trips ±1. The server makes the final call (it knows the flight distance).
const iso = (d) => d.toISOString().slice(0, 10);
const addDays = (s, n) => { const d = new Date(s + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
let dlgMode = "new";  // new | dates (change the selected trip's dates)
function flexFor(days) {
  const v = $("#f-flex").value;
  if (v !== "auto") return [Number(v), Number(v)];
  return days >= 10 ? [2, 2] : [1, 1];
}
function updateWindow() {
  const dep = $("#f-depart").value, ret = $("#f-return").value, el = $("#f-window");
  const compareOnly = dlgMode === "new" && !$("#f-to").value.trim() && trip();
  $("#f-dates").style.opacity = compareOnly ? ".45" : "";
  if (compareOnly) { el.textContent = t("dlg.compare_only"); return; }
  if (!dep || !ret) { el.textContent = t("dlg.pick_dates"); return; }
  const days = Math.round((new Date(ret) - new Date(dep)) / 864e5);
  if (days < 1) { el.textContent = t("dlg.return_after"); return; }
  const [flex, shorter] = flexFor(days);
  el.textContent = flex
    ? t("dlg.window", { days: tn("unit.day", days), d1: day(addDays(dep, -flex)), d2: day(addDays(dep, flex)),
        r1: day(addDays(ret, -flex)), r2: day(addDays(ret, flex)), range: t("unit.days_range", { min: days - shorter, max: days }) })
    : t("dlg.exact", { days: tn("unit.day", days) });
}
suggestField($("#f-from"), "from", "from");
suggestField($("#f-to"), "to", "to");
$("#f-to").addEventListener("input", updateWindow);
for (const id of ["#f-depart", "#f-return", "#f-flex"]) $(id).addEventListener("input", updateWindow);
$("#f-depart").addEventListener("change", () => {
  const dep = $("#f-depart").value, ret = $("#f-return").value;
  $("#f-return").min = dep ? addDays(dep, 1) : "";
  if (dep && (!ret || ret <= dep)) $("#f-return").value = addDays(dep, 7);
  updateWindow();
});
function openDialog(mode) {
  dlgMode = mode;
  const tr = trip();
  const tomorrow = addDays(iso(new Date()), 1);
  $("#f-depart").min = tomorrow;
  $("#f-msg").textContent = "";
  for (const el of document.querySelectorAll("#form-new > label, .f-new")) el.style.display = mode === "dates" ? "none" : "";
  if (mode === "dates") {
    if (!tr) return;
    $("#f-title").textContent = t("dlg.dates_title", { name: tr.name });
    $("#f-depart").value = tr.reference_dates ? tr.reference_dates.depart : "";
    $("#f-return").value = tr.reference_dates ? tr.reference_dates.return : "";
    const f = tr.window && tr.window.flex_days;
    $("#f-flex").value = f === null || f === undefined ? "auto" : String(Math.min(3, f));
    $("#f-submit").textContent = t("dlg.save_search");
  } else {
    $("#f-title").textContent = t("dlg.new");
    $("#f-from").value = ""; $("#f-to").value = ""; picked.from = picked.to = null;
    $("#f-depart").value = ""; $("#f-return").value = ""; $("#f-flex").value = "auto";
    if (tr) $("#f-adults").value = tr.adults;
    $("#f-submit").textContent = t("dlg.search");
  }
  updateWindow();
  $("#dlg-new").showModal();
}
$("#btn-new").onclick = () => openDialog("new");
$("#btn-dates").onclick = () => openDialog("dates");
$("#btn-remove").onclick = async () => {
  const tr = trip();
  if (!tr || !confirm(t("dlg.remove_confirm", { name: tr.name }))) return;
  try { await api("/api/remove", { watch: tr.id }); } catch (e) { alert(e.message); return; }
  state.trip = ""; state.origin = ""; state.combo = "overall"; state.key = "f:0";
  load(true);
};
$("#f-cancel").onclick = () => $("#dlg-new").close();
function checkDates() {
  const dep = $("#f-depart").value, ret = $("#f-return").value;
  if (!dep || !ret) throw new Error(t("dlg.pick_dates"));
  if (dep < addDays(iso(new Date()), 1)) throw new Error(t("dlg.depart_future"));
  if (ret <= dep) throw new Error(t("dlg.return_after"));
  return { depart: dep, return: ret, flex: $("#f-flex").value };
}
$("#form-new").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = $("#f-submit");
  if (btn.disabled) return;  // creating a trip takes a few seconds; a second click made a duplicate
  btn.disabled = true;
  const tr = trip();
  try {
    if (dlgMode === "dates") {
      await api("/api/dates", { watch: tr.id, ...checkDates() });
      state.origin = ""; state.combo = "overall"; state.key = "f:0";
      $("#dlg-new").close(); return load(true);
    }
    if (!$("#f-to").value.trim() && tr) {  // only a new departure airport for the current trip
      if (!picked.from) throw new Error(t("dlg.pick_from"));
      await api("/api/compare", { watch: tr.id, code: picked.from.code });
      state.origin = picked.from.code;
      $("#dlg-new").close(); return load(true);
    }
    if (!picked.to) throw new Error(t("dlg.pick_to"));
    const to = picked.to;
    $("#f-msg").textContent = t("dlg.creating");
    const created = await api("/api/new", {
      to: to.kind === "place" ? to.place : (to.label.split(" – ")[1] || to.code), airport: to.code,
      from: picked.from ? picked.from.code : (tr ? tr.preferred_origin : ""),
      ...checkDates(),
      adults: Number($("#f-adults").value), guests: Number($("#f-guests").value),
      lat: to.kind === "place" ? to.lat : null, lon: to.kind === "place" ? to.lon : null,
    });
    state.trip = created.id; state.origin = ""; state.combo = "overall"; state.key = "f:0";
    $("#dlg-new").close();
    load(true);
  } catch (e) { $("#f-msg").textContent = e.message; } finally { btn.disabled = false; }
});

// --- settings ----------------------------------------------------------------------------------
suggestField($("#s-origin"), "from", "origin", (s) => s.code);
$("#btn-settings").onclick = async () => {
  const s = await api("/api/settings");
  $("#s-language").value = s.language;
  $("#s-currency").innerHTML = s.currencies.map((c) => `<option>${esc(c)}</option>`).join("");
  $("#s-currency").value = s.currency;
  $("#s-times").value = s.search_times.join(", ");
  $("#s-times").disabled = s.scheduler === "systemd";
  $("#s-times-hint").textContent = s.scheduler === "systemd" ? t("set.times_systemd") : t("set.times_hint");
  $("#s-origin").value = s.default_origin;
  $("#s-drop").value = s.notify_drop_pct;
  $("#s-notify").checked = s.notify;
  $("#s-autostart").checked = s.autostart;
  $("#s-autostart-row").hidden = !s.autostart_supported;
  $("#s-msg").textContent = "";
  $("#dlg-settings").showModal();
};
$("#s-cancel").onclick = () => $("#dlg-settings").close();
$("#s-advanced").onclick = (ev) => { ev.preventDefault(); api("/api/config", {}); };
$("#form-settings").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    await api("/api/settings", {
      language: $("#s-language").value, currency: $("#s-currency").value,
      search_times: $("#s-times").value.split(/[,\s]+/).filter(Boolean),
      default_origin: $("#s-origin").value.trim().toUpperCase(),
      notify_drop_pct: Number($("#s-drop").value), notify: $("#s-notify").checked, autostart: $("#s-autostart").checked,
    });
    location.reload();  // new language/currency everywhere
  } catch (e) { $("#s-msg").textContent = e.message; }
});

// --- update notice -----------------------------------------------------------------------------
async function checkUpdate() {
  try {
    const u = await api("/api/update");
    const el = $("#update");
    el.hidden = !u.available;
    if (u.available) { el.textContent = t("app.update", { version: u.version }); el.onclick = () => api("/api/open", { url: u.url }); }
  } catch (e) { /* offline */ }
}

(async () => {
  readHash();
  await loadI18n();
  try {
    const th = await api("/api/theme");
    const map = { background: "--bg", dark_background: "--bg2", lighter_background: "--bg3", foreground: "--fg",
                  light_foreground: "--fg2", muted: "--muted", accent: "--accent", selection: "--sel" };
    if (th.background) {
      document.documentElement.dataset.theme = "omarchy";
      for (const [k, v] of Object.entries(map)) if (th[k]) document.documentElement.style.setProperty(v, th[k]);
      const bg = th.background.replace("#", "");
      const lum = (0.299 * parseInt(bg.slice(0, 2), 16) + 0.587 * parseInt(bg.slice(2, 4), 16) + 0.114 * parseInt(bg.slice(4, 6), 16)) / 255;
      document.documentElement.style.colorScheme = lum > 0.5 ? "light" : "dark";
    }
  } catch (e) { /* keep fallback colors */ }
  await load(true);
  await pollUi();
  checkUpdate();
  setInterval(() => load(false), 4000);
  setInterval(pollUi, 1500);
  setInterval(async () => { await loadI18n(); load(true); }, 30 * 60 * 1000);  // fresh exchange rate
})();
