# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`flipauth` is a single self-contained Bash script (`./flipauth`, ~910 lines) that swaps
saved OAuth login profiles for the official Claude Code CLI and the official Codex CLI.
There is no build step, no dependencies to install, and no package manifest — the only
runtime requirements are `bash` and `python3` (used for JSON validation and credential
inspection). Target platform is Windows WSL only.

## Read first

`tasks/todo.md` is the control plane — open work, and deferred work with the reason it
was deferred. Read it before starting, so a decision that was already made deliberately
does not get re-litigated.

## Commands

```sh
bash -n ./flipauth          # syntax check (lint equivalent)
./tests/parity-test.sh      # full save/activate/status/doctor coverage for both services
./tests/claude-doctor-test.sh   # Claude doctor output + token-leak assertions
./tests/claude-quota-cache-test.sh   # quota cache, observe, status --json (79 checks)
./tests/codex-quota-test.sh          # codex app-server quota path (60 checks, stubbed)
```

`quota` is the only command that reaches the network — for Claude over HTTP, for Codex by
spawning `codex app-server`. Both are stubbed, so the whole suite runs offline.

`claude-quota-cache-test.sh` starts a local `http.server` and points
`CLAUDE_SWITCH_API_BASE` at it, which also drives the 401/429/connection-failure paths
deterministically. `codex-quota-test.sh` substitutes a fake app-server via
`CODEX_SWITCH_CODEX_BIN` and uses it to assert the things a live account cannot show:
that each profile is read from a throwaway `CODEX_HOME`, that snapshots are never
mutated, and that a server-initiated token refresh is declined rather than answered.
Both suites compare the stub's call log before and after `status` / `status --json` /
`observe` to prove those issue no request at all. Only a real end-to-end run still needs
live credentials.

Run a single test by invoking its script directly — tests are plain Bash with a `check`
helper, not a framework. They drive the real script in an isolated `mktemp -d` sandbox by
overriding `CLAUDE_SWITCH_CLAUDE_DIR` / `CODEX_SWITCH_CODEX_DIR`, so they never touch your
real `~/.claude` or `~/.codex`. Override the script under test with `FLIPAUTH_BIN_DIR`.

The script invokes itself under different names via the `claude-switch` / `codex-switch`
symlinks in the repo root; tests call those symlinks directly to exercise name dispatch.

## Architecture

**Name-based service dispatch.** The same script handles both services. `$0`'s basename
selects the service: `claude-switch` → claude, `codex-switch` → codex, and bare `flipauth`
takes the service as its first argument. This happens once at the top of the file and sets
`SERVICE`, after which the two services differ only by data, not by code path.

**Index-aligned arrays describe the managed files.** Per service, `ACTIVE[]` (live file
paths), `SUFFIX[]` (saved-profile filename suffix), and `REQUIRED[]` ("yes"/"no") are filled
in parallel. Claude has one required file (`.credentials.json`); Codex has two — a required
`auth.json` and an optional `.credentials.json`. Every operation (`save`, `activate`,
`validate`, `doctor`) loops over these array indices, so adding or changing a managed file
means editing the array declarations, not the command logic. `ACTIVE[0]` is treated as the
primary file (e.g. profile listing globs on `SUFFIX[0]`).

**State layout.** Saved profiles live under `$STATE_DIR` (default `~/.<svc>/oauth-accounts/`)
as `<profile>.<suffix>`. A `.active-profile` marker file records which profile is live.
Directories are mode `700`, files mode `600`.

**Atomic, validated swaps.** `atomic_copy` writes to a `mktemp` temp file then `mv -f` into
place (never a partial write). Credentials are validated *before* save and *before* load:
Claude requires a top-level JSON object with a `claudeAiOauth` object and allows additional
Claude-managed OAuth blocks such as `designOauth`; Codex accepts any JSON object.
`cmd_activate` auto-saves the currently-live credentials back into the outgoing profile
before loading the new one, so an in-progress token refresh is never silently lost.

