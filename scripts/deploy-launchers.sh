#!/usr/bin/env bash
# Deploy named switch commands from registered accounts. Safe for agents to run:
# creates launchers and records the official executable; never starts/stops CLIs,
# logs in, reads credentials, changes selection, or replaces an existing file.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
service="${1:-}"
if [[ "$service" != codex && "$service" != claude ]]; then
  echo "Usage: deploy-launchers.sh <codex|claude> [--check] [destination-directory]" >&2
  exit 2
fi
shift
check_args=()
if [[ "${1:-}" == --check ]]; then check_args=(--check); shift; fi
destination="${1:-$HOME/.local/bin}"
if [[ "$#" -gt 1 || ! -d "$destination" ]]; then
  echo "Destination must be an existing directory" >&2
  exit 2
fi
accounts_json="$("$repo/flipauth" "$service" account list --json)"
labels="$(python3 -c 'import json,sys; print("\n".join(row["name"] for row in json.load(sys.stdin)["accounts"]))' <<< "$accounts_json")"
while IFS= read -r label; do
  [[ -n "$label" ]] || continue
  "$repo/flipauth" "$service" account bind "$label" "$destination/$service-$label" --switch "${check_args[@]}"
done <<< "$labels"
