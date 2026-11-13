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
不停 daemon；`exec`/`login`/`--version` 等非交互子命令直通不切换。用户日常只用命名切换入口（如 `codex-<name>`），
普通 `codex` 保持官方入口。旧终端回到 shell。新 daemon 由官方 CLI 自动拉起，不显式启动。
用户已授权代码、部署脚本及命名入口部署；本轮不实际停止会话、登录或迁移凭据。
账号目录固定，官方 CLI 独占登录、刷新和请求；无网关、配额轮询或自动轮换。
2026-11-13 用户定界：额度只做 L0 显示（Claude statusLine 的 `rate_limits`、Codex 内置 `status_line`），
不做提醒、预选、自动切换、凭据读取或额度请求；切换只由用户在协作间隙手动执行。
默认记录、后续选择、实际进程与服务端身份分别核验；普通官方入口不随选择变化。

## 当前实现与恢复

- 所有账号启动共用 `LaunchPlan`；命名包装使用稳定官方入口，拒绝覆盖既有不同文件。
- `scripts/deploy-launchers.sh <service> [--check]` 部署所有已登记账号的命名切换入口；
  普通服务命令不被替换，部署不触发实际切换或改变选择。
- 切换需要独立 TTY，拒绝从待关闭 CLI 的工具子进程触发；先预检所有已知进程归属，
  Codex CLI 必须在 Herdr pane 内，经 `herdr agent send-keys` 发 Ctrl+C 正常退出（否则预检拒绝）；
  Claude CLI 用 pidfd SIGTERM（原生已验证会恢复终端）；等待退出后，最后按 updater → server 停止有官方 PID 记录的 daemon。
- 无 detached worker 或旧 pane 重开；不强制 `--no-daemon`，不显式启动新 daemon。
  进程重用、未知归属、停不掉或启动前出现新进程时留下失败回执，不强杀、不自动重试。
- `exec-admitted` 只记录交接，`status` 独立回读 PID/start/home；不证明请求身份或成功。
- 当前设计及验证入口：[terminal-switch.md](work/directory-launcher/terminal-switch.md)。
  旧目录重构与原 pane 方案保留为历史：[refactor.md](work/directory-launcher/refactor.md)。

## 实机验收

2026-11-13 用户实机试切后报告旧终端残留界面并刷控制序列，随后已切回原账号。
根因：Codex 0.167.2 对任何外部信号都不恢复终端，只有键盘内退出会恢复；Claude 收 SIGTERM 会恢复。
2026-11-13 Claude 已在源码改为 Codex 经 Herdr Ctrl+C 退出，终端状态回归先红后绿，
一次性 Herdr pane 内未登录 Codex 实测通过（`terminal-switch.md`）；
真实已登录会话切换（旧终端可输入、鼠标不出字、新终端单一目标账号、daemon 自动出现）仍待用户现场执行。
