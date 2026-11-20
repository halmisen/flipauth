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

Explicitly switch away from other-account same-service CLI sessions, including busy sessions:

```sh
flipauth cod secondary
flipauth cc primary
```

Run these commands in a separate terminal, outside any running agent's tool shell.
When switching to a different selection (`selected != target`) or passing `--replace`,
they preflight all same-service processes, close only other-home CLIs (`home != target`),
wait for exit, then stop only verified other-home managed daemon updaters and servers,
while preserving any already-running target-home CLIs and target-home daemons
(recorded under `kept_cli`/`kept_daemon` in the receipt). A fresh official CLI
starts only in the requesting terminal and working directory. Old terminals return
to their shells. If only the target account (or nothing) is running, the command just
opens one more CLI and stops nothing; daemons are stopped only when other-home processes exist.
If the target is already selected (`selected == target`) while other-home processes are
running, the switch command refuses in preflight without stopping anything: run plain
`codex`/`claude` (with `bind-current`) or `flipauth <service> account run <name> --` to
open another session without disturbing peers, or pass `--replace` (for example
`codex-primary --replace` or `flipauth cod primary --replace`) to stop only the
other-home sessions.
Subcommands such as `exec`, `login`, `mcp` and `--version` run in that account without
switching. Ctrl+C reaches all old other-home Codex panes in parallel. The other service is
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

Or use the idempotent deployment/verification helper (which binds `~/.local/flipauth/bin/<service>`,
adds the PATH block to `~/.bashrc` and `~/.profile`, migrates any legacy `# flipauth current launcher`
file out of `~/.local/bin/<service>` into `~/.local/state/flipauth/launcher-backups/<timestamp>/`
without touching real official binaries/symlinks, and prints `status`):

```sh
bash scripts/deploy-current.sh [codex|claude|all] [--check]
```

Review it, then put that directory before the official CLI on PATH in your shell.
Use the same procedure for `claude`. Existing files and symlinks are never replaced, and
`bind-current` refuses to write into the official binary's or official symlink's directory
(such as `~/.local/bin` when `~/.local/bin/codex` is the official symlink) so provider
upgrades cannot overwrite the wrapper. Without the wrapper, plain native commands do not
consult FlipAuth selection.

To make the default home (`~/.codex` or `~/.claude`) Fail-Closed so an accidental un-wrapped
launch cannot silently use a registered account's credentials, move that default-home account
into a dedicated directory once no processes are using the default home:

```sh
flipauth codex account migrate-default primary "$HOME/.codex-primary" --dry-run
flipauth codex account migrate-default primary "$HOME/.codex-primary"
```

`migrate-default` verifies zero same-service processes are running in the default home,
moves account state with same-filesystem renames without reading credentials, updates
`accounts.json`, and (for Codex) keeps only `~/.codex/packages/standalone` in place so
standalone symlinks such as `~/.local/bin/codex` remain intact while `~/.codex` has no
`auth.json`. The per-home `packages/app-server-daemon` moves with the account, and its
absolute `current` symlink is repointed at the same release under the new home (matching
both the literal `~/.codex` spelling and its resolved path); otherwise Codex reports the
daemon executable missing.

The migration is all-or-nothing. Before anything moves it refuses on: unwritable source,
target or daemon directories; unknown package kinds; daemon symlinks that leave the daemon
package (absolute links into the old home, relative links such as `../standalone`); and
daemon subdirectories it cannot read. Every rename and symlink rewrite is journalled; if a
later step fails (including the final registry write, or a moved link that no longer
resolves where expected) the journal is undone in reverse and the command reports
`rolled back, nothing changed`, so fixing the cause and rerunning starts cleanly. Only if
the rollback itself fails does it report `rollback is INCOMPLETE` with the steps to restore
by hand; the registry still points at the default home in that case.

