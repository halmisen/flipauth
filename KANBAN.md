# KANBAN — 当前项目状态

> 本文件是唯一的短状态面板。短任务以代码、验证和 Git 历史为记录；需要精确跨会话恢复时才创建 `work/<id>/card.md`。

## 当前方向

用户 2026-10-13 确定本次范围：个人终端凭据切换，取消 Claude 和 Codex remote-control 开机启动，由 Harness 禁用对应登录任务并保持配置默认禁用，不增加 daemon 自动恢复或远程服务编排。个人会话建议使用 `codex --no-daemon`；保留旧进程退出后再换凭据的保护。

Herdr 联系规则归 Harness 全局指令：工具 shell 缺少 `HERDR_ENV` 不再单独阻断用户要求的联系；按明确会话、实时项目路径、代理类型和就绪状态核对目标，使用显式 pane ID，不凭 UI 焦点或无可靠调用者上下文的 `--current` 判断身份。此规则不放宽 flipauth 的凭据写入进程闸门。

研究并支持 OMP（oh-my-pi）凭据切换。OMP OAuth 位于独立的 `~/.omp/agent/agent.db`，当前切换 `~/.claude/` 或 `~/.codex/` 不会影响 OMP；目标是让一次 `flipauth` 操作一致切换官方 CLI 与 OMP，但不能引入 API 中转站。

## 已验证

- 2026-09-08：已核实 Windows Codex 与 Claude 桌面版已安装；检查时两个 Windows 进程均未运行。
- WSL 与 Windows Codex 使用各自的配置根；`doctor` 对 Windows Codex 凭据仅做读取和身份指纹比较，不写回 Windows 文件。
- 当前 Windows Codex 身份与 WSL 保存的 profile 身份不一致；不能把 Windows 登录状态当作 WSL profile 的切换结果。
- 工作树中的 Windows 边界保护会在写入或凭据复制前拒绝 Windows 受管路径、CLI 配置根错配、原生 Windows 二进制和 Windows 侧 Codex quota 临时目录；对应测试为 `tests/windows-boundary-test.sh`。
- 隔离结论有运行条件：保持 CLI 配置根和临时目录在 WSL 文件系统内，并使用 WSL 版 `claude` / `codex`；边界测试通过后才可把保护视为发布保证。

## 下一步

用户 2026-10-09 要求开新 session 只读 review 本轮个人 Codex 切换改动。入口：
[review 交接](docs/local/20261009-personal-codex-switch-review.md)，含 flipauth / Harness 的文件范围、源码指纹、隔离测试与红绿证据、未验收边界。当前未提交；不得操作真实凭据、服务或重启，也不得覆盖 Harness 的其他 WIP。下一 session 的完成标准是独立 review 结论，区分本地实现与真实验收。

2026-10-13 后续决策覆盖旧交接中“保留 Claude 自启动”的范围；复核新增的全局 Herdr 规则和自启动退休配置时，以 Harness [回执](../harness/docs/20261013-remote-control-autostart-retirement.md) 及当前源码为准。下次正常登录或重启后，由用户确认 Claude/Codex remote-control 未从退休入口启动；任务禁用回读不能替代该实机验收，不为验收主动重启。

在真实但可接受退出的 idle Herdr Claude 或 Codex pane 上，手动运行一次对应的
`flipauth <service> <profile>`，确认 Claude 的 pane 命令或 Codex 的 agent prompt 让 TUI
退出后 pane 保留并回到 shell，再确认 profile 切换完成。Codex 多 pane 验收应确认逐个发送
`/exit`，且所有 TUI 退出后才停止 managed daemon。不要用 `herdr server stop` 作为该验收的替代，
因为它会停止同一 server 的无关工作。

## 边界

- 不把真实账号标签、机器路径、用量数字、token 或凭据数据库写入 Git。
- 激活必须继续原子、先验证并保存退出账号的最新 token；查询配额不得改变活动凭据。
- 任何凭据写入（save、activate、login）前，必须先确认对应 CLI 的系统进程为零。Herdr 中只有
  已精确关联且 `idle` 的同服务 pane 可以收到 `/exit`；Codex 必须通过 `herdr agent prompt` 逐个
  退出 TUI，并在此之后才对精确匹配的 managed `app-server --managed-daemon`
  及其 `pid-update-loop` 辅助进程（官方 PID 记录、进程启动标识和配置根必须匹配，不依赖父子关系）发送 SIGTERM。不发 SIGKILL。working、blocked、unknown、不可检查和
  其他 Herdr 外进程一律中止，且 live credential、快照和 `.active-profile` 不得改变。
- Claude 与 Codex 的进程闸门必须隔离；不得停止 Pi、OMP、普通 shell、无关服务或整个 Herdr server。
- OMP 支持必须先证明 token 所有权与可移植边界；不以 API relay 绕过订阅和客户端边界。
- 任何 statusLine 安装只能显式 opt-in，保留并备份既有设置。

## Parked

- OSS statusLine onboarding。
- Codex full-reset credit 消费；该 RPC 是写操作，保持在 flipauth 范围外。
- `quota | head` 的既有 SIGPIPE traceback。
- OMP 后续研究保持原方向；本轮先完成个人 Codex 切换 review，再研究 `auth-broker` / `auth-gateway` 机制及 token 可移植边界。
- force-stop：不实现通用 SIGTERM/SIGKILL 选项。仅对精确匹配的 Codex managed daemon 发送
  SIGTERM 并等待；超时即中止，不升级为 SIGKILL。其他状态不确定的进程仍拒绝切换。

## 迁移说明

2026-08-10 起，`tasks/todo.md` 退出控制面；其有效 Next、Deferred 与稳定事实已合并到本文件和 `AGENTS.md`，旧记录由 Git 历史保留。
