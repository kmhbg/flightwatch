# Flightwatch

Daglig flygprisbevakning: widget i Omarchy-baren (`nille.flightwatch`) på Linux, app med ikon i
aktivitetsfältet/menyraden på Windows och macOS. Svenska och engelska (följer systemets språk), valfri
visningsvaluta.

Hittar billigaste kombinationen **flyg + boende (totalpris)** inom ett flexibelt datumfönster,
redovisar en referensresa separat, jämför paketresor och andra svenska avreseorter, sparar
prishistorik och notifierar (skrivbord + markering i baren) när priset blir bra eller sjunker.

## Användning

```sh
flightwatch run            # full körning (alla källor och avreseorter, ~10 min)
flightwatch run --quick    # bara API-källor (~1 min, ingen webbläsare)
flightwatch status         # läsbar sammanfattning (--json för rådata)
flightwatch origin set ARN # byt förstahandsflygplats
flightwatch origin toggle GOT  # jämför GOT av/på
flightwatch history        # bästa pris per körning
flightwatch config         # sökväg till konfigurationen
flightwatch ack            # markera notiser som lästa
flightwatch new --to "Sitges, Spanien" --depart 2027-05-01 --return 2027-05-08 [--flex 1]
                           # ny resa: närmaste flygplatser (BCN, REU, GRO) och boende i orten letas fram
flightwatch dates ID --depart 2027-03-10 --return 2027-03-24 [--flex 2]
                           # flytta en resa till nya datum (flex: standard automatiskt)
flightwatch suggest Sitges # förslag till sökfälten (JSON)
flightwatch select ID | remove ID | trips
flightwatch app            # skrivbordsappen (Windows/macOS; fönster, ikon, schemalagda sökningar)
flightwatch doctor         # kontrollera mappar, språk, valuta och webbläsaren
flightwatch run --watch ID --origin ARN   # sök en resa från en viss flygplats (fyller cachen)
```

Widgeten: klick = panel, mittenklick = sök nu. I panelen: flygplatsknapparna visar sparade priser direkt
(cache per avreseort, ingen ny sökning), högerklick tar bort en jämförelseflygplats; 󰍉 öppnar sökfälten
Från/Till med förslag (kod, namn eller ort utan flygplats); resknapparna byter resa, högerklick gör den
till standardresa i baren; klick på ett pris öppnar bokningen. Esc stänger, r söker.

Appen (󰏌 i panelen): "＋ Ny resa" tar Från/Till, avresa, hemresa och flexibilitet (automatisk, exakt eller
±1–3 dagar) och visar direkt vilket datumfönster som söks. "📅 Datum" flyttar vald resa till nya datum,
så flera resor kan planeras och bevakas samtidigt.

## Windows och macOS

`flightwatch app` är en egen process i stället för systemd: webbservern, ett appfönster (pywebview:
WebView2 på Windows, WKWebView på macOS), en ikon i aktivitetsfältet/menyraden (standardresans pris,
Öppna, Sök nu, Avsluta), schemalagda sökningar vid `search_times` (en missad sökning körs ikapp en gång om
den är högst 12 h gammal) och notiser. Stängt fönster = appen fortsätter i ikonen. Autostart vid inloggning:
Windows `HKCU\…\Run`, macOS LaunchAgent `se.flightwatch.app`. Startas den en gång till visas fönstret.

Sidbaserade källor kör datorns Chrome/Edge (Windows: Edge finns alltid); saknas båda laddas Playwrights
headless-Chromium ner en gång (≈280 MB) till cache-mappen. Mappar: `platformdirs` – Linux som förut,
Windows `%LOCALAPPDATA%\Flightwatch`, macOS `~/Library/Application Support/Flightwatch`.
`flightwatch doctor` visar mappar, språk, valuta och testar webbläsaren.

Installerare: `.github/workflows/release.yml` bygger med PyInstaller (`packaging/flightwatch.spec`) på
GitHub Actions – Windows-installerare med Inno Setup (per användare, ingen admin), macOS `.dmg` för arm64
och x86_64. Tagg `v*` → release. macOS-signering/notarisering körs bara om Apple-hemligheterna finns (se
filhuvudet); annars öppnas appen första gången med högerklick → Öppna. Windows-installeraren är osignerad
(SmartScreen: "Mer info → Kör ändå"). Lokalt: `pip install ".[gui,build]" && python packaging/make_icons.py
&& pyinstaller packaging/flightwatch.spec`.

## Språk och valuta

