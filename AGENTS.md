# AGENTS.md

Project rules for coding agents working in FlipAuth. Read `KANBAN.md` next for current state.

## What This Is

FlipAuth is an account-directory launcher for official Claude Code and Codex CLIs on Windows WSL.
It never reads or handles token contents; the official client owns login, refresh, and requests.
No gateway, quota API, automatic rotation, or daemon service.
Runtime: Bash and Python 3.11+. No build or package install; keep the checkout intact when symlinking.

## Module Map

- `flipauth`: thin Bash entry preserving invocation aliases.
- `lib/cli.py`: public dispatch and refusal of retired snapshot routes.
- `lib/directory_accounts.py`: registry, home ownership, reviewed config/templates, bindings, launch plans.
- `lib/official_cli.py`: stable official executable discovery and `LaunchPlan`.
- `lib/process_state.py`: same-user `/proc` inspection and exact managed-daemon ownership.
- `lib/short_commands.py`: current selection, status, and terminal switch admission.
- `lib/session_switch.py`: receipted CLI and managed-daemon shutdown.

## Core Invariants & Account Isolation

- **Launch contract**: `LaunchPlan(service, account, home, executable, argv, env)` is the shared contract for run, login, current selection, and switching. Preserve cwd, PID, terminal, stdio, native args, signals, and exit status via `exec`. Validate resolved executables for the WSL boundary, but execute/persist stable entry spellings (never pin release-number paths). Set `HERDR_AGENT` only on the launched child. A binary's install dir is not its account.
- **Registry**: `accounts.json` schema 1 stores canonical homes, config provenance, optional stable executable entries, current selection, and initial default (never credentials). Keep schema-1 compatibility. Use the registry writer lock for read/modify/write; writes must be atomic and private.
- **Strict home isolation (Fail-Closed)**:
  - Named homes cannot overlap across services, accounts, or the registry.
  - Creation requires explicit `--bare` or a reviewed `--template`. Copy only reviewed rules/settings; never share credentials, sessions, plugin runtime, writable DBs, or caches. Refuse symlinked/hardlinked runtime or config files. No automatic cross-project config reuse.
  - Auth is local Claude subscription login or Codex file storage only. Reject known auth/provider/remote/storage overrides at CLI/env/config boundaries without printing their values. Claude Console OAuth without an API key uses external state and is unsupported.
  - This launcher is not an OS sandbox, full policy evaluator, or guarantee of provider identity.
- **Default migration (`account migrate-default`)**: Verify zero processes in the default home before moving; keep only Codex `packages/standalone` in `~/.codex` and leave `~/.codex` without `auth.json` (Fail-Closed). Move `packages/app-server-daemon` and repoint its absolute `current` symlink. Refuse unknown packages, unsafe/uncheckable daemon symlinks, or unwritable dirs pre-move; roll back all journalled steps on any later failure (including registry write).
- **Bindings & PATH**: One binding generator and one official executable resolver (skipping FlipAuth wrappers on PATH and recording the stable entry in the registry). `bind-current` refuses to write into the official executable's or official symlink's directory so upgrades cannot overwrite it. A generated staging file is not PATH deployment.
- **Retired snapshot surface**: Never reintroduce credential copying, activation markers, or direct OAuth quota calls. `save/activate/login/quota/doctor/legacy` refuse before touching state; `*-switch` accepts only explicit `account` routes; `observe` stays a silent no-op.

## Selection, Observation & Switching

- **Non-switching commands**: `account run/login NAME`, `account current` (under startup gate), plain `codex` (or `bind-current` wrapper), and pass-through subcommands/flags (first arg only for subcommands) never stop peers or change selection. `account bind NAME PATH` creates a parallel launcher; `--switch` creates a switch launcher.
- **Switch admission (`cod NAME` / `cc NAME` / `--switch` launchers)**:
  - Requires a TTY; refuses when invoked from inside a CLI. No cross-account conversation resume or old-pane relaunch.
  - Mixed-account state (`selected == NAME` with other-home processes running) refuses in preflight without stopping anything unless `--replace` is passed.
  - When `selected != NAME` or `--replace` is set, stop only verified non-target CLIs and daemons (`home != target`), keeping target-home CLIs/daemons (`kept_cli`/`kept_daemon`), then `exec` one fresh CLI in the requesting terminal and cwd.
- **Status & observation**: Report selection/default separately from observed PID/home/account facts. File presence and labels are never authenticated identity; never read tokens or make provider requests.
- **`/proc` inspection**: Read NUL-delimited `/proc/<pid>/cmdline` (never `shlex.split(ps args)`). Match the executable, not spoofable argv0. Recognize native version-named Claude binaries (including older running versions post-upgrade). Exclude Codex code-mode/sandbox helpers and ordinary children with inherited env/args. Preserve UID, PID birth identity, and zombie handling.
- **Serialization & preflight**: Hold one operation mutex and startup gate until `exec`. Preflight all PID births, registered homes, config, caller ancestry, and target login-file presence before signaling. Refuse uninspectable processes, unregistered homes, or unmanaged background servers. No detached switch worker.
- **Per-service shutdown**:
  - **Codex CLIs** (restore terminal only on keyboard quit): close in-band via Herdr `agent send-keys` only, re-checking PID birth after each foreground query and before each key (`Esc` while `agent_status == "working"`, `Ctrl+C` otherwise; on concurrent rejection wait briefly within stop deadline to confirm exit). Refuse if not in exactly one Herdr pane or headless. Never signal Codex, never write another PTY directly, never send confirming keys (`Enter`/`y`/digits).
  - **Claude CLIs** (restore terminal on `SIGTERM`): terminate exact births via pidfd `SIGTERM` and wait for exit. Recheck this per-service split after major CLI upgrades with `work/directory-launcher/native-terminal-probe.py`.
  - **Managed daemons & failure handling**: Stop verified Codex daemon updaters before servers (matched by boot ID, start ticks, home, argv). Never `SIGKILL`. Fail with a receipt if anything remains or appears; never auto-rollback/retry partial shutdown. Never explicitly start/restore a daemon or force `--no-daemon`. `exec-admitted` records handoff only; status verifies observation separately.

## Verification & Public-Repo Safety

```sh
bash tests/run-all.sh   # runs bash -n ./flipauth and all tests/*-test.py suites
```

- Run individual suites via `python3 tests/<suite>-test.py` (`directory-accounts`, `launcher-contract`, `observation`, `process-state`, `short-commands`, `magpie-cleanup`) and `bash -n ./flipauth`.
- Tests must use private disposable HOME/registry/homes, fake CLIs, and controlled process indexes. Never discover, signal, or log into a real user CLI, and make no provider requests.
- Offline tests do not prove real identity or deployed PATH entrypoints. Real login, credential migration, peer shutdown, PATH deployment, and publishing require explicit user authority.
- **Public repo privacy red line**: Never commit credentials, private labels, or local account notes. Keep private operator notes in gitignored `README.local.md`, `*.local.md`, or `docs/local/`.
- For expensive multi-session work, track state in one `work/<id>/card.md` (do not create separate todos/journals).

## Shared assets

| Asset | Path | Allowed use | How to find |
|---|---|---|---|
| None declared | — | No automatic cross-project rules, skills or config reuse | Ask the owning project before adding shared assets |
