# flipauth

Independent account homes for the official Claude Code and Codex CLIs on WSL.
FlipAuth chooses a home and starts the official client. The client owns login,
token refresh and provider requests. There is no gateway, token copying or quota polling.

## Model

An account name owns one configuration directory. Two accounts never share writable
credentials, sessions, databases or plugin runtime state. Both accounts can use the
same official executable. The executable's installation directory does not identify
the account: `CLAUDE_CONFIG_DIR` or `CODEX_HOME` selects the state it reads.

Three facts remain separate:

- **Initial default:** the account recorded during setup.
- **Selection:** the preference used by subsequent `account current` launches.
- **Running processes:** observed PIDs and homes, which can differ from the selection.

Names and file presence do not prove the authenticated provider identity. Check that
identity in the official client. `status` never reads tokens or makes provider requests.

## Requirements and installation

Use the official Linux CLIs in Windows WSL, Bash and Python 3.11+. Keep this checkout
and its `lib/` directory together. A symlink to `flipauth` is sufficient; no build,
Python packages, server or background service is installed.

```sh
ln -s "$HOME/projects/flipauth/flipauth" "$HOME/.local/bin/flipauth"
```

Session replacement needs local Herdr. Stopping an existing managed Codex daemon also
requires Linux/Python pidfd support. Native Windows and macOS are outside the supported scope.

## Register and log in

Register an existing home without copying or changing its contents:

```sh
flipauth codex account add primary "$HOME/.codex" --default
flipauth claude account add primary "$HOME/.claude" --default
```

Create and log into another account through the official client:

```sh
flipauth cod secondary login
flipauth cc secondary login
```

`cod` means Codex; `cc` means Claude Code. Full service names work too. A new home is
`~/.codex-<name>` or `~/.claude-<name>`. An existing unregistered directory is refused;
register it explicitly instead of letting a launcher claim it. Login does not change
the selection or restart existing processes.

Existing homes must belong to you and must not be writable by group or other users.
FlipAuth refuses unsafe permissions and does not change them automatically.

For a remote Codex login, pass native login arguments after `--`:

```sh
flipauth cod secondary login -- --device-auth
```

`flipauth cc new secondary` creates a fresh home without logging in. It inherits no
rules, hooks, plugins or permission grants. To copy reviewed configuration only:

```sh
flipauth claude account add secondary "$HOME/.claude-secondary" --create --template /absolute/reviewed-template
```

A template may contain only `CLAUDE.md` and `settings.json` for Claude, or `AGENTS.md`
and `config.toml` for Codex. Credentials and runtime state are never copied. Codex
homes must use file credential storage; keyring-backed shared storage is refused.

## Launch or switch

Run a particular account without changing selection or touching other processes:

```sh
flipauth codex account run secondary --
flipauth claude account run secondary --
```

Launch the current selection:

```sh
flipauth codex account current --
```

Explicitly switch all same-service CLI sessions, including busy sessions:

```sh
flipauth cod secondary
flipauth cc primary
```

If no same-service process exists, this selects the home and starts the official CLI
in the current terminal. Otherwise, a bounded detached worker preflights every existing
CLI, cancels its task, requests normal exit, verifies shutdown, commits selection,
and starts fresh conversations in the original Herdr panes and project directories.
The other service is left alone. File edits already made by interrupted tasks remain.
Cross-account conversation resume is not implemented.

The immediate output is a receipt, not completion. Inspect it with:

```sh
flipauth cod status
flipauth cc status --json
```

Status shows selection, initial default, login-file presence, observed PID/home/account
associations and the last switch receipt. It warns when observed homes differ from
selection. `complete` means every target was rechecked as a new process in the target
home; it does not mean provider identity, UI readiness or a request was verified.

Unknown or unmanaged processes cause refusal before stopping any session. Herdr is
used for pane ownership and normal terminal interaction, not as an account identity
source. Unrecognized/blocked UI is never answered automatically. Only exactly verified
Codex managed daemons receive SIGTERM, after the TUIs exit; SIGKILL is never used.
Uncertain command delivery is read back, not repeated. A failed restart can leave some
panes stopped and selection committed; read its receipt before deciding on recovery.

