#!/usr/bin/env bash
set -euo pipefail

# Isolated coverage for the pre-mutation process gate.  The fake Herdr exposes the
# same snapshot/process-info/send surface used by flipauth; no real terminal, Agent,
# or credential directory is inspected or stopped.

BIN_DIR="${FLIPAUTH_BIN_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fails=0
check() { local desc="$1"; shift; if "$@"; then printf 'ok   - %s\n' "$desc"; else printf 'FAIL - %s\n' "$desc"; fails=$((fails+1)); fi; }

export SAFETY_FIXTURE="$TMP/state"; mkdir -p "$SAFETY_FIXTURE"
cat > "$TMP/herdr" <<'PY'
#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['SAFETY_FIXTURE'])
mode = (root / 'mode').read_text().strip()
exited = (root / 'exited').exists()
service = 'claude' if 'claude' in mode or mode == 'isolation' else 'codex'
pane = 'pane-claude' if service == 'claude' else 'pane-codex'
def out(doc): print(json.dumps(doc))
if sys.argv[1:] == ['api', 'snapshot']:
    agents = []
    if mode.startswith(('idle-', 'working-')) or mode == 'isolation':
        agents = [{'agent': service, 'agent_status': 'working' if mode.startswith('working-') else 'idle',
                   'pane_id': pane, 'workspace_id': 'w1', 'tab_id': 't1'}]
    out({'result': {'snapshot': {'agents': agents, 'workspaces': [{'workspace_id':'w1','label':'fixture'}], 'tabs': [{'tab_id':'t1','label':service.title()}]}}})
elif sys.argv[1:3] == ['pane', 'process-info']:
    running = (mode.startswith('idle-') or mode == 'isolation') and (not exited or mode == 'idle-stubborn-claude')
    pid = 123 if service == 'claude' else 456
    rows = [{'name': service, 'argv': [service], 'pid': pid}] if running else []
    out({'result': {'process_info': {'foreground_processes': rows}}})
elif sys.argv[1:3] == ['pane', 'send-text']:
    (root / 'calls').open('a').write('send-text ' + ' '.join(sys.argv[3:]) + '\n')
elif sys.argv[1:3] == ['pane', 'send-keys']:
    (root / 'calls').open('a').write('send-keys ' + ' '.join(sys.argv[3:]) + '\n')
    if mode != 'idle-stubborn-claude': (root / 'exited').write_text('1')
else: raise SystemExit(2)
PY
cat > "$TMP/ps" <<'PY'
#!/usr/bin/env python3
import os, pathlib
root = pathlib.Path(os.environ['SAFETY_FIXTURE']); mode = (root / 'mode').read_text().strip()
exited = (root / 'exited').exists()
if mode == 'external-claude': print('700 1 pts/7 claude claude --fixture')
elif mode == 'external-codex': print('701 1 pts/8 codex codex --fixture')
elif mode.startswith('idle-') and (not exited or mode == 'idle-stubborn-claude'):
    service = 'claude' if 'claude' in mode else 'codex'; pid = 123 if service == 'claude' else 456
    print(f'{pid} 1 pts/9 {service} {service} --fixture')
elif mode == 'isolation':
    if not exited: print('123 1 pts/9 claude claude --fixture')
    print('456 1 pts/10 codex codex --fixture\n789 1 pts/11 pi pi --fixture')
PY
chmod +x "$TMP/herdr" "$TMP/ps"
export FLIPAUTH_HERDR_BIN="$TMP/herdr" FLIPAUTH_PS_BIN="$TMP/ps"

set_mode() { printf '%s' "$1" > "$SAFETY_FIXTURE/mode"; rm -f "$SAFETY_FIXTURE/exited" "$SAFETY_FIXTURE/calls"; }
setup_claude() {
  CL="$TMP/claude"; rm -rf "$CL"; mkdir -p "$CL"; export CLAUDE_SWITCH_CLAUDE_DIR="$CL"; set_mode none
  printf '%s' '{"claudeAiOauth":{"accessToken":"one"}}' > "$CL/.credentials.json"; "$BIN_DIR/claude-switch" save one >/dev/null
  printf '%s' '{"claudeAiOauth":{"accessToken":"two"}}' > "$CL/.credentials.json"; "$BIN_DIR/claude-switch" save two >/dev/null
}
setup_codex() {
  CX="$TMP/codex"; rm -rf "$CX"; mkdir -p "$CX"; export CODEX_SWITCH_CODEX_DIR="$CX"; set_mode none
  printf '%s' '{"tokens":{"access_token":"one"}}' > "$CX/auth.json"; "$BIN_DIR/codex-switch" save one >/dev/null
  printf '%s' '{"tokens":{"access_token":"two"}}' > "$CX/auth.json"; "$BIN_DIR/codex-switch" save two >/dev/null
}
snapshot_claude() { cp "$CL/.credentials.json" "$TMP/live-before"; cp "$CL/oauth-accounts/two.credentials.json" "$TMP/saved-before"; cp "$CL/oauth-accounts/.active-profile" "$TMP/marker-before"; }

