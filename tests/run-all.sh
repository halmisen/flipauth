#!/usr/bin/env bash
set -uo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$repo/work"
scratch="$(mktemp -d "$repo/work/offline-tests.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT
export TMPDIR="$scratch"
failed=0
count=0
run() {
  count=$((count + 1))
  local label="${*: -1}"
  printf '\nRunning %s\n' "${label##*/}"
  if ! "$@"; then failed=$((failed + 1)); fi
}
run bash -n "$repo/flipauth"
shopt -s nullglob
for suite in "$repo"/tests/*-test.sh; do run bash "$suite"; done
for suite in "$repo"/tests/*-test.py; do run python3 "$suite"; done
printf '\nSuites/checks: %s; failed: %s\n' "$count" "$failed"
[[ "$failed" -eq 0 ]]
