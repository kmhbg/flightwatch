#!/usr/bin/env bash
# Helper for the Flightwatch bar widget; the work is done by the flightwatch CLI (~/Work/flight-watch).
# Searches run as transient systemd user units so they survive shell reloads.
#   fw.sh run                         full search, all trips (same as the timer)
#   fw.sh search WATCH [ORIGIN]       API-only search of one trip, optionally one departure airport
#   fw.sh suggest TEXT from|to        suggestions for the From/To fields (JSON on stdout)
#   fw.sh new ARGS...                 create a trip (flightwatch new ARGS), then search it
#   fw.sh compare WATCH IATA          add/remove a compared departure airport
#   fw.sh select|remove WATCH         default trip in the bar / delete a trip
#   fw.sh ack | open URL | config
#   fw.sh app [NAV]                   open/focus the Flightwatch app window on an option (w=..&o=..&c=..&k=..)
export PATH="$HOME/.local/bin:$PATH"
bg() { systemd-run --user --no-block --collect --quiet --unit="flightwatch-$1-$(date +%s%N)" "${@:2}"; }
case "$1" in
  run)     systemctl --user start --no-block flightwatch.service ;;
  search)  bg search "$HOME/.local/bin/flightwatch" run --quick --watch "$2" ${3:+--origin "$3"} ;;
  suggest) flightwatch suggest "$2" --kind "${3:-to}" 2>/dev/null || echo '[]' ;;
  new)     shift; out=$(flightwatch new "$@") || exit 1; echo "$out"
           id=$(sed -n 's/^{"id": "\([^"]*\)".*/\1/p' <<<"$out"); [ -n "$id" ] && bg search "$HOME/.local/bin/flightwatch" run --quick --watch "$id" ;;
  compare) if flightwatch origin toggle "$3" --watch "$2" | grep -q "jämför.*$3"; then
             bg search "$HOME/.local/bin/flightwatch" run --quick --watch "$2" --origin "$3"; fi ;;
  select)  flightwatch select "$2" ;;
  remove)  flightwatch remove "$2" ;;
  ack)     flightwatch ack ;;
  open)    setsid -f xdg-open "$2" >/dev/null 2>&1 ;;
  config)  setsid -f omarchy launch editor "$(flightwatch config)" >/dev/null 2>&1 ;;
  app)     systemctl --user start flightwatch-web.service
           nav="${2:-}"
           for _ in 1 2 3 4 5 6 7 8 9 10; do curl -s -o /dev/null http://127.0.0.1:8765/api/ui && break; sleep 0.3; done
           curl -s -o /dev/null -X POST -H 'x-flightwatch: 1' -H 'content-type: application/json' \
             --data "{\"nav\": \"$nav\"}" http://127.0.0.1:8765/api/ui
           setsid -f omarchy launch or focus webapp 'chrome-127\.0\.0\.1__' "http://127.0.0.1:8765/#$nav" >/dev/null 2>&1 ;;
esac
# fw.sh panel [toggle|close] – open/close the bar panel (for keybindings and testing)
[ "$1" = panel ] && printf '%s %s\n' "${2:-toggle}" "$(date +%s%N)" > "$HOME/.local/state/flightwatch/ui-cmd"
