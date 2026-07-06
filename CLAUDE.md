# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`flipauth` is a single self-contained Bash script (`./flipauth`, ~385 lines) that swaps
saved OAuth login profiles for the official Claude Code CLI and the official Codex CLI.
There is no build step, no dependencies to install, and no package manifest — the only
runtime requirements are `bash` and `python3` (used for JSON validation and credential
inspection). Target platform is Windows WSL only.

## Commands

```sh
bash -n ./flipauth          # syntax check (lint equivalent)
./tests/parity-test.sh      # full save/activate/status/doctor coverage for both services
./tests/claude-doctor-test.sh   # Claude doctor output + token-leak assertions
```

Note `quota` is the one command that hits the network, so it has no offline unit
test; verify it manually against a live token, or point `CLAUDE_SWITCH_API_BASE`
at a stub. Its codex-rejection and profile-name validation paths are offline.

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

**Quota is the only networked command.** `flipauth claude quota [profile]` (Claude
only) sends each saved profile's OAuth access token to Anthropic's undocumented
`GET /api/oauth/usage` endpoint (base overridable via `CLAUDE_SWITCH_API_BASE`) and
prints 5-hour / 7-day rolling-window utilization plus reset countdowns. It requires
headers `anthropic-beta: oauth-2025-04-20` and `User-Agent: claude-code/<version>`
(omitting the User-Agent triggers persistent 429s; the version is read from the
installed `claude` CLI with a hardcoded fallback). Every other command is offline.
The active profile uses the live credential file (freshest token); others use their
saved snapshot and degrade to `token expired — re-activate` on 401. Codex has no
equivalent endpoint, so `cmd_quota` hard-fails for it. Keep it opt-in and
non-fatal — `quota` must never make `status`/`save`/`activate` depend on the network.

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
