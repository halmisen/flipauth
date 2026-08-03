# todo

Short-file control plane. One line per item, newest section first. Keep operator
specifics (account labels, machine paths, real usage figures) out of this file —
they belong in ignored local notes, per README.md → *Privacy boundary*.

## In review

- [ ] **PR #1 — quota cache, `observe`, `status --json`, Codex quota.** Implemented;
      164 offline checks across four suites. Draft; awaiting merge.

## Next

- [ ] Hook `observe` onto the local Claude Code status line. One line at the end of the
      statusLine script; until that is done the Claude cache is only as fresh as the last
      manual `quota` run. Machine-local config, not a repo change.
- [ ] Remove `pic/*.png` from history. The screenshots carry real account labels, a
      hostname, a home path and a credential file hash. Must happen **after** PR #1 merges,
      or that branch is orphaned onto discarded history.
- [ ] Redeem the Codex "full reset" credit before it expires, or let it lapse knowingly.
      `codex quota` now prints the count and expiry; consuming it needs
      `account/rateLimitResetCredit/consume`, which is a *write* and deliberately out of
      scope for flipauth.

## Deferred, with reasons

- **Consuming rate-limit reset credits from flipauth.** The RPC exists
  (`account/rateLimitResetCredit/consume`) but it mutates account state. flipauth reads;
  it does not spend. Displaying the balance is the useful half and carries no risk.
- **Codex `observe`.** There is no equivalent of the Claude statusLine hook: Codex's
  `status_line` in `config.toml` is a list of built-in widget names, not an external
  command, so there is nothing to intercept. Codex's cache is refreshed by `quota` only.
- **Spend / cost ledger (`run`, `spend`).** Specced, then dropped before implementation —
  not wanted. The three measurements behind it are worth remembering if it ever returns:
  `claude -p --output-format json` reports `total_cost_usd` in its `result` event; a
  `rate_limit_event` in the same stream carries `isUsingOverage`, a direct answer to
  "is this call billing past the subscription"; and a trivial delegated call costs about
  the same as a substantial one, because the system-prompt cache read dominates — so cost
  tracks call *count*, not task size. All three are free to obtain.
- **Automatic stop-at-threshold / account rotation.** Rejected twice over: a utilization
  percentage cannot express dollars, and an automatic brake removes the decision from the
  operator rather than informing it.
- **Cross-checking `observe`'s profile attribution.** There is no account identifier in
  Claude credentials, and the credential file hash changes on every token refresh, so any
  check built from it produces false alarms rather than safety.
- **Testing a *successful* Codex token refresh.** Not needed, and not worth the risk of
  rotating a real refresh token: `account/chatgptAuthTokens/refresh` is a server→client
  request, so declining it means the refresh never happens. A test asserts flipauth
  answers that request with an error and never with a result. What remains formally
  unproven is only whether the app-server has an internal fallback after a client
  declines; the RPC's existence and its response shape argue strongly against one.
- **`quota` SIGPIPE handling.** `flipauth claude quota | head` can still emit a
  `BrokenPipeError` traceback. Pre-existing; `status` was fixed in PR #1 because that
  change introduced it there. Small, self-contained follow-up.

## Settled facts (do not re-derive)

- **Codex's 5-hour window no longer exists.** Recorded session history shows
  `primary`≈300min + `secondary`=10080min from 2025-10 through 2026-06, a mixed rollout
  during 2026-07, and `primary`=10080min + `secondary`=null consistently since
  2026-07-24. The live RPC agrees, and `rateLimitsByLimitId` holds a single bucket
  identical to the legacy view. Nothing is hidden behind another call.
- **`primary`/`secondary` are ordinal, not semantic.** They swapped meaning once already.
  Always key on `windowDurationMins`.
- **`usedPercent` is 0-100.** Verified empirically — `100.0` appears in recorded history
  on a 300-minute window — not inferred from the field name.
- **"Every window must be 5h + 7d" was never a Codex requirement.** It was copied from
  Claude's shape. The real requirement is that every window that exists carries both a
  percentage and a reset time.

## Done

- [x] Quota cache: allow-listed fields, atomic `600` write, merge-not-replace, failures
      preserve the last good sample. (PR #1)
- [x] Cached quota in `status`: `≥N%` lower bound, expired window degrades to `unknown`,
      zero network calls. (PR #1)
- [x] `observe`: free continuous refresh from the Claude Code statusLine payload. (PR #1)
- [x] `status --json`: machine-readable, offline, lower-bound semantics in the field
      names; per-service tests assert it agrees with the text rendering. (PR #1)
- [x] `codex quota`: app-server JSON-RPC per profile, throwaway `CODEX_HOME`, refresh
      declined, windows keyed by duration, reset credits surfaced. (PR #1)
- [x] Temp credential copies cannot outlive a query: the reader runs as a job so signals
      reach it, the handler bails once so a second signal cannot abort cleanup mid-way,
      and an uncatchable kill's leftovers are swept by the next run. (PR #1)
