#!/usr/bin/env bash
set -euo pipefail

BIN_DIR="${FLIPAUTH_BIN_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fails=0
check() { local desc="$1"; shift; if "$@"; then printf 'ok   - %s\n' "$desc"; else printf 'FAIL - %s\n' "$desc"; fails=$((fails+1)); fi; }

CL="$TMP/claude"; mkdir -p "$CL"; export CLAUDE_SWITCH_CLAUDE_DIR="$CL"
printf '%s' '{"claudeAiOauth":{"accessToken":"opaque-secret-tok","subscriptionType":"pro","expiresAt":1779870689090}}' > "$CL/.credentials.json"
"$BIN_DIR/claude-switch" save acct >/dev/null
OUT="$("$BIN_DIR/claude-switch" doctor)"

check "doctor has Claude header" bash -c "printf '%s' \"\$0\" | grep -q 'Claude switch doctor'" "$OUT"
check "doctor reports subscription_type pro" bash -c "printf '%s' \"\$0\" | grep -q 'subscription_type: pro'" "$OUT"
check "doctor lists saved acct" bash -c "printf '%s' \"\$0\" | grep -q 'saved_profiles: acct'" "$OUT"
check "doctor reports expires_at" bash -c "printf '%s' \"\$0\" | grep -q 'expires_at:'" "$OUT"
check "doctor does NOT leak token" bash -c "! printf '%s' \"\$0\" | grep -q 'opaque-secret-tok'" "$OUT"
check "doctor does NOT claim identity_fp" bash -c "! printf '%s' \"\$0\" | grep -q 'identity_fp'" "$OUT"

echo "----"
if [[ "$fails" -gt 0 ]]; then echo "$fails check(s) failed"; exit 1; fi
echo "all claude-doctor checks passed"
