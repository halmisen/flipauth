# todo

Short-file control plane. One line per item, newest section first. Keep operator
specifics (account labels, machine paths, real usage figures) out of this file —
they belong in ignored local notes, per README.md → *Privacy boundary*.

## Next

- [ ] OSS statusLine onboarding: detect a missing Claude `statusLine`, offer an explicit
      opt-in setup, preserve and back up existing settings, use a portable command path,
      and make the setup idempotent; never silently overwrite a configured user's command.
- [ ] Redeem the Codex "full reset" credit before it expires, or let it lapse knowingly.
      `codex quota` now prints the count and expiry; consuming it needs
      `account/rateLimitResetCredit/consume`, which is a *write* and deliberately out of
      scope for flipauth.

## Deferred, with reasons

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

- [x] Remove `pic/*.png` from history. The screenshots carried real account labels, a
      hostname, a home path and a credential file hash; the cleanup was completed after
      PR #1 merged.
- [x] PR #1 — quota cache, `observe`, `status --json`, Codex quota; 164 offline checks
      across four suites; merged to `master`.
- [x] Hook the local Claude Code status line to feed its payload to `flipauth claude observe`.
      Machine-local config; failures stay silent and never break the rendered status line.
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