Directory Codex launches use `--no-daemon`, avoiding reuse of a server's cached login.
A pre-existing daemon is not stopped by an ordinary launch. Each launch uses the
stable official executable entry, allowing normal upgrades, and sets a child-scoped
`HERDR_AGENT` hint so a version-named native binary remains recognizable to Herdr.

## Optional commands

A fixed account launcher never switches other sessions:

```sh
flipauth codex account bind secondary "$HOME/.local/bin/codex-secondary"
```

To make plain `codex` follow the selection, stage a separate wrapper:

```sh
mkdir -p "$HOME/.local/flipauth/bin" && flipauth codex account bind-current "$HOME/.local/flipauth/bin/codex"
```

Review it, then put that directory before the official CLI on PATH in your shell.
Use the same procedure for `claude`. Existing files and symlinks are never replaced.
Without the wrapper, plain native commands do not consult FlipAuth selection.

Binding records the stable official executable in the registry for every entrypoint.
It does not write a release-number path into the wrapper. PATH discovery skips FlipAuth
wrappers, so installing one does not break direct `account run/login` calls.

| Variable | Meaning |
|---|---|
| `FLIPAUTH_ACCOUNTS_DIR` | Registry and receipts; default `~/.local/state/flipauth` |
| `FLIPAUTH_CODEX_BIN` | Explicit official Codex entry; prefer its stable symlink |
| `FLIPAUTH_CLAUDE_BIN` | Explicit official Claude entry; prefer its stable symlink |
| `FLIPAUTH_SWITCH_STOP_TIMEOUT` | Per-target stop/start deadline, 1–60 seconds |

Registry names, executable paths and configuration provenance contain no credentials.
Keep local account labels and notes out of this public repository.

## Isolation boundary

Supported directory authentication is local Claude subscription login and Codex
file-backed login. Known API-key, federation, profile, alternate-provider, remote-server
and storage overrides are refused rather than silently redirected. Templates receive
the same checks. Project/system policy, plugins, hooks and future official CLI changes
remain owned by the official client; this is not its complete policy evaluator or an
OS sandbox. Do not treat it as protection against untrusted code under your user ID.

Claude Console sign-ins without an API key are stored outside the configuration home
and cannot be isolated this way; see [Claude's multiple-account documentation](https://code.claude.com/docs/en/authentication#log-in-with-multiple-accounts).
Use the official client's account display to verify the account before real use.

## Snapshot mode retired

`save`, snapshot activation, global `login`, `quota`, `doctor` and `legacy` no longer
operate. The `claude-switch` and `codex-switch` aliases refuse old snapshot commands;
they accept explicit `account ...` commands only. Existing snapshot files are left
untouched and never imported. Register an existing independent home or log into a
new one through the official client. Historical behavior is documented in
[legacy-snapshots.md](docs/legacy-snapshots.md).

Existing `flipauth claude observe` statusLine calls are silent no-ops. They make no
request and write no cache. Configure native statusLine behavior within each home
as desired. Magpie residual-data cleanup remains a separate, manually invoked helper:
`bash scripts/cleanup-magpie.sh` previews; its explicit `--apply` archives data.

## Development

```sh
bash tests/run-all.sh
```

All active suites use disposable homes and fake CLIs/Herdr. They cover directory
ownership, native launch behavior, wrappers on PATH, executable upgrades, process
facts, managed daemon ownership and session replacement. They never log into an
account or stop real agent processes. Removed snapshot/quota features are tested
for refusal rather than by retaining their old implementation.

## 简体中文

FlipAuth 为每个账号指定独立目录，启动原生 Claude Code 或 Codex。登录、刷新和请求
由官方客户端完成。`account run` 单独启动指定账号；`cod/cc NAME` 明确切换同服务全部
会话。`status` 分别显示启动选择和实际进程目录，不把账号标签当成真实身份验证。
不使用网关，不复制凭据，不查询配额，不自动安装 PATH 包装或修改已有登录。

## License

[MIT](LICENSE).
