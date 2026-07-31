# todo

Short-file control plane. One line per item, newest section first. Keep operator
specifics (account labels, machine paths, real usage figures) out of this file —
they belong in ignored local notes, per README.md → *Privacy boundary*.

## In review

- [ ] **PR #1 — quota cache, `observe`, `status --json`.** Implemented; 78 offline checks
      plus the existing parity and doctor suites pass. Draft; awaiting merge.

## Next

- [ ] Hook `observe` onto the local Claude Code status line. One line at the end of the
      statusLine script; until that is done the cache is only as fresh as the last manual
      `quota` run. This is a machine-local config change, not a repo change.
- [ ] Remove `pic/*.png` from history. The screenshots carry real account labels, a
      hostname, a home path and a credential file hash. Must happen **after** PR #1 merges,
      or that branch is orphaned onto discarded history.

## Deferred, with reasons

- **Spend / cost ledger (`run`, `spend`).** Specced, then dropped before implementation —
  not wanted. The three measurements behind it are worth remembering if it ever returns:
  `claude -p --output-format json` reports `total_cost_usd` in its `result` event; a
  `rate_limit_event` in the same stream carries `isUsingOverage`, a direct answer to
  "is this call billing past the subscription"; and a trivial delegated call costs about
  the same as a substantial one, because the system-prompt cache read dominates — so cost
  tracks call *count*, not task size. All three are free to obtain; none needs a network
  request of its own.
- **Automatic stop-at-threshold / account rotation.** Rejected twice over: a utilization
  percentage cannot express dollars, and an automatic brake removes the decision from the
  operator rather than informing it. Revisit only if visibility demonstrably fails.
- **Cross-checking `observe`'s profile attribution.** There is no account identifier in
  Claude credentials, and the credential file hash changes on every token refresh, so any
  check built from it produces false alarms rather than safety. Attribution follows
  `.active-profile`; the limitation is documented instead of papered over.
- **Branching on exhausted rate-limit states.** The vocabulary for `status` /
  `overageStatus` beyond `allowed` has not been observed. Store opaque, display verbatim.
- **`quota` SIGPIPE handling.** `flipauth claude quota | head` can still emit a
  `BrokenPipeError` traceback. Pre-existing, not a regression; `status` was fixed in PR #1
  because that change introduced it there. Small, self-contained follow-up.

## Done

- [x] Quota cache: allow-listed fields, atomic `600` write, merge-not-replace, failures
      preserve the last good sample. (PR #1)
- [x] Cached quota in `status`: `≥N%` lower bound, expired window degrades to `unknown`,
      zero network calls, Claude-only. (PR #1)
- [x] `observe`: free continuous refresh from the Claude Code statusLine payload — no
      network request, silent on every failure, throttled, epoch normalised to ISO. (PR #1)
- [x] `status --json`: machine-readable, offline, with the lower-bound semantics carried in
      the field names; a test asserts it agrees with the text rendering. (PR #1)
- [x] `tests/claude-quota-cache-test.sh`: 78 checks against a local HTTP stub, which also
      gave `quota` its first offline coverage of the 401 / 429 / connection-failure paths.
