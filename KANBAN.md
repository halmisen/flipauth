# KANBAN — 当前项目状态

> 本文件是唯一的短状态面板。短任务以代码、验证和 Git 历史为记录；需要精确跨会话恢复时才创建 `work/<id>/card.md`。

## 当前方向

研究并支持 OMP（oh-my-pi）凭据切换。OMP OAuth 位于独立的 `~/.omp/agent/agent.db`，当前切换 `~/.claude/` 或 `~/.codex/` 不会影响 OMP；目标是让一次 `flipauth` 操作一致切换官方 CLI 与 OMP，但不能引入 API 中转站。

## 下一步

先研究 OMP `auth-broker` / `auth-gateway` 的真实机制，以及不同客户端签名的 refresh token 是否可转移；据此决定向 `can1357/oh-my-pi` 提 issue/PR，还是在 flipauth 增加受测扩展。

在真实但可接受退出的 idle Herdr Claude 或 Codex pane 上，手动运行一次对应的
`flipauth <service> <profile>`，确认 `/exit` 后 pane 保留并回到 shell，再确认 profile
切换完成。不要用 `herdr server stop` 作为该验收的替代，因为它会停止同一 server 的无关工作。

## 边界

- 不把真实账号标签、机器路径、用量数字、token 或凭据数据库写入 Git。
- 激活必须继续原子、先验证并保存退出账号的最新 token；查询配额不得改变活动凭据。
- 任何凭据写入（save、activate、login）前，必须先确认对应 CLI 的系统进程为零。Herdr 中只有
  已精确关联且 `idle` 的同服务 pane 可以收到 `/exit`；working、blocked、unknown、不可检查和
  Herdr 外进程一律中止，且 live credential、快照和 `.active-profile` 不得改变。
- Claude 与 Codex 的进程闸门必须隔离；不得停止 Pi、OMP、普通 shell、无关服务或整个 Herdr server。
- OMP 支持必须先证明 token 所有权与可移植边界；不以 API relay 绕过订阅和客户端边界。
- 任何 statusLine 安装只能显式 opt-in，保留并备份既有设置。

## Parked

- OSS statusLine onboarding。
- Codex full-reset credit 消费；该 RPC 是写操作，保持在 flipauth 范围外。
- `quota | head` 的既有 SIGPIPE traceback。
- force-stop：不实现 SIGTERM/SIGKILL 选项；状态不确定时宁可拒绝切换，也不终止 Agent 工作。

## 迁移说明

2026-08-10 起，`tasks/todo.md` 退出控制面；其有效 Next、Deferred 与稳定事实已合并到本文件和 `AGENTS.md`，旧记录由 Git 历史保留。
