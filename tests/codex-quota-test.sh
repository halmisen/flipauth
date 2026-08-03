#!/usr/bin/env bash
set -euo pipefail

# Offline coverage for `codex quota` and the Codex half of the cached-quota block.
#
# The real path drives `codex app-server --stdio` over JSON-RPC. These tests replace the
# codex binary with a stub via CODEX_SWITCH_CODEX_BIN, which lets them assert the parts
# that actually matter and cannot be checked against a live account: that every profile
# is read from a throwaway CODEX_HOME, that saved snapshots are never mutated, and that
# a server-initiated token refresh is declined rather than answered.

BIN_DIR="${FLIPAUTH_BIN_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

fails=0
check() { local desc="$1"; shift; if "$@"; then printf 'ok   - %s\n' "$desc"; else printf 'FAIL - %s\n' "$desc"; fails=$((fails+1)); fi; }
mode_is() { [[ "$(stat -c '%a' "$1")" == "$2" ]]; }
outputs() { printf '%s' "$1" | grep -q "$2"; }
lacks() { ! printf '%s' "$1" | grep -q "$2"; }

TOKEN_W="fixture-codex-token-work-DO-NOT-LEAK"
TOKEN_A="fixture-codex-token-alt-DO-NOT-LEAK"

# ---------- stub app-server ----------
export STUB_DIR="$TMP/stub"; mkdir -p "$STUB_DIR"
cat > "$TMP/codex" <<'STUB'
#!/usr/bin/env python3
import json, os, pathlib, sys
stub = pathlib.Path(os.environ["STUB_DIR"])
mode = (stub / "mode").read_text().strip() if (stub / "mode").exists() else "ok"
home = pathlib.Path(os.environ.get("CODEX_HOME", ""))
auth = home / "auth.json"
with (stub / "calls.log").open("a") as fh:
    fh.write(json.dumps({"home": str(home),
                         "auth": auth.read_text().strip() if auth.exists() else None,
                         "auth_mode": oct(auth.stat().st_mode & 0o777) if auth.exists() else None,
                         "home_mode": oct(home.stat().st_mode & 0o777) if home.exists() else None}) + "\n")
def out(m): sys.stdout.write(json.dumps(m) + "\n"); sys.stdout.flush()
if mode == "hang":
    import time; time.sleep(600)
for line in sys.stdin:
    try: msg = json.loads(line)
    except Exception: continue
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        out({"jsonrpc": "2.0", "id": mid, "result": {"codexHome": str(home)}})
    elif method == "account/rateLimits/read":
        if mode == "401":
            out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32001, "message": "backend returned 401 Unauthorized"}})
        elif mode == "refresh":
            out({"jsonrpc": "2.0", "id": 9001, "method": "account/chatgptAuthTokens/refresh",
                 "params": {"reason": "unauthorized", "previousAccountId": None}})
            out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32001, "message": "backend returned 401 Unauthorized"}})
        else:
            out({"jsonrpc": "2.0", "id": mid, "result": json.loads((stub / "body.json").read_text())})
    elif method == "account/chatgptAuthTokens/refresh" and mid is None:
        pass
    elif mid is not None and "result" in msg:
        (stub / "refresh-ANSWERED").write_text("1")   # a client that refreshed: must not happen
    elif mid is not None and "error" in msg:
        (stub / "refresh-declined").write_text("1")
STUB
chmod +x "$TMP/codex"
export CODEX_SWITCH_CODEX_BIN="$TMP/codex"
export CODEX_SWITCH_QUOTA_TIMEOUT=15

# body <primary pct> <primary window mins> <primary reset offset> <secondary json|null>
body() {
  python3 - "$STUB_DIR/body.json" "$@" <<'PY'
import json, sys, time
now = int(time.time())
payload = {"rateLimits": {"limitId": "codex", "planType": "plus",
    "primary": {"usedPercent": int(sys.argv[2]), "windowDurationMins": int(sys.argv[3]),
                "resetsAt": now + int(sys.argv[4])},
    "secondary": json.loads(sys.argv[5])},
    "rateLimitResetCredits": {"availableCount": 1, "credits": [
        {"id": "c1", "resetType": "codexRateLimits", "status": "available",
         "grantedAt": now - 10, "expiresAt": now + 600000, "title": "Full reset"}]}}
with open(sys.argv[1], "w") as fh: fh.write(json.dumps(payload))
PY
}

printf 'ok' > "$STUB_DIR/mode"
body 73 10080 520000 null