Text i appen, notiser och CLI kommer från `src/flightwatch/i18n/{sv,en}.json` (samma nycklar, testas i
`tests/`). Språk: `FLIGHTWATCH_LANG`, annars `general.language` (`auto`/`sv`/`en`), annars systemets språk,
annars engelska. Valuta (`general.currency`) påverkar bara visningen: källorna söks och historiken sparas i
SEK och räknas om med ECB:s dagskurs (frankfurter.dev, cache ett dygn). Båda ändras i appen (⚙).
Text från en sökning (bagage, villkor, notiser) skrivs på det språk som gällde när sökningen kördes.

## Konfiguration

`~/.config/flightwatch/config.toml` (skapas med kommentarer första gången, utan resor; `[general]` ändras
enklast i appen under ⚙). Där finns datumfönster,
referensdatum, tröskelvärden, bagage (antal + uppskattade avgifter per flygbolag), boende
(gäster, krav som pool/AC, minsta betyg, max avstånd, reservpris per vecka), källor och avreseorter.

## Källor

| Källa | Metod | Bagage |
|---|---|---|
| momondo | resultatsidan i headless Chromium, läser `flights/poll` (kräver sidans csrf, anropas inte direkt) | per biljett: inkluderade väskor; flaggar flygbolagets egen försäljning |
| Qatar Airways | bokningssidan i headless Chromium, läser `flight-offers` (Akamai, anropas inte direkt); DKK→SEK via ECB (frankfurter.dev) | biljettyp med kg-bagage |
| Google Flights bokningsalternativ | väljer utresa + billigaste hemresa och läser "Boka hos …" | flygbolagets egna priser/biljettnivåer |
| Kiwi.com | publik GraphQL (`api.skypicker.com/umbrella/v2/graphql`), ingen inloggning | priset inkl. begärda väskor; prismatris för hela fönstret |
| flygcity.se | sitt eget formulärflöde (CSRF + session) → `capi/SearchChannel` | "Endast inkl. bagage", vikt per resultat |
| Google Flights | headless Chromium, läser resultatlistans aria-etiketter (som google-flights-skillen) | ingen bagagedata → uppskattas från konfigurationen |
| Ving (flyg) | `independentweb.nltg.com/api/proxy` GET | 1 väska ingår enligt Ving |
| Apollo (paket) | headless Chromium + klick på Sök (BFF ligger bakom Cloudflare, anropas inte direkt) | paket inkl. hotell |
| Sembo (flyg + hotell) | GraphQL över websocket (`smart-search.sembo.com/graphql`, graphql-transport-ws), ingen inloggning | bagage per flyg från svaret |
| Sunweb (paket) | `sunweb.se/api/sitecore/SearchApi/GetSearchResponse` GET; orter nära boendet via stadsfiltrets koordinater (bara Medelhavet, Kanarieöarna m.m.) | bara handbagage – väska uppskattas |
| Airbnb | serverrenderad söksida (`data-deferred-state-0`), endast Gästfavorit | – |
| Booking.com (hotell) | söksidan i headless Chromium (AWS WAF-kontroll), Apollo-cachen i `data-capla-store-data`; egna filter för pool/AC/betyg | – |
| Hotels.com (hotell) | söksidan i headless Chromium, läser `graphql` `PropertyListingQuery` | – |
| Sembo (hotell) | samma websocket som ovan; namn/betyg från `content-hc.sembo.com/Hotels/GetHotels` | – |

Boendet är det billigaste som uppfyller kraven av Airbnb (hela boendet) och hotell (rum för alla gäster,
två per rum, betyg ≥ `hotel_min_rating`, inga sovsalar). Panelen/appen visar billigast per källa.

Överhoppat (blockerar eller avvisar automatiserade anrop): TUI, Turkish Airlines egen sajt, Norwegian (403),
Booking.com flyg (`flights.booking.com/api` svarar 403 med botutmaning). Hotels.com säljer inte flyg i Sverige.
Sembos djuplänk öppnar hotellvalet för rätt datum – flyget läggs till i Sembos planerare.
Emirates/Etihad/SAS laddar men är inte inbyggda – deras priser kommer redan via Google och momondo.
Orter: Photon (komoot) för förslag, Nominatim för geokodning vid ny resa, OurAirports för flygplatser.
Inga captchas, inloggningar eller rate limits kringgås. Två körningar per dag är standard.

## Drift

- `systemd --user`: `flightwatch.timer` (07:30 och 19:30, `Persistent=true`) → `flightwatch.service`
  (≈10 min för tre avreseorter). Widgetens egna sökningar körs som tillfälliga `systemd-run`-enheter.
- Status till widgeten: `~/.local/state/flightwatch/status.json`
- Historik: `~/.local/share/flightwatch/history.db` (SQLite: runs, offers, matrix, stays)
- Loggar: `journalctl --user -u flightwatch`

Installera om CLI:t efter ändringar i beroenden: `uv tool install --editable --force ~/Work/flight-watch`.
Tester: `uv run pytest -q tests`.
