#!/bin/bash
# Smoke-test a built CodeSnap.app: start it against a throwaway data folder and call the endpoints that depend on files bundled
# into the app (end-of-life data, the Word template, the PDF and diagram builders), so a packaging mistake shows up here and not
# on a colleague's Mac. Usage:  packaging/smoke_test.command [path/to/CodeSnap.app]   (default: dist/CodeSnap.app)
cd "$(dirname "$0")/.." || exit 1
APP="${1:-dist/CodeSnap.app}"
BIN="$APP/Contents/MacOS/CodeSnap"
[ -x "$BIN" ] || { echo "No built app at $APP — run packaging/build_app.command first."; exit 1; }

WORK="$(mktemp -d)"
trap 'kill $PID 2>/dev/null; rm -rf "$WORK"' EXIT
env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN HOME="$WORK/home" CODESNAP_HOME="$WORK/data" CODESNAP_PROGRAMS="$WORK/programs" \
  "$BIN" --browser > "$WORK/app.log" 2>&1 &
PID=$!
B=http://127.0.0.1:8000
for i in $(seq 1 40); do curl -s -o /dev/null "$B/" && break; sleep 0.5; done
fail=0
check() {  # method path expected-status-pattern
  body="$4"; [ -z "$body" ] && body='{}'
  code=$(curl -s -o /dev/null -w "%{http_code}" -X "$1" -H 'Content-Type: application/json' -d "$body" "$B$2")
  if [[ "$code" =~ $3 ]]; then echo "ok   $code $1 $2"; else echo "FAIL $code $1 $2 (wanted $3)"; fail=1; fi
}
check GET  / '^200$'
check GET  /api/key/status '^200$'
check POST /api/programs '^200$' '{"name":"Smoke"}'
P=smoke
for path in "" /graph /technologies /findings /assessment /diagrams /health /coverage /report.docx /report.pdf /export; do
  check GET "/api/programs/$P$path" '^200$'
done
check GET  /api/programs/$P/diagrams/export/zip '^(200|404|409)$'
if grep -q "Traceback\|No such file or directory" "$WORK/app.log"; then
  echo "FAIL the app log reports errors:"; grep -m5 -B1 "Error" "$WORK/app.log" | cut -c1-220; fail=1
fi
[ "$fail" = 0 ] && echo "SMOKE TEST PASSED" || { echo "SMOKE TEST FAILED"; exit 1; }
