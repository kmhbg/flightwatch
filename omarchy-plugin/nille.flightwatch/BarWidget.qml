import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

BarWidget {
  id: root
  moduleName: "nille.flightwatch"

  // --- data from ~/.local/state/flightwatch/status.json ---------------------
  property var status: ({})
  property var trips: []
  property bool popupOpen: false
  property bool running: false
  property string updated: ""
  property string viewId: ""       // trip shown in the panel ("" = default trip)
  property string viewOrigin: ""   // departure airport shown ("" = the trip's preferred one)
  property string pendingView: ""  // trip just created from the panel; shown once it appears
  property bool formOpen: false

  readonly property string script: Qt.resolvedUrl("fw.sh").toString().replace("file://", "")
  readonly property string statusPath: Quickshell.env("HOME") + "/.local/state/flightwatch/status.json"
  readonly property var defaultTrip: trips.find(t => t.id === status.selected) || trips.find(t => t.active !== false) || trips[0] || null
  readonly property var watch: trips.find(t => t.id === viewId) || defaultTrip
  readonly property string shownOrigin: viewOrigin || (watch ? watch.preferred_origin : "")
  // Cached results per departure airport: switching airport is instant, no new search.
  readonly property var view: watch ? (((watch.by_origin || {})[shownOrigin]) || (shownOrigin === watch.preferred_origin ? watch : null)) : null
  readonly property var headline: defaultTrip ? defaultTrip.headline : null
  readonly property bool unread: !!(defaultTrip && defaultTrip.alert && defaultTrip.alert.unread)
  readonly property color dim: Qt.darker(bar.barForeground, 1.5)
  readonly property var catColors: ({ target: "#6cc070", good: "#a3d977", acceptable: "#e5a03c", expensive: "#e06c75" })
  readonly property var originList: {
    if (!watch) return []
    const list = [watch.preferred_origin].concat(watch.compare_origins || [])
    for (const k in (watch.by_origin || {})) if (list.indexOf(k) < 0) list.push(k)
    return list
  }

  function catColor(c) { return catColors[c] || bar.barForeground }
  function kr(n) {
    if (n === null || n === undefined) return "—"
    return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " kr"
  }
  function short(n) { return n ? (n / 1000).toFixed(1).replace(".", ",") + "k" : "" }
  function day(iso) {
    if (!iso) return ""
    const m = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
    const d = new Date(iso.substring(0, 10) + "T12:00:00")
    return d.getDate() + " " + m[d.getMonth()]
  }
  function hm(iso) { return iso && iso.length >= 16 ? iso.substring(11, 16) : "" }
  function dur(min) { return min ? Math.floor(min / 60) + "h " + (min % 60) + "m" : "" }
  function stopsText(n) { return n === 0 ? "direkt" : n === 1 ? "1 byte" : n + " byten" }
  function src(s) { return ({ kiwi: "Kiwi.com", flygcity: "flygcity", google: "Google Flights", ving: "Ving", apollo: "Apollo", airline: "flygbolaget direkt", momondo: "momondo", qatar: "Qatar Airways", sembo: "Sembo", sunweb: "Sunweb" })[s] || s }

  readonly property string icon: running ? "󰑓" : "󰀝"
  readonly property string label: headline ? short(headline.total) : ""

  implicitWidth: row.implicitWidth + Style.space(14)
  implicitHeight: barSize

  // KeyboardPanel calls owner.close() on outside click / Escape. Without this it would set its own
  // `open` and break the binding to popupOpen, leaving the panel stuck.
  function close() { popupOpen = false }

  // Replacing `trips` recreates every row in the panel, so only do it when the data really changed,
  // and never while the panel is open (it would eat clicks and reset scrolling); apply on close instead.
  property string lastText: ""
  property string pendingText: ""
  onPopupOpenChanged: {
    if (!popupOpen && pendingText) { const t = pendingText; pendingText = ""; apply(t) }
    if (!popupOpen) { formOpen = false; viewOrigin = "" }
  }

  function apply(text) {
    if (!text || text === lastText) return
    let d
    try { d = JSON.parse(text) } catch (e) { return }
    // Keep the optimistic spinner until the run has actually started and finished.
    if (d.running || d.updated !== root.updated) root.running = !!d.running
    if (popupOpen && root.trips.length) { pendingText = text; return }
    lastText = text
    root.status = d
    root.updated = d.updated || ""
    root.trips = d.watches || []
    if (pendingView && trips.find(t => t.id === pendingView)) { viewId = pendingView; pendingView = "" }
  }

  function act(args, onOut) {
    if (["run", "search", "compare", "new"].indexOf(args[0]) >= 0) root.running = true
    const p = actionComp.createObject(root, { command: [script].concat(args), handler: onOut || null })
    p.running = true
  }
  function openUrl(u) { if (u) act(["open", u]) }
  // Show an option in the app window: c = overall|reference|same_depart, k = f:0 | t:0 | s | p:0.
  function openApp(c, k) {
    const nav = watch ? "w=" + watch.id + "&o=" + shownOrigin + "&c=" + (c || "overall") + "&k=" + (k || "f:0") : ""
    act(["app", nav])
    popupOpen = false
  }

  Component {
    id: actionComp
    Process {
      property var handler: null
      stdout: StdioCollector { id: out; waitForEnd: true }
      onExited: function(exitCode) {
        if (exitCode !== 0 && root.running) root.running = false
        if (handler) handler(out.text, exitCode)
        statusFile.reload()
        destroy()
      }
    }
  }

  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.apply(text())
  }

  // External control: `fw.sh panel` writes "toggle <time>" here (usable from a Hyprland keybinding).
  FileView {
    id: uiCmd
    path: Quickshell.env("HOME") + "/.local/state/flightwatch/ui-cmd"
    watchChanges: true
    printErrors: false
    property string last: ""
    onFileChanged: reload()
    onLoaded: {
      const t = text().trim()
      if (!t || t === last) return
      const first = last === ""
      last = t
      if (first) return  // ignore whatever was there when the widget loaded
      if (t.startsWith("toggle")) root.popupOpen = !root.popupOpen
      else if (t.startsWith("close")) root.popupOpen = false
    }
  }

  Timer {  // atomic rename can slip past the watcher; poll as a fallback
    interval: root.running ? 15000 : 300000
    running: true
    repeat: true
    onTriggered: statusFile.reload()
  }

  // --- bar pill ---------------------------------------------------------------
  Row {
    id: row
    anchors.centerIn: parent
    spacing: Style.space(5)

    Text {
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: root.icon
      color: root.headline ? root.catColor(root.headline.category) : root.dim
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.body
      RotationAnimation on rotation { running: root.running; from: 0; to: 360; duration: 1400; loops: Animation.Infinite }
    }
    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.label !== "" && !root.bar.vertical
      textFormat: Text.PlainText
      text: root.label
      color: root.bar.barForeground
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.body
    }
    Rectangle {  // unread alert dot
      anchors.verticalCenter: parent.verticalCenter
      visible: root.unread
      width: Style.space(7); height: width; radius: width / 2
      color: root.headline ? root.catColor(root.headline.category) : "#e5a03c"
    }
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
    onClicked: function(mouse) {
      if (mouse.button === Qt.MiddleButton) { root.act(["run"]); return }
      root.popupOpen = !root.popupOpen
      if (root.popupOpen && root.unread) root.act(["ack"])
    }
    onEntered: if (root.bar && !root.popupOpen) root.bar.showTooltip(root, !root.defaultTrip ? "Flightwatch — ingen data än" :
      root.defaultTrip.name + (root.headline
        ? "\nBilligast: " + root.day(root.headline.depart) + "–" + root.day(root.headline.return) + " från " + root.headline.origin +
          "\nFlyg " + root.kr(root.headline.total) + " (" + root.headline.label + ") · med boende " + root.kr(root.headline.with_stay)
        : "") + (root.unread ? "\n🔔 " + root.defaultTrip.alert.text : "") +
      "\nKlick: detaljer · Mittenklick: sök nu")
    onExited: if (root.bar) root.bar.hideTooltip(root)
  }

  // --- reusable pieces --------------------------------------------------------
  component Caption: Text {
    textFormat: Text.PlainText
    color: Qt.darker(root.bar.foreground, 1.5)
    font.family: root.bar.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }
  component Body: Text {
    textFormat: Text.PlainText
    color: root.bar.foreground
    font.family: root.bar.fontFamily
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  // Text field with suggestions while typing (fw.sh suggest → flightwatch suggest).
  component SuggestField: Column {
    id: sf
    property string kind: "to"
    property string placeholder: ""
    property var picked: null          // chosen suggestion object
    property var items: []
    property alias text: field.text
    readonly property bool editing: field.activeFocus
    width: parent ? parent.width : 0
    spacing: Style.space(2)

    function clear() { field.text = ""; picked = null; items = [] }

    TextField {
      id: field
      width: parent.width
      placeholderText: sf.placeholder
      foreground: root.bar.foreground
      font.family: root.bar.fontFamily
      onTextEdited: { sf.picked = null; debounce.restart() }
      Keys.onEscapePressed: root.close()
    }
    Timer {
      id: debounce
      interval: 350
      onTriggered: {
        const t = field.text.trim()
        if (t.length < 2) { sf.items = []; return }
        root.act(["suggest", t, sf.kind], function(out) {
          if (field.text.trim() !== t) return  // stale answer
          try { sf.items = JSON.parse(out) } catch (e) { sf.items = [] }
        })
      }
    }
    Repeater {
      model: sf.picked ? [] : sf.items
      Rectangle {
        required property var modelData
        width: sf.width
        height: sugCol.implicitHeight + Style.space(6)
        radius: Style.cornerRadius
        color: sugMouse.containsMouse ? Style.selectedFillFor(root.bar.foreground, ThemeColor.accent) : "transparent"
        Column {
          id: sugCol
          anchors.verticalCenter: parent.verticalCenter
          x: Style.space(6)
          width: parent.width - Style.space(12)
          Body { width: parent.width; text: (modelData.kind === "place" ? "󰍎 " : "󰀝 ") + modelData.label }
          Caption { width: parent.width; text: modelData.detail }
        }
        MouseArea {
          id: sugMouse
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: { sf.picked = modelData; field.text = modelData.label; sf.items = [] }
        }
      }
    }
  }

  // One date combination: best flight, cheaper 2-stop option, lodging, package comparison.
  component ComboCard: Column {
    id: card
    property var combo: null
    property string ckey: "overall"
    property string title: ""
    width: parent ? parent.width : 0
    spacing: Style.space(3)
    visible: !!combo

    readonly property var f: combo ? combo.best : null
    readonly property var two: combo ? combo.cheaper_two_stops : null
    readonly property var stay: combo ? combo.stay : null
    readonly property var pkg: combo ? combo.best_package : null

    PanelSectionHeader {
      width: parent.width
      foreground: root.bar.foreground
      fontFamily: root.bar.fontFamily
      text: card.title + (card.combo ? "  ·  " + root.day(card.combo.depart) + " – " + root.day(card.combo.return) + " (" + card.combo.days + " dagar)" : "")
    }

    Item {  // best flight, clickable
      width: parent.width
      height: flightCol.implicitHeight
      visible: !!card.f
      Column {
        id: flightCol
        width: parent.width
        Row {
          width: parent.width
          Body {
            width: parent.width - priceText.implicitWidth
            elide: Text.ElideRight
            wrapMode: Text.NoWrap
            text: card.f ? card.f.airlines.join(" / ") + " · " + root.stopsText(card.f.max_stops) + (card.f.out.duration_min ? " · " + root.dur(card.f.out.duration_min) : "") : ""
          }
          Text {
            id: priceText
            textFormat: Text.PlainText
            text: card.f ? root.kr(card.f.total) : ""
            color: card.f ? root.catColor(card.f.category) : root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
          }
        }
        Caption {
          width: parent.width
          text: card.f ? root.hm(card.f.out.depart) + " → " + root.day(card.f.out.arrive) + " " + root.hm(card.f.out.arrive) +
                (card.f.out.via.length ? " via " + card.f.out.via.join(", ") : "") +
                (card.f.back.depart ? "  ·  hem " + root.day(card.f.back.depart) + " " + root.hm(card.f.back.depart) : "") : ""
        }
        Caption {
          width: parent.width
          text: card.f ? root.kr(card.f.per_person) + "/person · biljett " + root.kr(card.f.ticket_total) +
                " + bagage " + root.kr(card.f.bag_cost) + (card.f.bag_cost_estimated ? " (uppsk.)" : "") +
                " · " + (card.f.booking_via || root.src(card.f.source)) + " · " + (card.f.bag_note || "") : ""
        }
        Caption {  // airline direct price / fare brands from Google's booking options
          width: parent.width
          visible: !!(card.f && card.f.booking_options && card.f.booking_options.length)
          text: card.f && card.f.booking_options ? "Bokningsalternativ: " + card.f.booking_options.slice(0, 4).map(b => b.who + (b.airline ? " (bolaget)" : "") + " " + root.kr(b.price)).join(" · ") : ""
        }
      }
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.openApp(card.ckey, "f:0")
      }
    }
    Caption {
      width: parent.width
      visible: !card.f
      text: "Inget flyg med högst ett byte hittades."
    }

    Caption {
      width: parent.width
      visible: !!card.two
      text: card.two ? "Billigare med 2 byten: " + root.kr(card.two.total) + " " + card.two.airlines.join("/") + " (" + root.src(card.two.source) + ") — " + card.two.conditions : ""
      MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.openApp(card.ckey, "t:0") }
    }

    Row {  // lodging
      width: parent.width
      visible: !!card.stay
      Body {
        width: parent.width - stayPrice.implicitWidth
        elide: Text.ElideRight
        wrapMode: Text.NoWrap
        text: card.stay ? "󰋜 " + ({ airbnb: "Airbnb", booking: "Booking.com", "hotels.com": "Hotels.com", sembo: "Sembo" }[card.stay.source] ? ({ airbnb: "Airbnb", booking: "Booking.com", "hotels.com": "Hotels.com", sembo: "Sembo" }[card.stay.source] + ": " + card.stay.name + (card.stay.source === "airbnb" ? " ★" + card.stay.rating : " " + card.stay.rating + "/10")) : card.stay.name) : ""
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.openApp(card.ckey, "s") }
      }
      Text {
        id: stayPrice
        textFormat: Text.PlainText
        text: card.stay ? root.kr(card.stay.total) : ""
        color: root.bar.foreground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
    }
    Caption {
      width: parent.width
      visible: !!card.stay
      text: card.stay ? card.stay.nights + " nätter, " + card.stay.guests + " gäster" + (card.stay.beds ? " · " + card.stay.beds : "") +
            (card.stay.source !== "fallback" ? " · " + card.stay.reviews + " omdömen · billigast av " + card.stay.matches + " (Airbnb + hotell) som uppfyller kraven (" + ((root.watch.stay_cfg || {}).require || []).join(", ") + ")" : " · " + (card.stay.note || "")) : ""
    }

    Row {
      width: parent.width
      visible: !!(card.combo && card.combo.flight_plus_stay)
      Body { width: parent.width - ownTotal.implicitWidth; text: "Flyg + boende totalt"; font.bold: true }
      Text {
        id: ownTotal
        textFormat: Text.PlainText
        text: card.combo ? root.kr(card.combo.flight_plus_stay) : ""
        color: root.bar.foreground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
      }
    }
    Caption {
      width: parent.width
      visible: !!card.pkg
      text: card.pkg ? "Paketresa " + root.src(card.pkg.source) + ": " + root.kr(card.pkg.total) + " — " + card.pkg.hotel +
            (card.combo.package_minus_own !== null ? (card.combo.package_minus_own > 0 ? " · eget upplägg " + root.kr(card.combo.package_minus_own) + " billigare" : " · paketet " + root.kr(-card.combo.package_minus_own) + " billigare") : "") : ""
      MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.openApp(card.ckey, "p:0") }
    }
  }

  // --- panel ------------------------------------------------------------------
  KeyboardPanel {
    id: panel
    anchorItem: root
    owner: root
    bar: root.bar
    open: root.popupOpen
    contentWidth: panel.fittedContentWidth(Style.space(480))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(840))
    focusTarget: keyCatcher

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: fromField.editing || toField.editing || dateFields.editing
      onCloseRequested: root.close()
      onTextKey: function(t) { if (t === "r" || t === "R") root.act(["run"]) }

      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: parent.width - Style.space(6)
          spacing: Style.space(10)

          // Header
          Row {
            width: parent.width
            spacing: Style.space(10)
            Text {
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: "󰀝"
              color: root.view && root.view.headline ? root.catColor(root.view.headline.category) : root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.displayLarge
            }
            Column {
              anchors.verticalCenter: parent.verticalCenter
              width: parent.width - Style.space(230)
              Text {
                width: parent.width
                elide: Text.ElideRight
                textFormat: Text.PlainText
                text: root.watch ? root.watch.name + " · " + root.watch.destination_name : "Flightwatch"
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.subtitle
                font.bold: true
              }
              Caption {
                width: parent.width
                text: root.watch
                  ? root.watch.adults + " vuxna · " + root.watch.bags + " incheckad väska/person · " +
                    (root.watch.reference_dates && root.watch.window.flex_days !== undefined && root.watch.window.flex_days !== null
                      ? root.day(root.watch.reference_dates.depart) + "–" + root.day(root.watch.reference_dates.return) + " ±" + root.watch.window.flex_days + " dagar"
                      : root.day(root.watch.window.earliest_depart) + "–" + root.day(root.watch.window.latest_return)) + ", " +
                    root.watch.window.min_days + "–" + root.watch.window.max_days + " dagar\n" +
                    (root.running ? "Söker nu…" : "Uppdaterad " + root.day((root.view || {}).updated || root.updated) + " " + root.hm((root.view || {}).updated || root.updated) + " · söker 07:30 och 19:30")
                  : "Ingen data än — tryck på sök."
              }
            }
            Row {
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(4)
              Button {
                iconText: "󰑓"
                iconSpinning: root.running
                foreground: root.bar.foreground
                tooltipText: "Sök nu (alla resor, alla källor)"
                onClicked: root.act(["run"])
              }
              Button {
                iconText: "󰏌"
                foreground: root.bar.foreground
                tooltipText: "Öppna appen (alla detaljer)"
                onClicked: root.openApp("overall", "f:0")
              }
              Button {
                iconText: "󰍉"
                selected: root.formOpen
                foreground: root.bar.foreground
                tooltipText: "Sök annan avreseort eller ny resa"
                onClicked: root.formOpen = !root.formOpen
              }
              Button {
                iconText: "󰒓"
                foreground: root.bar.foreground
                tooltipText: "Redigera bevakningar (mål, datum, bagage, boende …)"
                onClicked: { root.act(["config"]); root.popupOpen = false }
              }
            }
          }

          // Trips
          Flow {
            width: parent.width
            spacing: Style.space(6)
            visible: root.trips.length > 1
            Repeater {
              model: root.trips
              Button {
                required property var modelData
                readonly property bool isDefault: root.defaultTrip && root.defaultTrip.id === modelData.id
                text: modelData.name + (modelData.reference_dates ? " " + root.day(modelData.reference_dates.depart) : "") + (isDefault ? " ★" : "")
                tooltipText: (isDefault ? "Standardresa i baren" : "Högerklick: gör till standardresa i baren")
                foreground: root.bar.foreground
                bordered: true
                selected: root.watch && root.watch.id === modelData.id
                onClicked: { root.viewId = modelData.id; root.viewOrigin = "" }
                onRightClicked: root.act(["select", modelData.id])
              }
            }
          }

          // Search form: From/To with suggestions
          Column {
            width: parent.width
            spacing: Style.space(6)
            visible: root.formOpen

            PanelSeparator { foreground: root.bar.foreground }
            Caption { text: "FRÅN — flygplats (kod eller namn, t.ex. CPH eller Köpenhamn)" }
            SuggestField { id: fromField; kind: "from"; placeholder: "Från" }
            Caption { text: "TILL — flygplats eller ort (orter utan flygplats får närmaste flygplats, boendet söks i orten)" }
            SuggestField { id: toField; kind: "to"; placeholder: "Till (lämna tomt för att söka annan avreseort till " + (root.watch ? root.watch.name : "resan") + ")" }

            Column {
              id: dateFields
              width: parent.width
              spacing: Style.space(4)
              visible: !!toField.picked
              readonly property bool editing: earliest.activeFocus || latest.activeFocus || adults.activeFocus || guests.activeFocus
              Caption { text: "PLANERAD AVRESA · HEMRESA (ÅÅÅÅ-MM-DD) · VUXNA SOM FLYGER · GÄSTER I BOENDET\nFlexibilitet sätts automatiskt: ±2 dagar och högst 2 dagar kortare för långa resor, annars ±1." }
              Row {
                width: parent.width
                spacing: Style.space(4)
                TextField { id: earliest; width: parent.width * 0.34; placeholderText: "2027-05-10"; foreground: root.bar.foreground; font.family: root.bar.fontFamily }
                TextField { id: latest; width: parent.width * 0.34; placeholderText: "2027-05-17"; foreground: root.bar.foreground; font.family: root.bar.fontFamily }
                TextField {
                  id: adults
                  width: parent.width * 0.14
                  text: "2"
                  validator: IntValidator { bottom: 1; top: 9 }
                  foreground: root.bar.foreground
                  font.family: root.bar.fontFamily
                }
                TextField {
                  id: guests
                  width: parent.width * 0.14
                  text: "2"
                  validator: IntValidator { bottom: 1; top: 16 }
                  foreground: root.bar.foreground
                  font.family: root.bar.fontFamily
                }
              }
            }

            Row {
              spacing: Style.space(6)
              Button {
                visible: !!fromField.picked && !toField.picked && !!root.watch
                text: fromField.picked ? "Sök från " + fromField.picked.code + " till " + root.watch.name : ""
                bordered: true
                foreground: root.bar.foreground
                onClicked: {
                  const code = fromField.picked.code
                  if (root.originList.indexOf(code) >= 0) { root.viewOrigin = code }
                  else { root.act(["compare", root.watch.id, code]); formStatus.text = "Söker från " + code + " … (ca 1 min)" }
                  fromField.clear()
                }
              }
              Button {
                visible: !!toField.picked
                text: "Skapa resa och sök"
                bordered: true
                foreground: root.bar.foreground
                onClicked: {
                  const t = toField.picked
                  if (!/^\d{4}-\d{2}-\d{2}$/.test(earliest.text) || !/^\d{4}-\d{2}-\d{2}$/.test(latest.text)) {
                    formStatus.text = "Fyll i datum som ÅÅÅÅ-MM-DD."
                    return
                  }
                  const args = ["new", "--to", t.kind === "place" ? t.place : (t.label.split(" – ")[1] || t.code),
                                "--airport", t.code, "--from", fromField.picked ? fromField.picked.code : (root.watch ? root.watch.preferred_origin : "CPH"),
                                "--depart", earliest.text, "--return", latest.text,
                                "--adults", adults.text || "2", "--guests", guests.text || adults.text || "2"]
                  if (t.kind === "place") args.push("--lat", String(t.lat), "--lon", String(t.lon))
                  formStatus.text = "Skapar resa och söker … (ca 1–2 min)"
                  root.act(args, function(out, code) {
                    try { root.pendingView = JSON.parse(out.split("\n")[0]).id } catch (e) {}
                    formStatus.text = code === 0 ? "Resan är skapad – priserna visas när sökningen är klar." : "Kunde inte skapa resan."
                  })
                  toField.clear(); fromField.clear()
                }
              }
            }
            Caption { id: formStatus; width: parent.width; text: "" }
          }

          // Alert banner
          Rectangle {
            width: parent.width
            visible: !!(root.watch && root.watch.alert)
            height: visible ? alertText.implicitHeight + Style.space(12) : 0
            radius: Style.cornerRadius
            color: Qt.rgba(0.42, 0.75, 0.44, 0.15)
            Body {
              id: alertText
              anchors.centerIn: parent
              width: parent.width - Style.space(16)
              text: root.watch && root.watch.alert ? "🔔 " + root.watch.alert.text : ""
            }
          }

          // Departure airports (cached results, instant switch)
          PanelSeparator { foreground: root.bar.foreground }
          Caption { text: "AVRESEORT — klick visar sparade priser · högerklick tar bort från jämförelsen · ★ = förstahand" }
          Flow {
            width: parent.width
            spacing: Style.space(6)
            Repeater {
              model: root.originList
              Button {
                required property string modelData
                readonly property var cached: root.watch && root.watch.by_origin ? root.watch.by_origin[modelData] : null
                readonly property bool preferred: root.watch && root.watch.preferred_origin === modelData
                text: modelData + (preferred ? " ★" : "") + (cached && cached.headline ? "  " + root.short(cached.headline.total) : "  …")
                tooltipText: cached ? "Sparat " + root.day(cached.updated) + " " + root.hm(cached.updated) + (cached.sources ? " · källor: " + cached.sources.join(", ") : "") : "Inga sparade priser än"
                foreground: root.bar.foreground
                bordered: true
                selected: root.shownOrigin === modelData
                onClicked: root.viewOrigin = modelData
                onRightClicked: if (!preferred) root.act(["compare", root.watch.id, modelData])
              }
            }
          }

          // Headline for the shown airport
          Row {
            width: parent.width
            visible: !!(root.view && root.view.headline)
            Column {
              width: parent.width / 2
              Caption { text: "Bästa flygpris inkl. bagage" }
              Text {
                textFormat: Text.PlainText
                text: root.view && root.view.headline ? root.kr(root.view.headline.total) : ""
                color: root.view && root.view.headline ? root.catColor(root.view.headline.category) : root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.subtitle
                font.bold: true
              }
              Caption { text: root.view && root.view.headline ? root.view.headline.label + " · " + root.kr(root.view.headline.per_person) + "/person" : "" }
            }
            Column {
              width: parent.width / 2
              Caption { text: "Flyg + boende totalt" }
              Text {
                textFormat: Text.PlainText
                text: root.view && root.view.headline ? root.kr(root.view.headline.with_stay) : ""
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.subtitle
                font.bold: true
              }
              Caption {
                text: root.view && root.view.thresholds ? (root.view.thresholds.auto ? "Auto-mål ≤ " : "Mål ≤ ") + root.kr(root.view.thresholds.target) + " · bra ≤ " + root.kr(root.view.thresholds.good) : ""
              }
            }
          }
          Caption {
            width: parent.width
            visible: !root.view
            text: "Inga sparade priser för " + root.shownOrigin + " än. De hämtas vid nästa sökning."
          }

          PanelSeparator { foreground: root.bar.foreground; visible: !!(root.view && root.view.overall) }
          ComboCard { title: "BILLIGAST INKL. BOENDE"; combo: root.view ? root.view.overall : null }
          PanelSeparator { foreground: root.bar.foreground; visible: !!(root.view && root.view.reference) }
          ComboCard { title: "REFERENS"; ckey: "reference"; combo: root.view ? root.view.reference : null }
          PanelSeparator { foreground: root.bar.foreground; visible: !!(root.view && root.view.same_depart) }
          ComboCard { title: "SAMMA UTRESEDATUM"; ckey: "same_depart"; combo: root.view ? root.view.same_depart : null }

          // Airports side by side
          PanelSeparator { foreground: root.bar.foreground; visible: !!(root.watch && root.watch.origins && root.watch.origins.length > 1) }
          PanelSectionHeader {
            visible: !!(root.watch && root.watch.origins && root.watch.origins.length > 1)
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            text: "JÄMFÖR FLYGPLATSER  ·  referens / bästa datum / inkl. boende"
          }
          Repeater {
            model: root.watch && root.watch.origins && root.watch.origins.length > 1 ? root.watch.origins : []
            Item {
              required property var modelData
              width: column.width
              height: originRow.implicitHeight
              Row {
                id: originRow
                width: parent.width
                Body { width: parent.width * 0.4; text: modelData.code + " " + modelData.name + (modelData.preferred ? " ★" : ""); font.bold: modelData.code === root.shownOrigin }
                Body { width: parent.width * 0.2; horizontalAlignment: Text.AlignRight; text: modelData.reference ? root.kr(modelData.reference.total) : "—" }
                Body { width: parent.width * 0.2; horizontalAlignment: Text.AlignRight; text: modelData.best ? root.kr(modelData.best.total) : "—" }
                Body { width: parent.width * 0.2; horizontalAlignment: Text.AlignRight; text: modelData.with_stay ? root.kr(modelData.with_stay) : "—" }
              }
              MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.viewOrigin = modelData.code }
            }
          }

          // Alternative dates
          PanelSeparator { foreground: root.bar.foreground; visible: !!(root.view && root.view.alternatives && root.view.alternatives.length) }
          PanelSectionHeader {
            visible: !!(root.view && root.view.alternatives && root.view.alternatives.length)
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            text: "ALTERNATIVA DATUM  ·  flyg + boende (≈ uppskattat, ✓ verifierat)"
          }
          Repeater {
            model: root.view && root.view.alternatives ? root.view.alternatives.slice(0, 8) : []
            Row {
              required property var modelData
              width: column.width
              Body { width: parent.width * 0.55; text: root.day(modelData.depart) + " – " + root.day(modelData.return) + " (" + modelData.days + " d)" }
              Body {
                width: parent.width * 0.45
                horizontalAlignment: Text.AlignRight
                text: modelData.verified_total ? "✓ " + root.kr(modelData.verified_total) : "≈ " + root.kr(modelData.total_est)
                color: modelData.verified_total ? root.bar.foreground : Qt.darker(root.bar.foreground, 1.4)
              }
            }
          }

          // Errors
          Caption {
            width: parent.width
            visible: !!(root.watch && root.watch.errors && root.watch.errors.length)
            color: "#e5a03c"
            text: root.watch && root.watch.errors ? "⚠ " + root.watch.errors.join("\n⚠ ") : ""
          }
          Caption {
            width: parent.width
            text: "Klicka på ett alternativ för att se allt det innehåller i appen. Bagage märkt (uppsk.) är en uppskattning från konfigurationen. Esc stänger, r söker."
          }
        }
      }
    }
  }
}