**Quota is the only networked command.** `flipauth claude quota [profile]`
sends each saved profile's OAuth access token to Anthropic's undocumented
`GET /api/oauth/usage` endpoint (base overridable via `CLAUDE_SWITCH_API_BASE`) and
prints 5-hour / 7-day rolling-window utilization plus reset countdowns. It requires
headers `anthropic-beta: oauth-2025-04-20` and `User-Agent: claude-code/<version>`
(omitting the User-Agent triggers persistent 429s; the version is read from the
installed `claude` CLI with a hardcoded fallback). Every other command is offline.
The active profile uses the live credential file (freshest token); others use their
saved snapshot and degrade to `token expired — re-activate` on 401. Codex has its own
path (below) rather than an HTTP endpoint. Keep quota opt-in and non-fatal for both —
it must never make `status`/`save`/`activate` depend on the network.

**The quota cache separates observation from authorisation.** Every successful usage
response is merged into `$STATE_DIR/.quota-cache.json` (schema `1`, mode `600`, atomic
`mkstemp` + `os.replace`), and `cmd_status` replays it with zero network calls. Four
invariants are load-bearing and all four have tests:

1. *Allow-list, not filter.* `sample_of` builds the entry field by field — `fetched_at`,
   `source`, and each window's `utilization`/`resets_at`. Never copy the raw response
   through; a token must not be able to reach the cache by being added upstream.
2. *Merge, never replace.* A single-profile query updates only that profile's entry, and
   `write_cache` is a no-op when nothing succeeded, so a 401/429/offline run preserves
   the last good sample instead of erasing it.
3. *A cached percentage is a lower bound, printed as `≥N%`.* Windows have fixed reset
   times, so usage can only have grown since the sample. This is enough to rule an
   account out and never enough to authorise starting one — only a live `quota` call can
   do that. Do not "improve" this into a bare `N%`.
4. *An expired window is `unknown`, not a stale number.* If `resets_at` has passed (or
   is missing/unparseable), the window degrades to `unknown` / `—`. Showing the old
   percentage would be actively misleading.

Degradation is one-directional: a missing, corrupt, or unknown-schema cache prints a
single note and leaves the active/saved lines — and `save`/`activate`/`doctor` — intact.
Codex's `status` never renders this block.

**Two writers feed one cache; `observe` is the cheap one.** `quota` pays a network
request. `observe` reads a Claude Code statusLine payload on stdin — Claude Code already
hands the same two windows to the configured status-line command on every render — and
writes the same schema-1 entries with `source: "statusline"`. Consequences worth keeping:

- The two writers duplicate the merge-and-atomically-write logic in separate Python
  heredocs. They must stay format-compatible; the test suite asserts a cache written by
  one is read and merged by the other, which is the guard that actually matters.
- `observe` runs inside a shell prompt, so it is **silent on every failure** and skips
  writes while values are unchanged and the sample is under `OBSERVE_MIN_INTERVAL`
  seconds old. Never make it print, prompt, or exit non-zero on bad input.
- statusLine reports `resets_at` as a unix epoch and `used_percentage` on the same 0-100
  scale as the endpoint's `utilization`. `observe` normalises the timestamp to ISO so one
  cache never holds two time formats.
- Attribution is by `.active-profile` alone. The payload carries no account identity and
  Claude credentials carry no account identifier, so there is deliberately **no
  cross-check** — do not invent one from the credential file hash, which changes on every
  token refresh and would only produce false alarms.

**Codex quota goes through the app-server, and three protocol facts make it safe.**
There is no HTTP usage endpoint; the data is behind the JSON-RPC method
`account/rateLimits/read` on `codex app-server --stdio`. Each of these is load-bearing:

