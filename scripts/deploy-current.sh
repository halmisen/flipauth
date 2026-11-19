#!/usr/bin/env bash
# Deploy or verify FlipAuth bind-current wrappers in an isolated PATH directory
# ($HOME/.local/flipauth/bin/<service>), configure ~/.bashrc and ~/.profile,
# and safely migrate legacy ~/.local/bin/<service> bind-current wrappers into a
# timestamped backup directory without touching real official binaries/symlinks.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
state_dir="${FLIPAUTH_ACCOUNTS_DIR:-$HOME/.local/state/flipauth}"
current_bin_dir="$HOME/.local/flipauth/bin"
legacy_bin_dir="$HOME/.local/bin"

usage() {
  echo "Usage: deploy-current.sh [codex|claude|all] [--check]" >&2
}

service_arg=""
check_only=0
for arg in "$@"; do
  case "$arg" in
    --check)
      check_only=1
      ;;
    codex|claude|all)
      if [[ -n "$service_arg" ]]; then
        usage
        exit 2
      fi
      service_arg="$arg"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done
service_arg="${service_arg:-all}"

resolve_services() {
  if [[ "$service_arg" != "all" ]]; then
    printf '%s\n' "$service_arg"
    return
  fi
  python3 - "$state_dir/accounts.json" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    sys.exit(0)
data = json.loads(path.read_text())
selected = data.get("selected", {})
accounts = data.get("accounts", {})
for svc in ("codex", "claude"):
    if selected.get(svc) or len(accounts.get(svc, {})) >= 2:
        print(svc)
PY
}

is_legacy_current_wrapper() {
  local path="$1"
  [[ -f "$path" && ! -L "$path" ]] || return 1
  python3 - "$path" <<'PY'
import sys
from pathlib import Path
try:
    with Path(sys.argv[1]).open("rb") as f:
        header = f.read(256)
    sys.exit(0 if b"# flipauth current launcher" in header else 1)
except OSError:
    sys.exit(1)
PY
}

has_path_block() {
  local rc_file="$1"
  [[ -f "$rc_file" ]] && grep -Fq '.local/flipauth/bin' "$rc_file" && grep -Eq 'PATH=.*\.local/flipauth/bin' "$rc_file"
}

append_path_block() {
  local rc_file="$1"
  if [[ -s "$rc_file" ]]; then
    printf '\n' >> "$rc_file"
  fi
  cat >> "$rc_file" <<'EOF'
# FlipAuth current-profile CLI launchers
if [ -d "$HOME/.local/flipauth/bin" ]; then
    case "$PATH" in
        "$HOME/.local/flipauth/bin"|"$HOME/.local/flipauth/bin:"*) ;;
        *) export PATH="$HOME/.local/flipauth/bin:$PATH" ;;
    esac
fi
EOF
}

verify_current_wrapper() {
  local service="$1"
  local target="$current_bin_dir/$service"
  if [[ -L "$target" || ! -f "$target" || ! -x "$target" ]]; then
    echo "missing or non-executable current wrapper: $target" >&2
    return 1
  fi
  python3 - "$target" "$service" <<'PY'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
service = sys.argv[2]
ok = (
    "# flipauth current launcher" in text
    and f"{service} account current --" in text
)
sys.exit(0 if ok else 1)
PY
}

mapfile -t services < <(resolve_services)
if [[ "${#services[@]}" -eq 0 ]]; then
  echo "No eligible services found in $state_dir/accounts.json (need selected or >=2 accounts)."
  exit 0
fi

failed=0
timestamp="$(date +%Y%m%d-%H%M%S)"

for service in "${services[@]}"; do
  target="$current_bin_dir/$service"
  legacy="$legacy_bin_dir/$service"

  if [[ "$check_only" -eq 1 ]]; then
    if verify_current_wrapper "$service"; then
      echo "verified: $target"
    else
      echo "check failed: $target is missing or invalid" >&2
      failed=1
    fi
    if is_legacy_current_wrapper "$legacy"; then
      echo "check failed: legacy bind-current wrapper still at $legacy; run deploy-current.sh $service to migrate it out" >&2
      failed=1
    fi
  else
    mkdir -p -m 700 "$current_bin_dir"
    "$repo/flipauth" "$service" account bind-current "$target"
    if is_legacy_current_wrapper "$legacy"; then
      backup_dir="$state_dir/launcher-backups/$timestamp"
      mkdir -p -m 700 "$backup_dir"
      mv -- "$legacy" "$backup_dir/$service"
      echo "migrated legacy wrapper: $legacy -> $backup_dir/$service"
    fi
  fi
done

for rc_file in "$HOME/.bashrc" "$HOME/.profile"; do
  if has_path_block "$rc_file"; then
    echo "verified PATH in: $rc_file"
  elif [[ "$check_only" -eq 1 ]]; then
    echo "check failed: $rc_file does not add \$HOME/.local/flipauth/bin to PATH" >&2
    failed=1
  else
    append_path_block "$rc_file"
    echo "updated PATH in: $rc_file"
  fi
done

for service in "${services[@]}"; do
  if [[ -d "$legacy_bin_dir" ]]; then
    if ! bash "$repo/scripts/deploy-launchers.sh" "$service" --check; then
      echo "note: named switch launcher check reported differences for $service (run scripts/deploy-launchers.sh $service if you want switch launchers updated)" >&2
    fi
  else
    echo "note: $legacy_bin_dir does not exist; skipping named launcher check for $service" >&2
  fi
  short_service="cod"
  if [[ "$service" == "claude" ]]; then
    short_service="cc"
  fi
  "$repo/flipauth" "$short_service" status
done

exit "$failed"
