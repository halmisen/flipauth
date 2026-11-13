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

Session replacement requires Linux/Python pidfd support and a separate terminal.
Native Windows and macOS are outside the supported scope.

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

Run these commands in a separate terminal, outside any running agent's tool shell.
They preflight all same-service processes, close old CLIs, wait for exit, then stop verified managed daemon updaters and servers. A fresh official CLI
starts only in the requesting terminal and working directory. Old terminals return
to their shells. If only the target account (or nothing) is running, the command just
opens one more CLI and stops nothing; daemons are stopped only on an account change.
Subcommands such as `exec`, `login`, `mcp` and `--version` run in that account without
switching. Ctrl+C reaches all old Codex panes in parallel. The other service is
left alone; file edits already made by interrupted tasks remain.

Codex only restores its terminal when it quits from keyboard input, so old Codex CLIs
must run in Herdr panes: FlipAuth queries Herdr pane state and sends `Esc` through
`herdr agent send-keys` while Codex is `working` (interrupting active turns or
dismissing the running-task modal), then sends `Ctrl+C` until each one quits cleanly
and rejects trust/approval overlays without confirming. A Codex CLI in any other
terminal refuses the switch before anything stops; quit it yourself and retry. Old
Claude CLIs restore their terminal on SIGTERM and are closed that way from any terminal.

FlipAuth does not explicitly start a new daemon and does not force `--no-daemon`.
The new official CLI handles its normal daemon startup. Cross-account conversation
resume is not implemented. From another terminal, inspect local process facts with:

```sh
flipauth cod status
flipauth cc status --json
```

Status shows selection, initial default, login-file presence, observed PID/home/account
associations and the last switch receipt. It warns when observed homes differ from
selection. `exec-admitted` records the handoff to the official executable;
`launch_observed` separately checks the recorded PID, birth and account home.
Neither establishes provider identity, UI readiness or a successful request.

Unregistered CLI homes, uninspectable processes or unmanaged background servers
cause refusal before termination. PID reuse is checked before opening a pidfd and
again before SIGTERM. Codex CLIs are never signaled. SIGKILL is never used. Failure can leave old sessions stopped;
read the receipt before deciding on recovery. Receipts live under
`~/.local/state/flipauth/switches/`, or the configured registry directory.

A pre-existing daemon is not stopped by an ordinary `account run` launch. Each launch uses the
stable official executable entry, allowing normal upgrades, and sets a child-scoped
`HERDR_AGENT` hint so a version-named native binary remains recognizable to Herdr.

## Optional commands

A fixed account launcher never switches other sessions:

```sh
flipauth codex account bind secondary "$HOME/.local/bin/codex-secondary"
```

To make the named launcher replace old sessions instead, add `--switch` when creating
it. Existing files with different contents are refused. Deploy named switch launchers
for all registered accounts of one service, without launching or stopping anything:

```sh
bash scripts/deploy-launchers.sh codex
bash scripts/deploy-launchers.sh codex --check
```

This creates `codex-<name>` commands and leaves the plain official `codex` command alone.
Use `claude` as the script argument for Claude launchers. An existing ordinary launcher
is not silently converted into a switch command.

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
| `FLIPAUTH_SWITCH_STOP_TIMEOUT` | Per-process shutdown deadline, greater than 0 and at most 60 seconds |

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

## Troubleshooting

Inspect live state and the latest receipt before changing configuration:

```sh
flipauth cod status --json
ls -lt "$HOME/.local/state/flipauth/switches" | head
```

- **Old CLI stayed open and receipt shows `"stopped_cli": []`**: FlipAuth did not recognize that running CLI binary (not a home-directory error). Ensure `accounts.json` and `FLIPAUTH_CODEX_BIN` / `FLIPAUTH_CLAUDE_BIN` point to the stable entrypoint (such as nvm's `bin/codex`, not a release or `vendor/.../bin/codex` subpath); npm `@openai/codex` on Node 24+ uses `process.execve` into `vendor/<triple>/bin/codex`, which FlipAuth matches in `lib/process_state.py`.
- **Switch failed with `CLI did not quit after Esc/Ctrl+C`**: Read the pane screen to see which modal blocked exit. Active `working` turns require `Esc` before `Ctrl+C` because `Ctrl+C` during a turn opens Codex's `"Task is still running"` dialog and ignores further `Ctrl+C` presses.
- **Repeated folder-trust prompt (`Trust this folder?`) on a new account home**: New `--bare` homes start with an empty `[projects]` table in `config.toml`; trust each project once in Codex or add `[projects."/abs/path"]` (`trust_level = "trusted"`) in that account home's `config.toml`.
- **`a Codex CLI runs outside Herdr`**: Close headless or non-Herdr Codex sessions first so switching never leaks mouse/alternate-screen escape sequences into another terminal.

## 简体中文

FlipAuth 为每个账号指定独立目录，启动原生 Claude Code 或 Codex。登录、刷新和请求
由官方客户端完成。`account run` 单独启动指定账号；`cod/cc NAME` 明确切换同服务全部
会话（对 Herdr 内正处于 `working` 回合的 Codex 先发 `Esc` 中断，再发 `Ctrl+C` 退出）。
`status` 分别显示启动选择和实际进程目录，不把账号标签当成真实身份验证。
不使用网关，不复制凭据，不查询配额，不自动安装 PATH 包装或修改已有登录。

排查异常先执行 `flipauth cod status --json`（或 `cc`）并查看 `~/.local/state/flipauth/switches/*.json` 回执：
- 若旧进程没退且回执里 `"stopped_cli": []`，通常是 FlipAuth 的进程识别未匹配该二进制布局（如 Node 24 + npm `@openai/codex` 通过 `process.execve` 跳到 `vendor/<triple>/bin/codex`），属 FlipAuth 识别缺陷而非用户目录配错；保持 `accounts.json` 指向稳定入口 `bin/codex` 即可。
- 若新增裸目录每次提示 `Trust this folder?`，在对应账号目录 `config.toml` 的 `[projects."<项目绝对路径>"]` 写入 `trust_level = "trusted"` 即可。

## License

[MIT](LICENSE).