CX="$TMP/codex-home"; mkdir -p "$CX"; export CODEX_SWITCH_CODEX_DIR="$CX"
STATE="$CX/oauth-accounts"; CACHE="$STATE/.quota-cache.json"
printf '{"auth_mode":"chatgpt","tokens":{"access_token":"%s"}}' "$TOKEN_W" > "$CX/auth.json"
"$BIN_DIR/codex-switch" save work >/dev/null
printf '{"auth_mode":"chatgpt","tokens":{"access_token":"%s"}}' "$TOKEN_A" > "$CX/auth.json"
"$BIN_DIR/codex-switch" save alt >/dev/null
cp "$STATE/work.auth.json" "$TMP/snap-before.json"

# ---------- 1. a successful read ----------
OUT="$("$BIN_DIR/codex-switch" quota)"
check "quota prints a window row" outputs "$OUT" '7d'
check "quota prints the used percentage" outputs "$OUT" '73%'
check "quota prints a reset countdown" outputs "$OUT" 'in [0-9]'
check "quota marks the active profile" outputs "$OUT" '^\* alt'
check "quota surfaces the reset credit" outputs "$OUT" 'Reset credits for .*: 1 available (expires 20'
check "quota creates the cache" test -f "$CACHE"
check "cache is mode 600" mode_is "$CACHE" 600
check "state dir stays mode 700" mode_is "$STATE" 700
check "cache records the plan type" bash -c "python3 -c \"import json;raise SystemExit(0 if json.load(open('$CACHE'))['profiles']['alt']['plan_type']=='plus' else 1)\""
check "cache keys the window by duration, not by field name" bash -c "python3 -c \"
import json
w=json.load(open('$CACHE'))['profiles']['alt']['windows']
raise SystemExit(0 if len(w)==1 and w[0]['duration_minutes']==10080 else 1)\""
check "cache distinguishes live from snapshot" bash -c "python3 -c \"
import json
d=json.load(open('$CACHE'))['profiles']
raise SystemExit(0 if d['alt']['source']=='live' and d['work']['source']=='snapshot' else 1)\""

# ---------- 2. isolation: every read uses a throwaway CODEX_HOME ----------
check "no read used the real codex dir" bash -c "! grep -q '\"home\": \"$CX\"' '$STUB_DIR/calls.log'"
check "no read used the state dir" bash -c "! grep -q '\"home\": \"$STATE\"' '$STUB_DIR/calls.log'"
check "each profile got its own temp home" bash -c "python3 -c \"
import json
homes=[json.loads(l)['home'] for l in open('$STUB_DIR/calls.log')]
raise SystemExit(0 if len(homes)==len(set(homes))==2 else 1)\""
check "the temp home is mode 700" bash -c "python3 -c \"
import json
raise SystemExit(0 if all(json.loads(l)['home_mode']=='0o700' for l in open('$STUB_DIR/calls.log')) else 1)\""
check "the copied auth is mode 600" bash -c "python3 -c \"
import json
raise SystemExit(0 if all(json.loads(l)['auth_mode']=='0o600' for l in open('$STUB_DIR/calls.log')) else 1)\""
check "each profile was read with its own token" bash -c "python3 -c \"
import json
toks={json.loads(l)['auth'] for l in open('$STUB_DIR/calls.log')}
raise SystemExit(0 if len(toks)==2 else 1)\""
check "querying did not mutate the saved snapshot" cmp -s "$STATE/work.auth.json" "$TMP/snap-before.json"
check "querying did not activate another profile" bash -c "grep -qx 'alt' '$STATE/.active-profile'"
check "no temp codex home was left behind" bash -c "! ls -d /tmp/.codex-quota-* >/dev/null 2>&1"