setup_claude; set_mode none; "$BIN_DIR/claude-switch" one >/dev/null
check "no Claude process permits a switch" grep -q 'one' "$CL/.credentials.json"
setup_codex; set_mode none; "$BIN_DIR/codex-switch" one >/dev/null
check "no Codex process permits a switch" grep -q 'one' "$CX/auth.json"

setup_claude; set_mode idle-claude; "$BIN_DIR/claude-switch" one >/dev/null
check "idle Herdr Claude exits gracefully then switches" bash -c "grep -q 'send-text pane-claude /exit' '$SAFETY_FIXTURE/calls' && grep -q 'send-keys pane-claude enter' '$SAFETY_FIXTURE/calls' && grep -q one '$CL/.credentials.json'"
setup_claude; set_mode working-claude; snapshot_claude
check "working Herdr Claude refuses without mutation" bash -c "! '$BIN_DIR/claude-switch' one >/dev/null 2>&1 && cmp -s '$CL/.credentials.json' '$TMP/live-before' && cmp -s '$CL/oauth-accounts/two.credentials.json' '$TMP/saved-before' && cmp -s '$CL/oauth-accounts/.active-profile' '$TMP/marker-before'"

setup_codex; set_mode idle-codex; "$BIN_DIR/codex-switch" one >/dev/null
check "idle Herdr Codex exits gracefully then switches" bash -c "grep -q 'send-text pane-codex /exit' '$SAFETY_FIXTURE/calls' && grep -q one '$CX/auth.json'"
setup_codex; set_mode working-codex; cp "$CX/auth.json" "$TMP/codex-live-before"; cp "$CX/oauth-accounts/two.auth.json" "$TMP/codex-saved-before"; cp "$CX/oauth-accounts/.active-profile" "$TMP/codex-marker-before"
check "working Herdr Codex refuses without mutation" bash -c "! '$BIN_DIR/codex-switch' one >/dev/null 2>&1 && cmp -s '$CX/auth.json' '$TMP/codex-live-before' && cmp -s '$CX/oauth-accounts/two.auth.json' '$TMP/codex-saved-before' && cmp -s '$CX/oauth-accounts/.active-profile' '$TMP/codex-marker-before'"

setup_claude; set_mode external-claude; snapshot_claude
check "unmanaged Claude refuses without mutation" bash -c "! '$BIN_DIR/claude-switch' one >/dev/null 2>&1 && cmp -s '$CL/.credentials.json' '$TMP/live-before' && cmp -s '$CL/oauth-accounts/two.credentials.json' '$TMP/saved-before' && cmp -s '$CL/oauth-accounts/.active-profile' '$TMP/marker-before'"
setup_codex; set_mode external-codex; cp "$CX/auth.json" "$TMP/codex-live-before"; cp "$CX/oauth-accounts/two.auth.json" "$TMP/codex-saved-before"; cp "$CX/oauth-accounts/.active-profile" "$TMP/codex-marker-before"
check "unmanaged Codex refuses without mutation" bash -c "! '$BIN_DIR/codex-switch' one >/dev/null 2>&1 && cmp -s '$CX/auth.json' '$TMP/codex-live-before' && cmp -s '$CX/oauth-accounts/two.auth.json' '$TMP/codex-saved-before' && cmp -s '$CX/oauth-accounts/.active-profile' '$TMP/codex-marker-before'"

setup_claude; set_mode idle-stubborn-claude; snapshot_claude
check "an unexited idle Claude times out without mutation" bash -c "! FLIPAUTH_SWITCH_STOP_TIMEOUT=1 '$BIN_DIR/claude-switch' one >/dev/null 2>&1 && cmp -s '$CL/.credentials.json' '$TMP/live-before' && cmp -s '$CL/oauth-accounts/two.credentials.json' '$TMP/saved-before' && cmp -s '$CL/oauth-accounts/.active-profile' '$TMP/marker-before'"

setup_claude; set_mode isolation; "$BIN_DIR/claude-switch" one >/dev/null
check "Claude switch leaves Codex and Pi process records untouched" bash -c "grep -q one '$CL/.credentials.json' && grep -q pane-claude '$SAFETY_FIXTURE/calls' && ! grep -q -E 'pane-codex|pi' '$SAFETY_FIXTURE/calls'"
setup_codex; set_mode external-claude; "$BIN_DIR/codex-switch" one >/dev/null
check "Codex switch ignores Claude process records" grep -q 'one' "$CX/auth.json"

echo '----'
if [[ "$fails" -gt 0 ]]; then echo "$fails check(s) failed"; exit 1; fi
echo 'all process-safety checks passed'
