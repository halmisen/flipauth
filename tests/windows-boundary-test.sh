#!/usr/bin/env bash
set -euo pipefail

# Isolated coverage for the Windows-filesystem boundary.
#
# flipauth manages the WSL-side CLI. Every managed path comes from an overridable
# variable, so nothing structural stops one from resolving onto a Windows mount; these
# checks prove the script refuses that case instead of writing the Windows installation's
# credentials. A fake `findmnt` reports the Windows filesystem type for a chosen prefix
# only, so no case has to touch a real /mnt path to exercise the guard.

BIN_DIR="${FLIPAUTH_BIN_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fails=0
check() { local desc="$1"; shift; if "$@"; then printf 'ok   - %s\n' "$desc"; else printf 'FAIL - %s\n' "$desc"; fails=$((fails+1)); fi; }

cat > "$TMP/findmnt" <<'PY'
#!/usr/bin/env python3
# Reports a Windows filesystem type only for paths under $WINFS_MATCH.
import os, sys
target = sys.argv[sys.argv.index('--target') + 1] if '--target' in sys.argv else ''
match = os.environ.get('WINFS_MATCH', '')
print('9p' if match and target.startswith(match) else 'ext4')
PY
chmod +x "$TMP/findmnt"
FAKE_PATH="$TMP:$PATH"

printf '#!/bin/sh\nexit 0\n' > "$TMP/ps-empty"; chmod +x "$TMP/ps-empty"
export FLIPAUTH_PS_BIN="$TMP/ps-empty" FLIPAUTH_HERDR_BIN="$TMP/no-herdr"

CODEX_DIR="$TMP/codex"; mkdir -p "$CODEX_DIR/oauth-accounts"
printf '{"tokens":{"access_token":"tok"}}\n' > "$CODEX_DIR/auth.json"
printf '{"tokens":{"access_token":"tok"}}\n' > "$CODEX_DIR/oauth-accounts/one.auth.json"

run_codex() { CODEX_SWITCH_CODEX_DIR="$CODEX_DIR" "$BIN_DIR/codex-switch" "$@" 2>&1; }

# --- managed paths on a Windows filesystem ------------------------------------------
out="$(PATH="$FAKE_PATH" WINFS_MATCH="$TMP/codex" run_codex status || true)"
check "a managed dir on a Windows filesystem is refused" \
  grep -q "Windows filesystem" <<<"$out"
check "the refusal names the WSL-only scope" \
  grep -q "manages the WSL-side CLI only" <<<"$out"

out="$(PATH="$FAKE_PATH" WINFS_MATCH="$TMP/codex" run_codex save two || true)"
check "save is refused before it can write" grep -q "Windows filesystem" <<<"$out"
check "the refused save wrote no profile" [ ! -e "$CODEX_DIR/oauth-accounts/two.auth.json" ]

out="$(PATH="$FAKE_PATH" WINFS_MATCH="$TMP/codex" run_codex one || true)"
check "activate is refused before it can write" grep -q "Windows filesystem" <<<"$out"
check "the refused activate left the marker alone" \
  [ ! -e "$CODEX_DIR/oauth-accounts/.active-profile" ]

# A live credential file pointed at a Windows path is refused even when the state
# directory itself is local.
mkdir -p "$TMP/winauth"
out="$(PATH="$FAKE_PATH" WINFS_MATCH="$TMP/winauth" \
  CODEX_SWITCH_AUTH_FILE="$TMP/winauth/auth.json" run_codex status || true)"
check "a live credential file on a Windows filesystem is refused" \
  grep -q "Windows filesystem" <<<"$out"

# --- no usable findmnt: the /mnt prefix fallback --------------------------------------
# The guard must not depend on findmnt being present, so this stub always fails and the
# path below is refused on its mount point alone. It names a directory that does not
# exist, so a regression here cannot write into a real Windows drive.
NOMNT="$TMP/nofindmnt"; mkdir -p "$NOMNT"
printf '#!/bin/sh\nexit 1\n' > "$NOMNT/findmnt"; chmod +x "$NOMNT/findmnt"
out="$(PATH="$NOMNT:$PATH" CODEX_SWITCH_CODEX_DIR=/mnt/no-such-flipauth-target \
  "$BIN_DIR/codex-switch" status 2>&1 || true)"
check "without a usable findmnt a /mnt path still refuses" \
  grep -q "Windows filesystem" <<<"$out"
check "the fallback refusal created nothing under /mnt" \
  [ ! -e /mnt/no-such-flipauth-target ]

# --- a config root the CLI would actually read --------------------------------------
out="$(CODEX_HOME="$TMP/elsewhere" run_codex save two || true)"
check "a mismatched CODEX_HOME refuses the switch" grep -q "CODEX_HOME is set to" <<<"$out"
check "the mismatch says the change would not reach the CLI" \
  grep -q "would never reach it" <<<"$out"
check "the refused mismatch wrote no profile" [ ! -e "$CODEX_DIR/oauth-accounts/two.auth.json" ]

out="$(CODEX_HOME="$CODEX_DIR" run_codex save two || true)"
check "a matching CODEX_HOME is accepted" [ -e "$CODEX_DIR/oauth-accounts/two.auth.json" ]
rm -f "$CODEX_DIR/oauth-accounts/two.auth.json" "$CODEX_DIR/oauth-accounts/.active-profile"

# --- the binary the quota reader drives ----------------------------------------------
printf '#!/bin/sh\nexit 0\n' > "$TMP/codex.exe"; chmod +x "$TMP/codex.exe"
out="$(CODEX_SWITCH_CODEX_BIN="$TMP/codex.exe" run_codex quota || true)"
check "a Windows codex executable is refused" grep -q "Windows executable" <<<"$out"

printf '#!/bin/sh\nexit 0\n' > "$TMP/codex-native"; chmod +x "$TMP/codex-native"
out="$(PATH="$FAKE_PATH" WINFS_MATCH="$TMP/codex-native" \
  CODEX_SWITCH_CODEX_BIN="$TMP/codex-native" run_codex quota || true)"
check "a codex binary on a Windows filesystem is refused" \
  grep -q "on a Windows filesystem" <<<"$out"

# --- the temp dir the credential copy lands in ----------------------------------------
WINTMP="$TMP/wintemp"; mkdir -p "$WINTMP"
out="$(PATH="$FAKE_PATH" WINFS_MATCH="$WINTMP" TMPDIR="$WINTMP" \
  CODEX_SWITCH_CODEX_BIN="$TMP/codex-native" run_codex quota || true)"
check "a TMPDIR on a Windows filesystem is refused" \
  grep -q "temporary directory (TMPDIR)" <<<"$out"
check "the refused quota copied no credential" \
  [ -z "$(find "$WINTMP" -name '.codex-quota-*' 2>/dev/null)" ]

# --- the ordinary local case still works ----------------------------------------------
out="$(run_codex status || true)"
check "a WSL-local setup is unaffected" grep -q "Saved profiles" <<<"$out"

printf -- '----\n'
if (( fails )); then printf '%d windows-boundary check(s) failed\n' "$fails"; exit 1; fi
printf 'all windows-boundary checks passed\n'