# A query holds a real credential in a temp CODEX_HOME. It must not outlive the query,
# including when the query is killed. TMPDIR is redirected so the sweep and the counting
# both stay inside this test's sandbox.
SB="$TMP/tmpdir"; mkdir -p "$SB"
strays() { find "$SB" -maxdepth 1 -type d -name '.codex-quota-*' | wc -l; }
# Cleanup cannot be instantaneous — the app-server is terminated before its CODEX_HOME
# is removed — so wait for it rather than asserting on the same tick.
drains() { local i; for i in $(seq 100); do [[ "$(strays)" == 0 ]] && return 0; sleep 0.1; done; return 1; }
printf 'hang' > "$STUB_DIR/mode"
TMPDIR="$SB" timeout -s TERM 1 "$BIN_DIR/codex-switch" quota >/dev/null 2>&1 || true
check "SIGTERM mid-query removes the temp credential copy" drains
TMPDIR="$SB" timeout -s INT 1 "$BIN_DIR/codex-switch" quota >/dev/null 2>&1 || true
check "SIGINT mid-query removes the temp credential copy" drains
TMPDIR="$SB" timeout -s HUP 1 "$BIN_DIR/codex-switch" quota >/dev/null 2>&1 || true
check "SIGHUP mid-query removes the temp credential copy" drains
# A second signal arriving during cleanup must not abort it before the directory goes.
TMPDIR="$SB" bash -c '"$1" quota >/dev/null 2>&1 & p=$!; sleep 1; kill -TERM $p; kill -TERM $p; wait $p' _ "$BIN_DIR/codex-switch" >/dev/null 2>&1 || true
check "a second signal during cleanup does not strand the copy" drains
# SIGKILL cannot be caught, so the next run must sweep what it stranded.
# The kill notice is emitted by whichever shell owns the job, so run it in an inner
# shell whose stderr is discarded; the suite must leave stderr clean.
bash -c 'TMPDIR="$1" timeout -s KILL 1 "$2" quota >/dev/null 2>&1' _ "$SB" "$BIN_DIR/codex-switch" 2>/dev/null || true
check "SIGKILL does strand a temp dir" bash -c "test \"\$(find '$SB' -maxdepth 1 -type d -name '.codex-quota-*' | wc -l)\" != 0"
find "$SB" -maxdepth 1 -type d -name '.codex-quota-*' -exec touch -d '1 hour ago' {} \;
printf 'ok' > "$STUB_DIR/mode"
TMPDIR="$SB" "$BIN_DIR/codex-switch" quota >/dev/null 2>&1 || true
check "the next run sweeps a stranded temp dir" test "$(strays)" = 0
# A concurrent run's fresh temp dir must survive the sweep.
FRESH="$(TMPDIR="$SB" mktemp -d "$SB/.codex-quota-XXXXXX")"
TMPDIR="$SB" "$BIN_DIR/codex-switch" quota >/dev/null 2>&1 || true
check "the sweep spares a fresh temp dir from a concurrent run" test -d "$FRESH"
rmdir "$FRESH"

# ---------- 3. a server-initiated refresh must be declined, never answered ----------
: > "$STUB_DIR/calls.log"; rm -f "$STUB_DIR/refresh-declined" "$STUB_DIR/refresh-ANSWERED"
printf 'refresh' > "$STUB_DIR/mode"
cp "$CACHE" "$TMP/cache-before.json"
"$BIN_DIR/codex-switch" quota >/dev/null 2>&1 || true
check "flipauth never answers a token refresh request" test ! -f "$STUB_DIR/refresh-ANSWERED"
check "flipauth declines the refresh request" test -f "$STUB_DIR/refresh-declined"
check "a refresh-then-401 run preserves the cache" cmp -s "$CACHE" "$TMP/cache-before.json"

# ---------- 4. failures never erase the last good sample ----------
printf '401' > "$STUB_DIR/mode"
ERR="$("$BIN_DIR/codex-switch" quota 2>&1 || true)"
check "401 is reported as an expired token" outputs "$ERR" 'token expired'
check "401 preserves the previous cache" cmp -s "$CACHE" "$TMP/cache-before.json"
printf 'hang' > "$STUB_DIR/mode"
CODEX_SWITCH_QUOTA_TIMEOUT=2 "$BIN_DIR/codex-switch" quota >/dev/null 2>&1 || true
check "a hung app-server times out without erasing the cache" cmp -s "$CACHE" "$TMP/cache-before.json"
check "a missing codex binary fails clearly" bash -c "! CODEX_SWITCH_CODEX_BIN=/nonexistent-codex \"$BIN_DIR/codex-switch\" quota 2>&1 | grep -q Traceback"

# ---------- 5. status renders the cache offline ----------
printf 'ok' > "$STUB_DIR/mode"
: > "$STUB_DIR/calls.log"
STATUS="$("$BIN_DIR/codex-switch" status)"
check "status starts no app-server" bash -c "test ! -s '$STUB_DIR/calls.log'"
check "status keeps the active profile line" outputs "$STATUS" '^Active profile: alt$'
check "status keeps the saved profiles line" outputs "$STATUS" '^Saved profiles: alt work$'
check "status shows the cached value as a lower bound" outputs "$STATUS" '≥73%'
check "status labels the window by duration" outputs "$STATUS" '7d'
check "status shows the sample age" outputs "$STATUS" 'just now\|ago'
check "status shows the reset credit" outputs "$STATUS" 'Reset credits'

# an elapsed window must degrade to unknown rather than show a stale number
python3 - "$CACHE" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
p = sys.argv[1]; c = json.load(open(p))
c["profiles"]["work"]["windows"][0]["resets_at"] = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
json.dump(c, open(p, "w"))
PY
STATUS="$("$BIN_DIR/codex-switch" status)"
check "an elapsed window reports unknown" bash -c "printf '%s' \"\$0\" | grep '^  work' | grep -q 'unknown'" "$STATUS"
check "an elapsed window hides the stale percentage" bash -c "! printf '%s' \"\$0\" | grep '^  work' | grep -q '73'" "$STATUS"