While files move, SIGINT/SIGTERM/SIGHUP/SIGQUIT are recorded rather than acted on, so a
signal never lands between a step and its journal entry. The last abort check runs after the
new registry content is staged and immediately before its atomic replace (the commit point):
a signal recorded by then aborts and rolls back; a later one lets the finished migration
print its result and then exits with status 128+signal. If a failure is reported around the
replace, the staged file's inode decides: replaced means the migration is kept and reported
as committed; not replaced means rollback; if the registry cannot even be stat'ed, nothing is
rolled back and the commit state is reported as `UNKNOWN` for manual inspection. SIGKILL or a power loss cannot be
deferred and may leave a partial move; the registry then still names the default home, and
the moved entries are under the target directory.

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
由官方客户端完成。`account run` 单独启动指定账号；`cod/cc NAME` 仅关闭非目标账号的
同服务会话与 daemon（保留已运行的目标账号会话，对 Herdr 内正处于 `working` 回合的
Codex 先发 `Esc` 中断，再发 `Ctrl+C` 退出）；若目标账号已是当前选中且场上仍有异号进程，
默认预检拒绝而不停任何进程，可用裸命令 / `account run` 直接加开或显式传 `--replace` 清场。
`bind-current` 必须放在独立优先目录（如 `~/.local/flipauth/bin/`），禁止写入官方二进制或官方软链目录以防升级覆写；
`account migrate-default <name> <new-dir>` 可在默认目录无进程运行时将默认目录账号迁至独立目录（Codex 只保留 `~/.codex/packages/standalone` 不断链；按 home 分装的 `packages/app-server-daemon` 随账号迁走，其绝对软链 `current` 改指新目录下同一 release；遇未知包类型或指向旧目录其他位置的 daemon 软链则迁移前拒绝），使默认目录无 `auth.json` 实现 Fail-Closed。迁移全有或全无：移动前预检源/目标/daemon 目录可写、daemon 软链不越出 daemon 包（含指向旧目录根的绝对链、`../standalone` 类相对链）、子目录可读，否则拒绝且零移动；移动中任一步（含最后的注册表写入、迁后软链解析校验）失败即按日志逆序回滚并报 `rolled back, nothing changed`，修复原因后可直接重跑；仅回滚本身失败时报 `rollback is INCOMPLETE` 并列出手工恢复步骤，此时注册表仍指向默认目录。搬移期间 SIGINT/SIGTERM/SIGHUP/SIGQUIT 只记录不立即生效：最后一次中止检查在新注册表内容暂存后、原子替换（提交点）前，此前收到则中止并回滚，此后收到则让已完成的迁移输出结果后以 128+信号值退出；替换前后报错时按暂存文件 inode 判定：已替换则保留迁移并报已提交，未替换才回滚，注册表连 stat 都失败则不回滚并报 `UNKNOWN` 待人工核对；SIGKILL 或断电无法延后，可能留下半迁移（注册表仍指向默认目录，已移条目在目标目录下）。
`status` 分别显示启动选择和实际进程目录，不把账号标签当成真实身份验证。
不使用网关，不复制凭据，不查询配额，不自动安装 PATH 包装或修改已有登录。

排查异常先执行 `flipauth cod status --json`（或 `cc`）并查看 `~/.local/state/flipauth/switches/*.json` 回执：
- 若旧进程没退且回执里 `"stopped_cli": []`，通常是 FlipAuth 的进程识别未匹配该二进制布局（如 Node 24 + npm `@openai/codex` 通过 `process.execve` 跳到 `vendor/<triple>/bin/codex`），属 FlipAuth 识别缺陷而非用户目录配错；保持 `accounts.json` 指向稳定入口 `bin/codex` 即可。
- 若新增裸目录每次提示 `Trust this folder?`，在对应账号目录 `config.toml` 的 `[projects."<项目绝对路径>"]` 写入 `trust_level = "trusted"` 即可。

## License

[MIT](LICENSE).
