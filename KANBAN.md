# KANBAN — 当前项目状态

> 本文件是唯一的短状态面板。短任务以代码、验证和 Git 历史为记录；需要精确跨会话恢复时才创建 `work/<id>/card.md`。

## 当前方向

研究并支持 OMP（oh-my-pi）凭据切换。OMP OAuth 位于独立的 `~/.omp/agent/agent.db`，当前切换 `~/.claude/` 或 `~/.codex/` 不会影响 OMP；目标是让一次 `flipauth` 操作一致切换官方 CLI 与 OMP，但不能引入 API 中转站。

## 下一步

先研究 OMP `auth-broker` / `auth-gateway` 的真实机制，以及不同客户端签名的 refresh token 是否可转移；据此决定向 `can1357/oh-my-pi` 提 issue/PR，还是在 flipauth 增加受测扩展。

## 边界

- 不把真实账号标签、机器路径、用量数字、token 或凭据数据库写入 Git。
- 激活必须继续原子、先验证并保存退出账号的最新 token；查询配额不得改变活动凭据。
- OMP 支持必须先证明 token 所有权与可移植边界；不以 API relay 绕过订阅和客户端边界。
- 任何 statusLine 安装只能显式 opt-in，保留并备份既有设置。

## Parked

- OSS statusLine onboarding。
- Codex full-reset credit 消费；该 RPC 是写操作，保持在 flipauth 范围外。
- `quota | head` 的既有 SIGPIPE traceback。

## 迁移说明

2026-08-10 起，`tasks/todo.md` 退出控制面；其有效 Next、Deferred 与稳定事实已合并到本文件和 `AGENTS.md`，旧记录由 Git 历史保留。