# ---------- 6. --json agrees with the text form ----------
JSON="$("$BIN_DIR/codex-switch" status --json)"
check "codex --json parses" bash -c "printf '%s' \"\$0\" | python3 -c 'import json,sys;json.load(sys.stdin)'" "$JSON"
check "codex --json now carries quota" bash -c "printf '%s' \"\$0\" | python3 -c \"
import json,sys
rows={r['name']:r for r in json.load(sys.stdin)['profiles']}
raise SystemExit(0 if rows['alt']['quota'] and rows['alt']['quota']['windows'] else 1)\"" "$JSON"
check "codex --json names the value a lower bound" outputs "$JSON" 'utilization_at_least'
check "codex --json labels and keys the window by duration" bash -c "printf '%s' \"\$0\" | python3 -c \"
import json,sys
w=json.load(sys.stdin)['profiles'][0]['quota']['windows'][0]
raise SystemExit(0 if w['duration_minutes']==10080 and w['label']=='7d' else 1)\"" "$JSON"
check "codex --json marks the elapsed window expired" bash -c "printf '%s' \"\$0\" | python3 -c \"
import json,sys
rows={r['name']:r for r in json.load(sys.stdin)['profiles']}
w=rows['work']['quota']['windows'][0]
raise SystemExit(0 if w['state']=='expired' and w['utilization_at_least'] is None else 1)\"" "$JSON"
check "codex --json exposes the reset credit" bash -c "printf '%s' \"\$0\" | python3 -c \"
import json,sys
rows={r['name']:r for r in json.load(sys.stdin)['profiles']}
raise SystemExit(0 if rows['alt']['quota']['reset_credits']['available']==1 else 1)\"" "$JSON"
check "codex text and --json agree on every window" bash -c "
python3 - \"\$0\" \"\$1\" <<'PY'
import json, re, sys
text, doc = sys.argv[1], json.loads(sys.argv[2])
for row in doc['profiles']:
    q = row.get('quota')
    idx = next((i for i, l in enumerate(text.splitlines())
                if re.match(r'^[* ] ' + re.escape(row['name']) + r'\b', l)), None)
    assert idx is not None, row['name']
    lines = text.splitlines()[idx:idx + max(1, len(q['windows'] if q else [1]))]
    blob = '\n'.join(lines)
    if not q:
        assert 'no sample' in blob; continue
    for w in q['windows']:
        if w['state'] == 'known':
            assert f\"≥{w['utilization_at_least']:.0f}%\" in blob, (w, blob)
        else:
            assert 'unknown' in blob, (w, blob)
PY" "$STATUS" "$JSON"

# ---------- 7. no token reaches output or cache ----------
check "quota output does not leak the work token" lacks "$OUT" "$TOKEN_W"
check "quota output does not leak the alt token" lacks "$OUT" "$TOKEN_A"
check "status output does not leak a token" lacks "$STATUS" "$TOKEN_A"
check "--json does not leak a token" lacks "$JSON" "$TOKEN_A"
check "cache does not leak the work token" bash -c "! grep -q '$TOKEN_W' '$CACHE'"
check "cache does not leak the alt token" bash -c "! grep -q '$TOKEN_A' '$CACHE'"
check "cache stores no access_token field" bash -c "! grep -qi 'access_token\|tokens' '$CACHE'"

# ---------- 8. Claude is unaffected ----------
CL="$TMP/claude"; mkdir -p "$CL"; export CLAUDE_SWITCH_CLAUDE_DIR="$CL"
printf '%s' '{"claudeAiOauth":{"accessToken":"fixture-claude"}}' > "$CL/.credentials.json"
"$BIN_DIR/claude-switch" save one >/dev/null
CJSON="$("$BIN_DIR/claude-switch" status --json)"
check "claude --json keeps its named windows" bash -c "printf '%s' \"\$0\" | python3 -c \"
import json,sys
d=json.load(sys.stdin)
raise SystemExit(0 if d['service']=='claude' and d['profiles'][0]['quota'] is None else 1)\"" "$CJSON"
check "claude observe is still accepted" bash -c "printf '{}' | \"$BIN_DIR/claude-switch\" observe"
check "codex observe is still rejected" bash -c "! printf '{}' | \"$BIN_DIR/codex-switch\" observe 2>/dev/null"

echo "----"
if [[ "$fails" -gt 0 ]]; then echo "$fails check(s) failed"; exit 1; fi
echo "all codex-quota checks passed"
