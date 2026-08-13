#!/usr/bin/env bash
set -euo pipefail

BIN_DIR="${FLIPAUTH_BIN_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
printf '#!/usr/bin/env bash\nexit 0\n' > "$TMP/ps-empty"; chmod +x "$TMP/ps-empty"
export FLIPAUTH_PS_BIN="$TMP/ps-empty" FLIPAUTH_HERDR_BIN="$TMP/no-herdr"

fails=0
check() { local desc="$1"; shift; if "$@"; then printf 'ok   - %s\n' "$desc"; else printf 'FAIL - %s\n' "$desc"; fails=$((fails+1)); fi; }
mode_is() { [[ "$(stat -c '%a' "$1")" == "$2" ]]; }
has() { grep -q "$2" "$1"; }

# ---------- claude (single file, Claude OAuth shape with optional extra blocks) ----------
CL="$TMP/claude"; mkdir -p "$CL"
export CLAUDE_SWITCH_CLAUDE_DIR="$CL"
printf '%s' '{"claudeAiOauth":{"accessToken":"tok-one","subscriptionType":"pro","expiresAt":1779870689090}}' > "$CL/.credentials.json"
"$BIN_DIR/claude-switch" save one >/dev/null
check "claude save creates profile file" test -f "$CL/oauth-accounts/one.credentials.json"
check "claude state dir mode 700" mode_is "$CL/oauth-accounts" 700
check "claude profile file mode 600" mode_is "$CL/oauth-accounts/one.credentials.json" 600
check "claude marker = one" has "$CL/oauth-accounts/.active-profile" '^one$'
printf '%s' '{"claudeAiOauth":{"accessToken":"tok-two"},"designOauth":{"accessToken":"design-two"}}' > "$CL/.credentials.json"
"$BIN_DIR/claude-switch" save two >/dev/null
"$BIN_DIR/claude-switch" one >/dev/null
check "claude activate one restores tok-one" has "$CL/.credentials.json" 'tok-one'
check "claude saved two before switching away" has "$CL/oauth-accounts/two.credentials.json" 'tok-two'
check "claude preserves extra oauth blocks" has "$CL/oauth-accounts/two.credentials.json" 'design-two'
check "claude status lists one two" bash -c "\"$BIN_DIR/claude-switch\" status | grep -q 'Saved profiles: one two'"
printf '%s' '{"wrong":1}' > "$CL/.credentials.json"
check "claude save rejects wrong shape" bash -c "! \"$BIN_DIR/claude-switch\" save bad 2>/dev/null"

# ---------- codex (two files, any-object shape, doctor) ----------
CX="$TMP/codex"; mkdir -p "$CX"
export CODEX_SWITCH_CODEX_DIR="$CX"
printf '%s' '{"auth_mode":"chatgpt","tokens":{"access_token":"a.b.c"}}' > "$CX/auth.json"
printf '%s' '{"k":"v1"}' > "$CX/.credentials.json"
"$BIN_DIR/codex-switch" save red >/dev/null
check "codex save creates auth profile" test -f "$CX/oauth-accounts/red.auth.json"
check "codex save creates creds profile" test -f "$CX/oauth-accounts/red.credentials.json"
check "codex state dir mode 700" mode_is "$CX/oauth-accounts" 700
check "codex auth profile mode 600" mode_is "$CX/oauth-accounts/red.auth.json" 600
check "codex creds profile mode 600" mode_is "$CX/oauth-accounts/red.credentials.json" 600
check "codex marker = red" has "$CX/oauth-accounts/.active-profile" '^red$'
printf '%s' '{"auth_mode":"chatgpt","tokens":{"access_token":"x.y.z"}}' > "$CX/auth.json"
"$BIN_DIR/codex-switch" save blue >/dev/null
"$BIN_DIR/codex-switch" red >/dev/null
check "codex saved blue before switching away" has "$CX/oauth-accounts/blue.auth.json" 'x.y.z'
check "codex activate red restores auth a.b.c" has "$CX/auth.json" 'a.b.c'
check "codex doctor header" bash -c "\"$BIN_DIR/codex-switch\" doctor | grep -q 'Codex switch doctor'"
check "codex doctor lists saved blue red" bash -c "\"$BIN_DIR/codex-switch\" doctor | grep -q 'saved_profiles: blue red'"

echo "----"
if [[ "$fails" -gt 0 ]]; then echo "$fails check(s) failed"; exit 1; fi
echo "all parity checks passed"
