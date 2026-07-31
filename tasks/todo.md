# todo

Short-file control plane. One line per item, newest section first. Keep operator
specifics (account labels, machine paths, real usage figures) out of this file —
they belong in ignored local notes, per README.md → *Privacy boundary*.

## In review

- [ ] **PR #1 — quota cache + offline cached quota in `status`.** Implemented, 45 offline
      checks pass. Draft; awaiting merge.
- [ ] **`docs/spend-ledger-spec.md`** — spec for `run` / `spend`. Awaiting adversarial
      review before any implementation. Open questions are listed in the spec's §8; the
      most costly one to get wrong is whether `isUsingOverage` can report a false negative.

## Next

- [ ] Remove `pic/*.png` from history. The screenshots carry real account labels, a
      hostname, a home path and a credential file hash. Must happen **after** PR #1 merges,
      or that branch is orphaned onto discarded history.
- [ ] Decide whether the spend ledger belongs in `flipauth` at all (spec §8.5). If the
      answer is no, the alternative is a standalone wrapper that both agents call.

## Deferred, with reasons

- **Automatic stop-at-threshold / account rotation.** Rejected for now, twice over: a
  utilization percentage cannot express dollars, and an automatic brake removes the
  decision from the operator rather than informing it. Revisit only if the ledger shows
  a spend pattern that manual review demonstrably cannot catch in time.
- **Branching on exhausted rate-limit states.** The vocabulary for `status` /
  `overageStatus` beyond `allowed` has not been observed. Store opaque, display verbatim,
  and let a real exhaustion event supply the answer.
- **`quota` SIGPIPE handling.** `flipauth claude quota | head` can still emit a
  `BrokenPipeError` traceback. Pre-existing, not a regression; `status` was fixed in PR #1
  because that change introduced it. Small, self-contained follow-up.

## Done

- [x] Quota cache: allow-listed fields, atomic `600` write, merge-not-replace, failures
      preserve the last good sample. (PR #1)
- [x] Cached quota in `status`: `≥N%` lower bound, expired window degrades to `unknown`,
      zero network calls, Claude-only. (PR #1)
- [x] `tests/claude-quota-cache-test.sh`: 45 checks against a local HTTP stub, which also
      gave `quota` its first offline coverage of the 401 / 429 / connection-failure paths.
