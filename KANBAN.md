# KANBAN — 当前项目状态

> 唯一短状态面板。长任务恢复入口：[card.md](work/directory-launcher/card.md)。

## 持续维护标准

2026-11-13 用户明确后续判断标准：

> This codebase is yours: what it's for and how it's built are your call, and you'll keep building on it.

负责本项目的代理按长期维护者的立场工作，主动判断项目用途、设计、实现与演进方式。
每次改动都要考虑实际使用价值、整体逻辑和后续继续开发的成本。
用户明确的需求与操作授权边界继续适用。

## 当前方向与授权

2026-11-13 用户修正切换语义：带账号名的切换入口关闭同服务全部旧 CLI，
再停止旧 Codex daemon，只在输入命令的新终端及其工作目录启动一个新会话。
2026-11-13 再修正：只在有其他账号的 CLI/daemon 时才清场；同账号或无进程时直接再开一个，
不停 daemon；`exec`/`login`/`--version` 等非交互子命令直通不切换。用户日常切号用命名切换入口（如 `codex-<name>`）；
2026-11-15 用户确认：为避免 `codex-az` 期间多 Agent / Herdr 按默认习惯执行裸 `codex` 落回 `~/.codex`（`sen`）导致混号清场，
已在 `halmi-home` 部署 `bind-current` 到 `~/.local/bin/codex`，使普通 `codex` 经 `account current` 跟随 `selected`（不清场）；
未部署 `bind-current` 的环境（如 `workman` 尚未部署前）或直接调用原官方二进制时，普通入口仍不随选择变化。旧终端回到 shell。新 daemon 由官方 CLI 自动拉起，不显式启动。
2026-11-18 用户确认普通 `claude` 也跟随 `selected`。`workman` 已通过 `~/.local/flipauth/bin/claude` 部署 `bind-current`，新 Bash 优先使用该目录。当前只登记 `fiver`，并将它设为当前选择，初始默认仍留空，`claude-fiver` 保留固定入口。
用户已授权代码、部署脚本及命名入口部署；本轮不实际停止会话、登录或迁移凭据。
账号目录固定，官方 CLI 独占登录、刷新和请求；无网关、配额轮询或自动轮换。
2026-11-13 用户定界：额度只做 L0 显示（Claude statusLine 的 `rate_limits`、Codex 内置 `status_line`），
不做提醒、预选、自动切换、凭据读取或额度请求；切换只由用户在协作间隙手动执行。
默认记录、后续选择、实际进程与服务端身份分别核验；直接调用原官方入口不随选择变化（已部署 `bind-current` 的 PATH 包装器除外）。

## 当前实现与恢复

- 所有账号启动共用 `LaunchPlan`；命名包装使用稳定官方入口，拒绝覆盖既有不同文件。
- `scripts/deploy-launchers.sh <service> [--check]` 部署所有已登记账号的命名切换入口；
  普通服务命令不被替换，部署不触发实际切换或改变选择。
- 切换需要独立 TTY，拒绝从待关闭 CLI 的工具子进程触发；先预检所有已知进程归属，
  Codex CLI 必须在 Herdr pane 内，经 `herdr agent send-keys` 带内退出（`working` 时先发 `Esc` 中断回合或退出 `Task is still running` 弹窗，非 `working` 时发 `Ctrl+C`；否则预检拒绝）；
  Claude CLI 用 pidfd SIGTERM（原生已验证会恢复终端）；等待退出后，最后按 updater → server 停止有官方 PID 记录的 daemon。
- 无 detached worker 或旧 pane 重开；不强制 `--no-daemon`，不显式启动新 daemon。
  进程重用、未知归属、停不掉或启动前出现新进程时留下失败回执，不强杀、不自动重试。
- `exec-admitted` 只记录交接，`status` 独立回读 PID/start/home；不证明请求身份或成功。
- 当前设计及验证入口：[terminal-switch.md](work/directory-launcher/terminal-switch.md)。
  旧目录重构与原 pane 方案保留为历史：[refactor.md](work/directory-launcher/refactor.md)。

## 实机验收

2026-11-13 用户在 `workman` 实机试切后报告旧终端残留界面并刷控制序列，随后切回原账号；根因为 Codex 对外部信号不恢复终端，Claude 收 SIGTERM 会恢复。同日 Claude 在 `d7806f4` 改为 Codex 经 Herdr Ctrl+C 退出。
2026-11-13 晚在 `halmi-home`（npm `@openai/codex 0.169.0` + Node `v24.22.3`）首次真机热切换实测时，发现 `codex.js` 调用 `process.execve` 替换成 `vendor/<triple>/bin/codex`，原进程识别漏掉该路径导致旧 CLI 未收到 Ctrl+C；已在 `lib/process_state.py` 新增 `_codex_npm_vendors` 与回归测试并复验通过。
随后实机连续完成两次已登录会话热切换（`codex-sen` → `codex-az` → `codex-sen`，跨 `wJ:pP` / `wJ:pN`）：两次旧 CLI 均经 `herdr agent send-keys ctrl+c` 退出（`key_delivery: acknowledged`），旧终端干净退回 shell，旧 `app-server` 守护进程全部退出，新账号 CLI 与自动守护进程均被 `status` 观测到（`launch_observed: true`）。
同晚经 Herdr 实测更多边界并补修两处源码缺陷：
- 授权/信任遮罩（`blocked`：`Folder access` 与 `Would you like to run ...?` 提权命令弹窗）：实测 `Ctrl+C` 不确认执行直接撤回并干净退出；修补后在 `Would you like to run ...?`（`curl -sI https://example.com`）下切账号再次通过（`keys_sent: 2`，回执 `codex-27acb59b5f58409492be19ff84185d80.json`）。
- 活跃回合与退出窗竞态（`working` + `Task is still running` 弹窗）：Codex `0.169.0` 在回合中收 `Ctrl+C` 会弹出 `Task is still running` 并忽略后续全部 `Ctrl+C`（`keys_sent: 30` 失败）；`lib/session_switch.py` 先改为 `working` 发 `Esc`（实测 `Working sleep 30` 清场双端一次通过，`codex-26a8100611124c038fdaa8a8229de2c6.json`）。随后在预置 `Task is still running` 弹窗复测中捕获到第 4 轮 `agent send-keys` 与 CLI 正好退出（`agent_not_found`）撞车报错（`codex-a21073ce3a014cbe8797c840c27d80c4.json`），再在 `lib/session_switch.py` 补上发键拒收后短暂确认退出的竞态恢复（`short-commands-test.py` 先红后绿通过 30 项）。修补后预置 `Task is still running` 弹窗脱困切出（`codex-26c4f774f8664ad384ce62a192d17539.json`）、直通 `--version`、同账号并行接入及双端并切全部真机通过。
- 已将两份 Codex 账号 `config.toml`（`~/.codex` 与 `~/.codex-az`）对 `~/projects/*` 等 33 个目录补齐 `trust_level = "trusted"`。
待办：
- Claude 多账号切换真机实测（`halmi-home` 目前仅配置单账号，待加第二个账号后补测）；
- `workman` 拉取 `feature/directory-launcher` 最新提交并复验。
