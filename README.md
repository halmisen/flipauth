<div align="center">

# flipauth

**One command to switch between multiple OAuth logins for the official Claude Code and Codex CLIs — safely, atomically, and without re-authenticating every time.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Platform: WSL](https://img.shields.io/badge/platform-Windows%20WSL-blue.svg)
![Dependencies: bash + python3](https://img.shields.io/badge/deps-bash%20%2B%20python3-lightgrey.svg)

English · [简体中文](#简体中文)

</div>

---

## Why flipauth?

The official `claude` and `codex` CLIs each store a single live OAuth credential on
disk. If you work across more than one account — personal and work, two
subscriptions, a client's tenant — switching means logging out and logging back in
every single time, and you lose the other session in the process.

`flipauth` keeps a named snapshot of each login and swaps the live credential in place
on demand. Switching accounts becomes one command and takes a fraction of a second, no
browser round-trip required.

It also answers the question every multi-account user actually has — **"which account
still has quota left?"** — by reading Claude's own usage windows for every saved
profile at once.

## Features

- 🔁 **Instant profile switching** for both Claude Code and Codex from one tiny script.
- 📸 **Named snapshots** of each OAuth login, stored locally with strict `600`/`700` permissions.
- 🔒 **Atomic, validated swaps** — credentials are shape-checked before every save and load, and written via temp-file-then-rename so a crash never leaves a half-written file.
- 📊 **Quota at a glance** — see the 5-hour and 7-day usage windows (and reset countdowns) for **all** your Claude profiles side by side.
- 🗂️ **Offline quota recall** — every live quota check is cached, so `status` can show each profile's last known usage without touching the network, even for profiles whose saved token has since expired.
- 🔌 **Free, continuous refresh** — hook `observe` onto your Claude Code status line and the active profile's cache stays current from data Claude Code already gives you, with no network request and no extra cost.
- 🤖 **`status --json`** for scripts and agents that must pick a profile before dispatching work.
- 🩺 **`doctor` diagnostics** that fingerprint credentials and compare WSL vs. Windows-side Codex identity — without ever printing a raw token.
- 🪪 **Login helper** for Claude that authenticates straight into a named profile.
- 🧰 **Zero install footprint** — a single Bash script; the only requirements are `bash` and `python3`.

## Supported platform

Windows WSL. macOS and native Windows are not supported or tested.

## What it does

`flipauth` copies your live credential file(s) into per-profile snapshots, then swaps
them atomically when you activate a different profile. `status`, `doctor`, and `quota`
let you inspect the current state at any time.

| Service | Live files | Saved profile directory |
|---|---|---|
| Claude Code | `~/.claude/.credentials.json` | `~/.claude/oauth-accounts/` |
| Codex | `~/.codex/auth.json`, optional `~/.codex/.credentials.json` | `~/.codex/oauth-accounts/` |

## ⚠️ Golden rule

**Exit the running `claude` or `codex` process before switching profiles.**

A live CLI process keeps tokens in memory. If you swap files while that process is
still alive, it can write its old in-memory token back to disk and overwrite the
profile you just activated.

## Install

Clone the repo and put `flipauth` on your `PATH`:

```sh
git clone https://github.com/halmisen/flipauth.git ~/flipauth
mkdir -p ~/.local/bin
ln -s ~/flipauth/flipauth ~/.local/bin/flipauth
```

Optional shorthand commands can point to the same file:

```sh
ln -s ~/flipauth/flipauth ~/.local/bin/claude-switch
ln -s ~/flipauth/flipauth ~/.local/bin/codex-switch
```

Check that it worked:

```sh
flipauth claude doctor
```

If your shell reports `command not found`, `~/.local/bin` is not on your `PATH`.
Add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` (or `~/.zshrc`) and open
a new terminal. Avoid `~/bin` for this: on Debian/Ubuntu the default `~/.profile`
only adds it when the directory already existed at login, so a freshly created
`~/bin` stays off your `PATH` until you log in again.

## Quick start

```sh
# 1. Log into your first account with the official CLI, then snapshot it.
claude            # (log in as usual, then exit the session)
flipauth claude save work

# 2. Log into a second account and snapshot that one too.
flipauth claude login personal      # authenticates straight into a named profile

# 3. Switch any time (exit claude first!).
flipauth claude personal
claude

# 4. See where you stand.
flipauth claude status
flipauth claude quota
```

## Usage

Use the explicit form:

```sh
flipauth claude status
flipauth codex status
```

Or use optional shorthand symlinks:

```sh
claude-switch status
codex-switch status
```

`flipauth` dispatches on the program name used to invoke it:

| Invocation | Service resolved |
|---|---|
| `flipauth claude <cmd>` | Claude Code |
| `flipauth codex <cmd>` | Codex |
| `claude-switch <cmd>` | Claude Code |
| `codex-switch <cmd>` | Codex |

## Commands

Save the currently active credentials as a named profile:

```sh
flipauth claude save <profile>
flipauth codex save <profile>
```

Activate a saved profile:

```sh
flipauth claude <profile>
flipauth codex <profile>
```

Show active profile and saved profiles. For Claude this also prints the last cached
quota sample for each profile, entirely offline:

```sh
flipauth claude status
flipauth codex status
```

The same data as machine-readable JSON, for scripts and agents:

```sh
flipauth claude status --json
```

Record a rate-limit sample that Claude Code handed you for free (see *Free refresh from
the status line* below):

```sh
flipauth claude observe   # reads a Claude Code statusLine payload on stdin
```

Diagnose local credential state:

```sh
flipauth claude doctor
flipauth codex doctor
```

Show subscription usage (5-hour and 7-day rolling windows) for every saved Claude
profile, or a single one:

```sh
flipauth claude quota
flipauth claude quota <profile>
```

Log in fresh and save directly as a named profile for Claude:

```sh
flipauth claude login <profile>
```

Codex does not have a `flipauth` login helper. Log in with Codex itself, then save the
active credentials:

```sh
codex login
codex login status
flipauth codex save <profile>
```

Profile names must match:

```text
[A-Za-z0-9][A-Za-z0-9_-]*
```

## Switching flow

Claude:

```sh
# Exit any running claude session first.
flipauth claude <profile>
claude
```

Codex:

```sh
# Exit any running codex session first.
flipauth codex <profile>
codex
```

Read-only checks are safe anytime:

```sh
flipauth claude status
flipauth claude doctor
flipauth codex status
flipauth codex doctor
```

## Quota

`flipauth claude quota` is the only command that makes a network call. It sends each
saved profile's OAuth access token to Anthropic's `/api/oauth/usage` endpoint — the
same data behind Claude Code's `/usage` — and prints the 5-hour and 7-day rolling-window
utilization plus reset countdowns:

```text
  Profile     5h    resets     7d    resets
  work      100%    in 23m    64%  in 2d18h
* home       48%     in 3m    11%  in 6d11h
* = active profile
```

The active profile (`*`) is read from the live credential file; other profiles use
their saved snapshot, so a profile whose saved token has expired shows
`token expired — re-activate` instead of a number. This is a Claude-only feature; Codex
has no equivalent endpoint. The endpoint is undocumented and may change. Avoid polling
tighter than ~180s per account to stay clear of rate limiting.

### Cached quota in `status`

Every successful `quota` response is cached to `~/.claude/oauth-accounts/.quota-cache.json`
(mode `600`, written atomically). Only the two rolling windows' utilization and reset
time are stored, plus when the sample was taken and whether it came from the live
credential file or a saved snapshot. Tokens are never cached.

`flipauth claude status` then replays that cache with no network call at all:

```text
Active profile: production
Saved profiles: production scratch staging

Cached quota (offline snapshot, not live — a cached % is a lower bound):
  Profile          5h    resets       7d    resets    sampled
* production      ≥1%  in 3h19m     ≥14%   in 4d1h    12m ago
  scratch     no sample
  staging     unknown         —     ≥91%   in 2d4h  9h00m ago
* = active profile; refresh with 'flipauth claude quota'
```

Read those numbers carefully — the display is deliberately pessimistic:

- **`≥N%` is a lower bound, not a measurement.** Each window has a fixed reset time, so
  usage can only have grown since the sample. A cached `≥88%` is enough to rule an
  account out; a cached `≥1%` is *never* enough to conclude an account is free, because
  a browser session, another machine, or another process may have spent it since.
  Only a live `quota` call can justify starting an account.
- **`unknown` means the window rolled over after the sample was taken.** The old
  percentage describes an expired window and would be actively misleading, so it is
  dropped rather than shown.
- A profile with no cached sample shows `no sample`; a missing or unreadable cache
  degrades to a one-line note and never affects `save`, `activate`, `doctor`, or the
  active/saved lines above it.

A failed `quota` call (expired token, rate limit, no network) leaves the last good
sample in place instead of erasing it, and querying a single profile updates only that
profile's entry.

### Free refresh from the status line

`quota` costs a network request, so the cache is only as fresh as the last time you
remembered to run it. Claude Code, however, already hands the same two rolling windows to
your configured `statusLine` command on every render. `observe` catches that payload:

```sh
# at the end of your statusLine script, after you have read stdin into "$input"
printf '%s' "$input" | flipauth claude observe
```

If your script consumes stdin with `input=$(cat)` — the usual pattern — pipe that
variable, not stdin again.

The result is that the **active** profile's sample is always seconds old, for free. That
matters most for the profile you are about to leave: when you switch away, its cached
number is from just before the switch rather than from whenever you last ran `quota`.
`observe` and `quota` share one cache and merge into it, so you can use either or both.

Three things worth knowing:

- **It is silent and cheap by design.** Bad JSON, an absent `rate_limits` block (API-key
  users have no subscription windows), or an unwritable cache all exit quietly — breaking
  someone's shell prompt to record telemetry would be absurd. Writes are skipped while
  the values are unchanged and the sample is under a minute old
  (`OBSERVE_MIN_INTERVAL` overrides the interval).
- **Attribution follows `.active-profile`.** The status-line payload does not identify
  the account, so the sample is filed under whichever profile flipauth believes is
  active. flipauth keeps that correct when *it* performs the switch; a login performed
  outside flipauth can make it stale, and Claude credentials carry no account identifier
  to cross-check against.
- **Claude only.** Codex's status line is a built-in config list rather than a script, so
  there is nowhere to hook; `flipauth codex observe` is rejected.

### `status --json`

For scripts and agents that must choose a profile before handing it work. Strictly
offline, same data as the text form:

```json
{
  "service": "claude",
  "active_profile": "production",
  "cache": { "state": "ok" },
  "profiles": [
    { "name": "production", "active": true,
      "quota": {
        "sampled_at": "2026-07-31T08:47:32+00:00", "age_seconds": 12, "source": "statusline",
        "five_hour": { "state": "known",   "utilization_at_least": 37.4, "resets_at": "..." },
        "seven_day": { "state": "expired", "utilization_at_least": null, "resets_at": "..." }
      } },
    { "name": "scratch", "active": false, "quota": null }
  ]
}
```

The field names carry the same warning the text form carries with `≥` and `unknown`:
`utilization_at_least` is a **lower bound, never a measurement**, and `state` is one of
`known` / `expired` / `missing`. `cache.state` (`ok` / `missing` / `unreadable` /
`unsupported_schema`) lets a consumer tell "no data" apart from "broken". Codex profiles
carry no `quota` key at all — absent rather than null, because Codex has no usage
endpoint, not because it is merely unsampled.

## Windows-side Codex auth path

`flipauth codex doctor` can compare the WSL credential against the Windows-side Codex
`auth.json` to tell you whether both sides appear to be logged into the same account.

To override the Windows path:

```sh
export CODEX_SWITCH_WINDOWS_AUTH="/mnt/c/Users/<YourWindowsUser>/.codex/auth.json"
```

If the variable is unset, `flipauth` attempts auto-detection via `wslvar` or `cmd.exe`.
If detection fails, the field is reported as `not configured` and the comparison is
skipped.

## How it works

- Profiles are stored under `~/.{claude,codex}/oauth-accounts/<profile>.<suffix>`.
- Profile files are written with mode `600`; profile directories use mode `700`.
- Copies are atomic: write to a temp file, then rename into place.
- Credential JSON shape is validated before saving or loading.
- `doctor` reports short hashes and token fingerprints, not raw tokens.
- Activating a profile first re-saves the outgoing live credential, so an in-progress
  token refresh is never silently lost.
- Successful quota responses are cached to `.quota-cache.json` in the same directory so
  `status` stays offline; only quota-shaped fields are stored, never tokens.
- `observe` writes to that same cache from the payload Claude Code already pipes to your
  status line, so keeping it fresh costs no network request at all.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_SWITCH_CLAUDE_DIR` | `~/.claude` | Claude config directory |
| `CLAUDE_SWITCH_STATE_DIR` | `$CLAUDE_SWITCH_CLAUDE_DIR/oauth-accounts` | Where Claude profiles are stored |
| `CLAUDE_SWITCH_CREDENTIALS_FILE` | `~/.claude/.credentials.json` | Live Claude credential file |
| `CODEX_SWITCH_CODEX_DIR` | `~/.codex` | Codex config directory |
| `CODEX_SWITCH_STATE_DIR` | `$CODEX_SWITCH_CODEX_DIR/oauth-accounts` | Where Codex profiles are stored |
| `CODEX_SWITCH_AUTH_FILE` | `~/.codex/auth.json` | Live Codex auth file |
| `CODEX_SWITCH_CREDENTIALS_FILE` | `~/.codex/.credentials.json` | Optional live Codex credentials file |
| `CODEX_SWITCH_WINDOWS_AUTH` | auto-detect | Path to Windows-side `.codex/auth.json`; set empty to disable |
| `CLAUDE_SWITCH_API_BASE` | `https://api.anthropic.com` | Base URL for the `quota` usage endpoint |

## Safety

- Exit the live CLI before every switch.
- Save refreshed active credentials immediately after a new login.
- Do not have the same OAuth account active in two places at once.
- Do not hand-edit saved profile files unless you are deliberately repairing profiles.
- Do not commit credential files or local account notes.

## Privacy boundary

This repository is published as open source. Do not put personal account labels, email
mappings, local machine paths, private token history, or operator runbooks in this
public README. Keep local notes in an ignored file such as `README.local.md`;
`.gitignore` excludes that file class on purpose.

## Development

Basic local checks:

```sh
bash -n ./flipauth          # syntax check
./tests/parity-test.sh      # save / activate / status / doctor coverage for both services
./tests/claude-doctor-test.sh   # doctor output + token-leak assertions
./tests/claude-quota-cache-test.sh   # quota cache, observe, status --json (local stub, no network)
```

## License

MIT. See [`LICENSE`](LICENSE).

---

<div align="center">

# 简体中文

**一条命令在 Claude Code 与 Codex 官方 CLI 的多个 OAuth 账号之间切换 —— 安全、原子、无需反复登录。**

[English](#flipauth) · 简体中文

</div>

## 为什么需要 flipauth？

官方的 `claude` 和 `codex` CLI 在磁盘上各自只保存**一份**生效的 OAuth 凭据。如果你要
在多个账号之间来回切换 —— 个人和工作、两个订阅、客户的租户 —— 每次切换都得先退出登录、
再重新登录，而且会丢掉另一个会话。

`flipauth` 为每个登录保存一份命名快照，并在需要时就地替换生效凭据。切换账号变成一条
命令，瞬间完成，不需要再走一遍浏览器授权。

它还顺手回答了多账号用户真正关心的问题 —— **「哪个账号还有额度？」** —— 一次性读取
所有已保存 Claude 配置的用量窗口。

## 功能特性

- 🔁 **即时切换配置**：用一个小脚本同时管理 Claude Code 和 Codex。
- 📸 **命名快照**：本地保存每个 OAuth 登录，目录 `700`、文件 `600` 严格权限。
- 🔒 **原子且经过校验的替换**：保存和加载前都会校验凭据结构，并采用「先写临时文件再重命名」的方式写入，崩溃也不会留下写了一半的文件。
- 📊 **额度一目了然**：并排查看**所有** Claude 配置的 5 小时 / 7 天用量窗口及重置倒计时。
- 🗂️ **离线额度回看**：每次实时额度查询都会写入缓存，`status` 因此可以不联网就展示每个配置最后一次已知用量 —— 即使该配置的快照 token 早已过期。
- 🔌 **免费持续刷新**：把 `observe` 接到 Claude Code 的状态栏上，当前配置的缓存就会用 Claude Code 本来就给你的数据保持最新 —— 零网络请求，零成本。
- 🤖 **`status --json`**：给需要在派发任务前先选账号的脚本和 agent 用。
- 🩺 **`doctor` 诊断**：对凭据做指纹比对，对照 WSL 与 Windows 侧的 Codex 身份 —— 全程不打印任何原始 token。
- 🪪 **登录助手**：Claude 可直接登录并保存为命名配置。
- 🧰 **零安装负担**：单个 Bash 脚本，仅依赖 `bash` 和 `python3`。

## 支持平台

Windows WSL。不支持也未测试 macOS 与原生 Windows。

## 它做什么

`flipauth` 把你当前生效的凭据文件复制成按配置命名的快照，激活其它配置时再原子地换回去。
`status`、`doctor`、`quota` 子命令可随时查看当前状态。

| 服务 | 生效文件 | 保存配置目录 |
|---|---|---|
| Claude Code | `~/.claude/.credentials.json` | `~/.claude/oauth-accounts/` |
| Codex | `~/.codex/auth.json`，可选 `~/.codex/.credentials.json` | `~/.codex/oauth-accounts/` |

## ⚠️ 黄金法则

**切换配置前，先退出正在运行的 `claude` 或 `codex` 进程。**

正在运行的 CLI 进程会把 token 保存在内存里。如果你在进程还活着的时候替换文件，它可能把
内存里的旧 token 写回磁盘，覆盖你刚刚激活的配置。

## 安装

克隆仓库并把 `flipauth` 加入 `PATH`：

```sh
git clone https://github.com/halmisen/flipauth.git ~/flipauth
mkdir -p ~/.local/bin
ln -s ~/flipauth/flipauth ~/.local/bin/flipauth
```

可选的简写命令可以指向同一个文件：

```sh
ln -s ~/flipauth/flipauth ~/.local/bin/claude-switch
ln -s ~/flipauth/flipauth ~/.local/bin/codex-switch
```

验证安装是否成功：

```sh
flipauth claude doctor
```

如果 shell 提示 `command not found`，说明 `~/.local/bin` 不在你的 `PATH` 里。把
`export PATH="$HOME/.local/bin:$PATH"` 加进 `~/.bashrc`（或 `~/.zshrc`），然后重开
一个终端。这里不建议用 `~/bin`：Debian/Ubuntu 默认的 `~/.profile` 只在登录时该目录
已存在的情况下才会把它加入 `PATH`，所以刚创建的 `~/bin` 要等下次登录才会生效。

## 快速上手

```sh
# 1. 用官方 CLI 登录第一个账号，然后保存快照。
claude            # （照常登录，然后退出会话）
flipauth claude save work

# 2. 登录第二个账号并同样保存。
flipauth claude login personal      # 直接登录并保存为命名配置

# 3. 随时切换（记得先退出 claude！）。
flipauth claude personal
claude

# 4. 查看当前状态。
flipauth claude status
flipauth claude quota
```

## 用法

显式写法：

```sh
flipauth claude status
flipauth codex status
```

或使用可选的简写软链接：

```sh
claude-switch status
codex-switch status
```

`flipauth` 根据调用时的程序名分派服务：

| 调用方式 | 解析到的服务 |
|---|---|
| `flipauth claude <cmd>` | Claude Code |
| `flipauth codex <cmd>` | Codex |
| `claude-switch <cmd>` | Claude Code |
| `codex-switch <cmd>` | Codex |

## 命令

把当前生效的凭据保存为命名配置：

```sh
flipauth claude save <profile>
flipauth codex save <profile>
```

激活某个已保存的配置：

```sh
flipauth claude <profile>
flipauth codex <profile>
```

查看当前配置与已保存配置。Claude 还会额外打印每个配置最后一次缓存的额度快照，全程离线：

```sh
flipauth claude status
flipauth codex status
```

同样的数据，机器可读格式，供脚本和 agent 使用：

```sh
flipauth claude status --json
```

记录一次 Claude Code 免费交给你的额度采样（见下方「从状态栏免费刷新」）：

```sh
flipauth claude observe   # 从 stdin 读取 Claude Code 的 statusLine 载荷
```

诊断本地凭据状态：

```sh
flipauth claude doctor
flipauth codex doctor
```

查看每个已保存 Claude 配置（或单个）的订阅用量（5 小时与 7 天滚动窗口）：

```sh
flipauth claude quota
flipauth claude quota <profile>
```

直接登录并保存为命名的 Claude 配置：

```sh
flipauth claude login <profile>
```

Codex 没有 `flipauth` 登录助手。请用 Codex 自身登录后再保存当前凭据：

```sh
codex login
codex login status
flipauth codex save <profile>
```

配置名必须匹配：

```text
[A-Za-z0-9][A-Za-z0-9_-]*
```

## 切换流程

Claude：

```sh
# 先退出正在运行的 claude 会话。
flipauth claude <profile>
claude
```

Codex：

```sh
# 先退出正在运行的 codex 会话。
flipauth codex <profile>
codex
```

只读检查随时安全：

```sh
flipauth claude status
flipauth claude doctor
flipauth codex status
flipauth codex doctor
```

## 额度（Quota）

`flipauth claude quota` 是唯一会发起网络请求的命令。它把每个已保存配置的 OAuth access
token 发送到 Anthropic 的 `/api/oauth/usage` 接口（即 Claude Code 的 `/usage` 背后的
数据），打印 5 小时与 7 天滚动窗口的用量百分比及重置倒计时：

```text
  Profile     5h    resets     7d    resets
  work      100%    in 23m    64%  in 2d18h
* home       48%     in 3m    11%  in 6d11h
* = active profile
```

当前生效配置（`*`）读取的是生效凭据文件；其它配置使用各自的快照，因此快照 token 已过期
的配置会显示 `token expired — re-activate` 而不是数字。这是 Claude 专属功能，Codex 没有
对应接口。该接口未公开，可能随时变动。请勿对同一账号以快于约 180 秒的频率轮询，以免触发
限流。

### `status` 里的缓存额度

每次成功的 `quota` 响应都会写入 `~/.claude/oauth-accounts/.quota-cache.json`（权限 `600`，
原子写入）。缓存里只有两个滚动窗口的用量百分比与重置时间，外加采样时刻和该样本取自生效
凭据文件还是保存的快照。**永远不缓存 token。**

`flipauth claude status` 随后完全不联网地回放这份缓存：

```text
Active profile: production
Saved profiles: production scratch staging

Cached quota (offline snapshot, not live — a cached % is a lower bound):
  Profile          5h    resets       7d    resets    sampled
* production      ≥1%  in 3h19m     ≥14%   in 4d1h    12m ago
  scratch     no sample
  staging     unknown         —     ≥91%   in 2d4h  9h00m ago
* = active profile; refresh with 'flipauth claude quota'
```

这些数字要按字面读 —— 展示方式是刻意保守的：

- **`≥N%` 是下界，不是测量值。** 每个窗口有固定的重置时刻，因此在同一窗口内用量只增不减。
  缓存里的 `≥88%` 足以**排除**一个账号；缓存里的 `≥1%` **永远不足以**断定这个账号还空着 ——
  浏览器会话、另一台机器或另一个进程都可能在采样之后把额度用掉了。只有实时 `quota` 查询
  才能授权启动某个账号。
- **`unknown` 表示该窗口在采样之后已经重置过。** 旧百分比描述的是一个已经作废的窗口，
  与其误导不如不显示。
- 没有缓存样本的配置显示 `no sample`；缓存缺失或损坏时只降级成一行说明，绝不影响
  `save`、`activate`、`doctor`，也不影响它上方的当前配置与已保存配置两行。

失败的 `quota` 查询（token 过期、限流、断网）会保留上一次成功的样本而不是抹掉它；
只查询单个配置时也只更新该配置的条目。

### 从状态栏免费刷新

`quota` 要发一次网络请求，所以缓存的新鲜度取决于你还记不记得跑它。但 Claude Code 每次
渲染状态栏时，**本来就把同样这两个滚动窗口交给了你配置的 `statusLine` 命令**。`observe`
把这份载荷接住：

```sh
# 在你的 statusLine 脚本末尾，在已经把 stdin 读进 "$input" 之后
printf '%s' "$input" | flipauth claude observe
```

如果你的脚本用 `input=$(cat)` 读取 stdin（常见写法），请把这个变量管道过去，不要再读一次
stdin。

效果是：**当前配置**的样本永远只有几秒钟大，而且免费。这一点对你**即将切走**的那个配置
最有价值 —— 切换之后，它的缓存数字来自切换前一刻，而不是你上次想起来跑 `quota` 的时候。
`observe` 和 `quota` 共用同一份缓存并合并写入，两者可以只用一个，也可以都用。

三件需要知道的事：

- **它被设计成安静且廉价。** JSON 损坏、载荷里没有 `rate_limits`（API key 用户没有订阅
  窗口）、缓存写不进去 —— 全都安静退出。为了记一条遥测而弄坏别人的 shell 提示符是荒唐的。
  数值没变且样本不到一分钟时会跳过写入（`OBSERVE_MIN_INTERVAL` 可覆盖该间隔）。
- **归属依据是 `.active-profile`。** 状态栏载荷**不包含账号身份**，所以样本会记在 flipauth
  认为当前生效的那个配置名下。flipauth 自己执行切换时这个标记是准的；绕过 flipauth 重新
  登录会让它过时，而 Claude 凭据里没有任何账号标识可供交叉验证。
- **仅限 Claude。** Codex 的状态栏是内置配置项而非可执行脚本，没有地方挂钩子；
  `flipauth codex observe` 会被拒绝。

### `status --json`

给需要在派发任务前选定配置的脚本和 agent 使用。严格离线，数据与文本形式一致：

```json
{
  "service": "claude",
  "active_profile": "production",
  "cache": { "state": "ok" },
  "profiles": [
    { "name": "production", "active": true,
      "quota": {
        "sampled_at": "2026-07-31T08:47:32+00:00", "age_seconds": 12, "source": "statusline",
        "five_hour": { "state": "known",   "utilization_at_least": 37.4, "resets_at": "..." },
        "seven_day": { "state": "expired", "utilization_at_least": null, "resets_at": "..." }
      } },
    { "name": "scratch", "active": false, "quota": null }
  ]
}
```

字段名承载了文本形式用 `≥` 和 `unknown` 承载的同一个警告：`utilization_at_least` 是
**下界，不是测量值**；`state` 取 `known` / `expired` / `missing`。`cache.state`
（`ok` / `missing` / `unreadable` / `unsupported_schema`）让调用方能区分「没有数据」和
「坏了」。Codex 的配置项**完全没有 `quota` 键** —— 是缺失而不是 null，因为 Codex 根本没有
用量接口，不是「只是还没采样」。

## Windows 侧 Codex 凭据路径

`flipauth codex doctor` 可以把 WSL 侧凭据与 Windows 侧 Codex 的 `auth.json` 做对比，
判断两边是否登录的是同一个账号。

覆盖 Windows 路径：

```sh
export CODEX_SWITCH_WINDOWS_AUTH="/mnt/c/Users/<YourWindowsUser>/.codex/auth.json"
```

若该变量未设置，`flipauth` 会尝试通过 `wslvar` 或 `cmd.exe` 自动探测。探测失败时，该字段
显示为 `not configured`，并跳过对比。

## 工作原理

- 配置保存在 `~/.{claude,codex}/oauth-accounts/<profile>.<suffix>`。
- 配置文件权限 `600`，配置目录权限 `700`。
- 复制是原子的：先写临时文件，再重命名就位。
- 保存或加载前都会校验凭据 JSON 结构。
- `doctor` 只报告短哈希和 token 指纹，不输出原始 token。
- 激活配置时会先把即将切走的生效凭据重新保存，因此进行中的 token 刷新不会被悄悄丢失。
- 成功的额度查询会缓存到同目录下的 `.quota-cache.json`，让 `status` 保持离线；缓存里只有额度相关字段，不含 token。
- `observe` 从 Claude Code 本来就管道给状态栏的载荷里写进同一份缓存，因此保持新鲜完全不需要网络请求。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CLAUDE_SWITCH_CLAUDE_DIR` | `~/.claude` | Claude 配置目录 |
| `CLAUDE_SWITCH_STATE_DIR` | `$CLAUDE_SWITCH_CLAUDE_DIR/oauth-accounts` | Claude 配置的保存位置 |
| `CLAUDE_SWITCH_CREDENTIALS_FILE` | `~/.claude/.credentials.json` | 生效的 Claude 凭据文件 |
| `CODEX_SWITCH_CODEX_DIR` | `~/.codex` | Codex 配置目录 |
| `CODEX_SWITCH_STATE_DIR` | `$CODEX_SWITCH_CODEX_DIR/oauth-accounts` | Codex 配置的保存位置 |
| `CODEX_SWITCH_AUTH_FILE` | `~/.codex/auth.json` | 生效的 Codex auth 文件 |
| `CODEX_SWITCH_CREDENTIALS_FILE` | `~/.codex/.credentials.json` | 可选的生效 Codex credentials 文件 |
| `CODEX_SWITCH_WINDOWS_AUTH` | 自动探测 | Windows 侧 `.codex/auth.json` 路径；设为空则禁用 |
| `CLAUDE_SWITCH_API_BASE` | `https://api.anthropic.com` | `quota` 用量接口的基础 URL |

## 安全须知

- 每次切换前退出正在运行的 CLI。
- 新登录后立即保存刷新过的生效凭据。
- 不要让同一个 OAuth 账号同时在两处生效。
- 除非有意修复配置，否则不要手动编辑已保存的配置文件。
- 不要提交凭据文件或本地账号笔记。

## 隐私边界

本仓库以开源方式发布。请勿在这份公开 README 中写入个人账号标签、邮箱映射、本地机器路径、
私密 token 历史或运维手册。把本地笔记放进被忽略的文件（如 `README.local.md`）；
`.gitignore` 已特意排除这一类文件。

## 开发

基本本地检查：

```sh
bash -n ./flipauth          # 语法检查
./tests/parity-test.sh      # 两个服务的 save / activate / status / doctor 覆盖
./tests/claude-doctor-test.sh   # doctor 输出与 token 不泄露断言
./tests/claude-quota-cache-test.sh   # 额度缓存、observe、status --json（本地 stub，不联网）
```

## 许可证

MIT，详见 [`LICENSE`](LICENSE)。
