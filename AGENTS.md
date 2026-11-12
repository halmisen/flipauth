# AGENTS.md

Project rules for Claude Code, Codex and other coding agents. Read `KANBAN.md` next;
it is the only short current-state panel. Provider overlays sit below this file.

## What This Is

FlipAuth is an account-directory launcher for the official Claude Code and Codex CLIs
on Windows WSL. It never handles token contents. The official client owns login,
refresh and requests. There is no gateway, quota API, automatic rotation or daemon service.
Runtime dependencies are Bash and Python 3.11+. No build or package installation is needed.
Keep the checkout together when installing a symlink.

## Architecture

- `flipauth`: thin Bash entry, preserving invocation aliases.
- `lib/cli.py`: public dispatch and explicit retirement of snapshot commands.
- `lib/directory_accounts.py`: registry, home ownership, reviewed config, templates,
  binding and launch-plan construction.
- `lib/official_cli.py`: stable official executable discovery and `LaunchPlan`.
- `lib/process_state.py`: same-user `/proc` facts and exact managed-daemon ownership.
- `lib/short_commands.py`: current selection, status and detached switch admission.
- `lib/session_switch.py`: receipted Herdr shutdown/restart orchestration.

`LaunchPlan(service, account, home, executable, argv, env)` is the shared launch
contract for explicit run, login, current selection and switching. It preserves
cwd, PID, terminal, stdio, native arguments, signals and exit status through exec.
Validate a resolved executable for the WSL boundary, but execute/persist its stable
entry spelling. Never pin wrappers to a release-number path. Set `HERDR_AGENT` only
on the launched child, not globally. A binary's install directory is not its account.

`accounts.json` schema 1 stores canonical homes, configuration provenance, optional
stable executable entries, current selection and the separately recorded initial
default. It contains no credentials. Existing schema-1 registrations remain valid.
Use the registry writer lock for read/modify/write; writes are atomic and private.

Named homes cannot overlap across services/accounts or the registry. Creation must
explicitly choose `--bare` or a reviewed `--template`. Copy only reviewed rules and
settings: credentials, sessions, plugin runtime, writable databases and caches must
never be shared. Refuse symlinked/hardlinked runtime/config files. No automatic
cross-project configuration reuse is authorized.

Authentication is local Claude subscription login or Codex file storage. Reject known
auth/provider/remote/storage overrides at CLI/environment/config boundaries without
printing their values. The launcher is not the official project's/system's complete
policy evaluator, an OS sandbox or a guarantee of provider identity. Claude Console
OAuth without an API key uses state outside the config home and is unsupported.

## Selection, observation and switching

- `account run/login NAME` sets the home and execs the official CLI. It does not change
  selection or stop peers. Login is not a switch of an already-running process.
- `account current` reads the launch preference under the startup gate.
- `cod NAME` / `cc NAME` explicitly cancel and replace all verified same-service local
  Herdr CLI sessions, including busy ones. No cross-account conversation resume.
- Bindings use one generator and one official executable resolver. PATH discovery
  skips FlipAuth wrappers; binding records the stable official entry in the registry.
  A generated staging file is not deployment on the user's PATH.
- Status reports selection/default separately from observed PID/home/account facts.
  File presence and labels are never authenticated identity. No token reads or requests.

Read actual argv from NUL-delimited `/proc/<pid>/cmdline`, never `shlex.split(ps args)`.
Recognize native version-named Claude clients, including older running versions after
an upgrade. Match the executable, not a spoofable argv0. Codex release directories
also contain code-mode/sandbox helpers: those are not CLI sessions. Never classify
an ordinary child from inherited config-root variables or arbitrary argument text.
Preserve UID, PID birth identity and zombie handling.

A detached bounded worker survives its requesting CLI. One operation mutex serializes
switches and another startup gate prevents launches during shutdown. Preflight all
process/pane/cwd/config/login-presence ownership before cancelling any session.
Unmanaged/uninspectable processes refuse the operation before cancellation.
Cancellation precedes normal `/exit`; read back uncertain delivery without repeating.
Blocked or unfamiliar UI is never automatically answered. New conversations start in
original panes/cwds after old processes exit and selection commits.

Only exact Codex managed-daemon records (boot ID, PID start ticks, home and argv) permit
SIGTERM, only after TUIs exit, and through pidfd. Never SIGKILL or restore a daemon.
A new/unknown process blocks continuation. Validate new PID/start/home per target and
recheck all targets before `complete`. Completion proves observed process homes, not
identity, request success, readiness or future liveness. A partial restart leaves the
committed selection and a failure receipt; do not automatically roll back or retry.

## Snapshot retirement

Do not reintroduce credential copying, activation markers or direct OAuth quota calls.
Old `save/activate/login/quota/doctor/legacy` routes refuse before touching state.
`*-switch` accepts only explicit directory `account` routes. Existing files remain
untouched. `observe` is a silent no-op for old statusLine callers. Legacy documentation
and Git history are historical evidence, not runnable design or current test gates.

## Verification

```sh
bash tests/run-all.sh
python3 tests/directory-accounts-test.py
python3 tests/launcher-contract-test.py
python3 tests/observation-test.py
python3 tests/process-state-test.py
python3 tests/short-commands-test.py
python3 tests/magpie-cleanup-test.py
bash -n ./flipauth
```

Tests use private disposable HOME/registry/homes, fake CLIs/Herdr and controlled process
indexes. Never let a test discover, signal or log into a real user CLI. Preserve meaningful
checks for terminal/PID/argument behavior, concurrent ownership, native version naming,
PATH wrappers and upgrades, zombie exits/PID reuse, managed-daemon records, uncertain
admission and refusal of legacy mutations. No provider request is needed for any suite.

Offline tests do not prove real identity or a deployed entrypoint. Real login, credential
migration, peer shutdown, PATH deployment and publishing need appropriate user authority.
Never commit credentials, private labels or local account notes. Use ignored
`README.local.md`, `*.local.md`, or `docs/local/` for private operator notes.

## Work records

Short work is recorded by code, verification and Git. For expensive multi-session work,
reuse one `work/<id>/card.md` with acceptance, boundaries, resume point and closure.
Do not create another todo/journal. Read KANBAN before changing it; update for actual
scope/decision/recovery changes. Reusable prevention goes in `lessons.md` as
**When** / **Do** / **Evidence**, at most one per task.

## Shared assets

| Asset | Path | Allowed use | How to find |
|---|---|---|---|
| None declared | — | No automatic cross-project rules, skills or config reuse | Ask the owning project before adding shared assets |
