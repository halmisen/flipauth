#!/usr/bin/env bash
set -euo pipefail

# Offline coverage for the Claude quota cache and the cached-quota block that
# `status` prints. Every network call goes to a local stub; the fixture tokens
# below are obviously fake and must never appear in output or in the cache.

BIN_DIR="${FLIPAUTH_BIN_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TMP="$(mktemp -d)"
STUB="$TMP/stub"; mkdir -p "$STUB"
cleanup() { [[ -n "${STUB_PID:-}" ]] && kill "$STUB_PID" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT

fails=0
check() { local desc="$1"; shift; if "$@"; then printf 'ok   - %s\n' "$desc"; else printf 'FAIL - %s\n' "$desc"; fails=$((fails+1)); fi; }
mode_is() { [[ "$(stat -c '%a' "$1")" == "$2" ]]; }
outputs() { printf '%s' "$1" | grep -q "$2"; }
lacks() { ! printf '%s' "$1" | grep -q "$2"; }

TOKEN_A="fixture-token-alpha-DO-NOT-LEAK"
TOKEN_B="fixture-token-beta-DO-NOT-LEAK"

# ---------- local usage-endpoint stub ----------
PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
cat > "$STUB/serve.py" <<'PY'
import http.server, pathlib, sys
root = pathlib.Path(sys.argv[1]); port = int(sys.argv[2])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        with (root / "requests.log").open("a") as fh:
            fh.write(self.path + "\n")
        code = int((root / "code").read_text().strip())
        body = (root / "body.json").read_bytes()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
PY

# mk_body <5h util> <5h reset offset secs> <7d util> <7d reset offset secs>
mk_body() {
  python3 - "$STUB/body.json" "$@" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
path = sys.argv[1]
def iso(off): return (datetime.now(timezone.utc) + timedelta(seconds=int(off))).isoformat()
payload = {"five_hour": {"utilization": float(sys.argv[2]), "resets_at": iso(sys.argv[3])},
           "seven_day": {"utilization": float(sys.argv[4]), "resets_at": iso(sys.argv[5])}}
with open(path, "w") as fh: fh.write(json.dumps(payload))
PY
}

requests_seen() { [[ -f "$STUB/requests.log" ]] && wc -l < "$STUB/requests.log" || echo 0; }

printf '200' > "$STUB/code"
mk_body 1 12000 14 350000
: > "$STUB/requests.log"
python3 "$STUB/serve.py" "$STUB" "$PORT" &
STUB_PID=$!
for _ in $(seq 1 50); do
  python3 -c "import socket,sys;s=socket.socket();sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)" && break
  sleep 0.1
done

export CLAUDE_SWITCH_API_BASE="http://127.0.0.1:$PORT"
CL="$TMP/claude"; mkdir -p "$CL"
export CLAUDE_SWITCH_CLAUDE_DIR="$CL"
CACHE="$CL/oauth-accounts/.quota-cache.json"

printf '{"claudeAiOauth":{"accessToken":"%s","subscriptionType":"pro","expiresAt":1779870689090}}' "$TOKEN_A" > "$CL/.credentials.json"
"$BIN_DIR/claude-switch" save alpha >/dev/null
printf '{"claudeAiOauth":{"accessToken":"%s","subscriptionType":"pro","expiresAt":1779870689090}}' "$TOKEN_B" > "$CL/.credentials.json"
"$BIN_DIR/claude-switch" save beta >/dev/null
# beta is now the active profile and owns the live credentials file.

# ---------- 1. a 200 response creates the cache with mode 600 ----------
"$BIN_DIR/claude-switch" quota alpha >/dev/null
check "200 response creates the quota cache" test -f "$CACHE"
check "quota cache mode 600" mode_is "$CACHE" 600
check "state dir still mode 700" mode_is "$CL/oauth-accounts" 700
check "cache records the queried profile" bash -c "python3 -c \"import json;d=json.load(open('$CACHE'));raise SystemExit(0 if 'alpha' in d['profiles'] else 1)\""

ALPHA_STAMP="$(python3 -c "import json;print(json.load(open('$CACHE'))['profiles']['alpha']['fetched_at'])")"

# ---------- 2. a single-profile query merges instead of replacing ----------
"$BIN_DIR/claude-switch" quota beta >/dev/null
check "querying beta keeps alpha's cached entry" bash -c "python3 -c \"import json;d=json.load(open('$CACHE'))['profiles'];raise SystemExit(0 if {'alpha','beta'} <= set(d) else 1)\""
check "cache marks the active profile's sample as live" bash -c "python3 -c \"import json;d=json.load(open('$CACHE'))['profiles'];raise SystemExit(0 if d['beta']['source']=='live' and d['alpha']['source']=='snapshot' else 1)\""

# ---------- 3. failures never overwrite the last good sample ----------
printf '401' > "$STUB/code"
"$BIN_DIR/claude-switch" quota alpha >/dev/null || true
check "401 leaves the previous alpha sample intact" bash -c "test \"\$(python3 -c \"import json;print(json.load(open('$CACHE'))['profiles']['alpha']['fetched_at'])\")\" = '$ALPHA_STAMP'"
printf '429' > "$STUB/code"
"$BIN_DIR/claude-switch" quota alpha >/dev/null || true
check "429 leaves the previous alpha sample intact" bash -c "test \"\$(python3 -c \"import json;print(json.load(open('$CACHE'))['profiles']['alpha']['fetched_at'])\")\" = '$ALPHA_STAMP'"
kill "$STUB_PID" 2>/dev/null; wait "$STUB_PID" 2>/dev/null || true
"$BIN_DIR/claude-switch" quota alpha >/dev/null 2>&1 || true
check "connection failure leaves the cache intact" bash -c "test \"\$(python3 -c \"import json;print(json.load(open('$CACHE'))['profiles']['alpha']['fetched_at'])\")\" = '$ALPHA_STAMP'"

# ---------- 4. status is offline ----------
BEFORE="$(requests_seen)"
STATUS="$("$BIN_DIR/claude-switch" status)"
check "status issues no request to the usage endpoint" test "$(requests_seen)" = "$BEFORE"

# ---------- 5. status renders cached percentages, resets and age ----------
check "status keeps the active profile line" outputs "$STATUS" '^Active profile: beta$'
check "status keeps the saved profiles line" outputs "$STATUS" '^Saved profiles: alpha beta$'
check "status labels the block as a cached snapshot" outputs "$STATUS" 'Cached quota'
check "status marks the data as not live" outputs "$STATUS" 'not live'
check "status shows the 5h value as a lower bound" outputs "$STATUS" '≥1%'
check "status shows the 7d value as a lower bound" outputs "$STATUS" '≥14%'
check "status shows a reset countdown" outputs "$STATUS" 'in [0-9]'
check "status shows a fresh sample as just now" outputs "$STATUS" 'just now'
check "status marks the active profile" outputs "$STATUS" '^\* beta'

# an older sample reports its age rather than pretending to be fresh
python3 - "$CACHE" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
path = sys.argv[1]
cache = json.load(open(path))
cache["profiles"]["alpha"]["fetched_at"] = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(timespec="seconds")
with open(path, "w") as fh: json.dump(cache, fh)
PY
AGED="$("$BIN_DIR/claude-switch" status)"
check "status reports the age of an older sample" bash -c "printf '%s' \"\$0\" | grep '^  alpha' | grep -q '6h[0-9][0-9]m ago'" "$AGED"

# ---------- 6. a window whose reset has passed shows unknown, not a stale % ----------
python3 "$STUB/serve.py" "$STUB" "$PORT" &
STUB_PID=$!
for _ in $(seq 1 50); do
  python3 -c "import socket,sys;s=socket.socket();sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)" && break
  sleep 0.1
done
printf '200' > "$STUB/code"
mk_body 77 -5 91 350000
"$BIN_DIR/claude-switch" quota alpha >/dev/null
STATUS="$("$BIN_DIR/claude-switch" status)"
check "expired 5h window reports unknown" bash -c "printf '%s' \"\$0\" | grep '^  alpha' | grep -q 'unknown'" "$STATUS"
check "expired 5h window hides the stale percentage" bash -c "! printf '%s' \"\$0\" | grep '^  alpha' | grep -q '77'" "$STATUS"
check "still-valid 7d window keeps its value" bash -c "printf '%s' \"\$0\" | grep '^  alpha' | grep -q '≥91%'" "$STATUS"

# ---------- status stays a well-behaved filter when its reader closes early ----------
PIPE_ERR="$("$BIN_DIR/claude-switch" status 2>&1 >/dev/null | head -c 4000)"
check "status writes nothing to stderr" test -z "$PIPE_ERR"
PIPE_ERR="$({ "$BIN_DIR/claude-switch" status | grep -q 'Saved profiles'; } 2>&1)"
check "status piped into grep -q does not traceback" test -z "$PIPE_ERR"
check "status piped into grep -q still succeeds" bash -c "\"$BIN_DIR/claude-switch\" status | grep -q 'Saved profiles: alpha beta'"

# ---------- 7. a corrupt cache degrades without breaking status ----------
cp "$CACHE" "$TMP/cache.bak"
printf 'not json at all' > "$CACHE"
STATUS_BAD="$("$BIN_DIR/claude-switch" status)"
check "corrupt cache still prints the active profile" outputs "$STATUS_BAD" '^Active profile: beta$'
check "corrupt cache still prints saved profiles" outputs "$STATUS_BAD" '^Saved profiles: alpha beta$'
check "corrupt cache explains the missing quota block" outputs "$STATUS_BAD" 'Cached quota: unavailable'
check "corrupt cache does not break save" bash -c "\"$BIN_DIR/claude-switch\" save alpha >/dev/null"
check "corrupt cache does not break activate" bash -c "\"$BIN_DIR/claude-switch\" beta >/dev/null"
check "corrupt cache does not break doctor" bash -c "\"$BIN_DIR/claude-switch\" doctor >/dev/null"
cp "$TMP/cache.bak" "$CACHE"

# ---------- absent cache degrades with a hint, not a crash ----------
mv "$CACHE" "$TMP/cache.away"
STATUS_NONE="$("$BIN_DIR/claude-switch" status)"
check "missing cache still prints saved profiles" outputs "$STATUS_NONE" '^Saved profiles: alpha beta$'
check "missing cache hints at the quota command" outputs "$STATUS_NONE" 'Cached quota: no samples yet'
mv "$TMP/cache.away" "$CACHE"

# ---------- 8. neither output nor cache leaks a token ----------
QUOTA_OUT="$("$BIN_DIR/claude-switch" quota 2>&1)"
STATUS="$("$BIN_DIR/claude-switch" status)"
check "quota output does not leak the alpha token" lacks "$QUOTA_OUT" "$TOKEN_A"
check "quota output does not leak the beta token" lacks "$QUOTA_OUT" "$TOKEN_B"
check "status output does not leak the alpha token" lacks "$STATUS" "$TOKEN_A"
check "status output does not leak the beta token" lacks "$STATUS" "$TOKEN_B"
check "cache does not leak the alpha token" bash -c "! grep -q '$TOKEN_A' '$CACHE'"
check "cache does not leak the beta token" bash -c "! grep -q '$TOKEN_B' '$CACHE'"
check "cache does not store an Authorization header" bash -c "! grep -qi 'authorization\|bearer\|accesstoken' '$CACHE'"

# ---------- 9. Codex status gains nothing ----------
CX="$TMP/codex"; mkdir -p "$CX"
export CODEX_SWITCH_CODEX_DIR="$CX"
printf '%s' '{"auth_mode":"chatgpt","tokens":{"access_token":"a.b.c"}}' > "$CX/auth.json"
"$BIN_DIR/codex-switch" save red >/dev/null
CODEX_STATUS="$("$BIN_DIR/codex-switch" status)"
check "codex status keeps its two lines" outputs "$CODEX_STATUS" '^Saved profiles: red$'
check "codex status shows no cached quota block" lacks "$CODEX_STATUS" 'Cached quota'
check "codex quota is still rejected" bash -c "! \"$BIN_DIR/codex-switch\" quota 2>/dev/null"

# ---------- 10. a profile with no sample is listed, not dropped ----------
printf '{"claudeAiOauth":{"accessToken":"fixture-token-gamma-DO-NOT-LEAK"}}' > "$CL/.credentials.json"
"$BIN_DIR/claude-switch" save gamma >/dev/null
STATUS="$("$BIN_DIR/claude-switch" status)"
check "uncached profile still appears in the block" bash -c "printf '%s' \"\$0\" | grep -q 'gamma .*no sample'" "$STATUS"

echo "----"
if [[ "$fails" -gt 0 ]]; then echo "$fails check(s) failed"; exit 1; fi
echo "all claude-quota-cache checks passed"