1. *`CODEX_HOME` relocates the config root.* Every profile is read from a throwaway copy
   of its snapshot (dir `700`, files `600`), and nothing is ever copied back. A query
   therefore cannot mutate a saved profile or activate an account. Tests assert the temp
   home is never the real Codex dir or the state dir. That copy is a real credential, so
   it must not outlive the query, and three separate things are needed to guarantee it:

   - The Python reader runs as a **background job** with a bash `trap` forwarding
     TERM/INT/HUP to it. Without that the child is merely orphaned when flipauth is
     killed: it keeps querying, with the credential copy still on disk, after the command
     the user killed has exited.
   - The Python signal handler bails **once**. A second signal — and there usually is one,
     since the shell forwards what it received — would otherwise raise again from inside
     the `finally` and abort it *before* `rmtree`, stranding exactly the copy the handler
     exists to remove. This was a real bug; the accompanying test sends two signals.
   - SIGKILL cannot be caught, so each run first sweeps `.codex-quota-*` directories it
     owns that are older than five minutes. That floor is what stops the sweep from
     deleting a concurrent run's live directory — do not lower it without revisiting that.

   Cleanup is not instantaneous: the app-server is terminated before its `CODEX_HOME` is
   removed. Tests poll for the directory to drain rather than asserting on the same tick.
2. *`account/chatgptAuthTokens/refresh` is a server→client request.* The app-server does
   not refresh tokens itself — it asks the connected client to do it and hand the new
   token back. flipauth **declines** it, so no rotation can happen on this path. A test
   drives a stub that issues the request and asserts flipauth answers with an error and
   never with a result. Do not "helpfully" implement that handler.
3. *Windows are identified by `windowDurationMins`, never by `primary`/`secondary`.*
   Those names are ordinal, not semantic: until 2026-07 `primary` was the 5-hour window;
   it is now the 7-day one and `secondary` is null. Keying on the field name would
   silently mislabel the data the next time the backend's window set changes. This is
   also why the Codex cache holds a `windows` **list** keyed by duration rather than the
   two fixed keys the Claude cache uses — the two services keep separate cache files
   (they already live in separate state dirs) precisely so Claude's shape is not forced
   onto Codex.

`usedPercent` is on a 0-100 scale — verified empirically, not inferred from the name:
`100.0` appears in recorded session history. `rateLimitResetCredits` from the same
response is surfaced too; its expiry is rendered in **local** time because it is a
deadline the operator acts on, while the cache stores UTC.

**`status --json` must agree with the text form.** It is a second rendering of the same
cache, so the lower-bound and expired-window semantics are carried in the field names:
`utilization_at_least` (never `utilization`) and `state` ∈ `known`/`expired`/`missing`.
Both services carry `quota`, but the inner shape differs because the services genuinely
differ: Claude has two named windows, Codex a variable-length `windows` list. Each service
has a test asserting its text and JSON renderings agree on every profile; those tests are
the reason the duplicated window logic is safe to keep.

**Doctor inspects without leaking.** `doctor` is a Python heredoc per service. It reports
file modes, sizes, and `sha16` hashes — never raw tokens. For Codex it decodes the JWT
*payload* (not the signature) to derive an `identity_fp`/`sub_fp` fingerprint and the access
token's expiry, and can compare the WSL identity against the Windows-side `auth.json`. For
Claude the access token is opaque (not a JWT), so doctor deliberately does **not** claim any
identity/email — the test suite asserts this. When touching doctor output, preserve the
no-token-leak and no-false-identity guarantees; both are covered by tests.

## Conventions

- **Credential shapes are load-bearing.** The Claude validator must require a valid
  `claudeAiOauth` object but preserve extra top-level OAuth blocks that the official CLI
  writes. If Anthropic changes the on-disk format again, this validator and the doctor
  parsing must change together.
- **The golden rule is a real correctness constraint, not advice:** a live `claude`/`codex`
  process holds tokens in memory and can write a stale token back over a freshly-activated
  profile. User-facing messages reinforce "start a fresh process"; keep that intent.
- **This repo is published open source.** Never commit credential files or local account
  notes. `.gitignore` already excludes the credential/runtime artifact classes plus
  `README.local.md` / `*.local.md` / `docs/local/`; keep private operator notes there.
- All behavior is configurable via the `CLAUDE_SWITCH_*` / `CODEX_SWITCH_*` environment
  variables (documented in README.md) — tests rely on this for sandboxing.
