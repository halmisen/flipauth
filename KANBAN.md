# KANBAN — FlipAuth

> 唯一短状态面板。长任务恢复入口：[card.md](work/directory-launcher/card.md)；切换设计：[terminal-switch.md](work/directory-launcher/terminal-switch.md)；历史方案：[refactor.md](work/directory-launcher/refactor.md)。

## 现在

- **长期维护立场（2026-11-13 用户确认）**：按长期维护者自主演进设计与实现，受用户需求与操作授权边界约束。
- **核心架构与边界**：账号目录固定，官方 CLI 独占登录、刷新与请求；无网关、配额轮询或自动轮换。所有启动共用 `LaunchPlan`；命名切换入口由 `scripts/deploy-launchers.sh` 部署；普通裸命令 `bind-current` 经 `scripts/deploy-current.sh` 部署在独立优先目录 `~/.local/flipauth/bin/<service>`（代码层禁止写入官方二进制或官方软链所在目录，防升级覆写）。
- **切换与混号语义**：仅场上存在异号 CLI/daemon 时清场，且只停 `home != target` 的进程，保留已运行的目标账号 CLI/daemon（回执记 `kept_cli`/`kept_daemon`）。`selected == target` 且场上混号时预检拒绝且不杀进程（需裸命令/`account run` 并开或显式 `--replace`）。非交互子命令直通不切换。Codex CLI 须在 Herdr pane 内经 `herdr agent send-keys` 带内退出（`working` 发 `Esc`，其余发 `Ctrl+C`，含退出竞态恢复）；Claude CLI 用 pidfd SIGTERM；daemon 按 updater → server 停止，新 daemon 由官方 CLI 自动拉起；`exec-admitted` 与 `status` 独立核验。
- **Fail-Closed 迁移**：`account migrate-default <name> <new-dir> [--dry-run]` 预检默认目录零进程后原子迁出账号文件，Codex 仅在 `~/.codex` 保留 `packages/standalone`（无 `auth.json`），`packages/app-server-daemon` 随账号迁走并重写绝对 `current` 软链。
- **实机部署与验收**：
  - `workman`：Codex（`sen` 已迁至 `~/.codex-sen`）与 Claude（单账号 `fiver` 设为 `selected`，`~/.local/bin/claude-fiver` 单账号期保留现状）均已在 `~/.local/flipauth/bin/` 部署 `bind-current`。
  - `halmi-home`：Codex（`sen`/`az`）已完成热切换、授权遮罩撤回、`Task is still running` 弹窗脱困、双端并切与 33 目录 `trust_level = "trusted"` 真机验收；Claude 当前仅单账号。
- **额度定界（2026-11-13）**：只做 L0 显示（Claude statusLine `rate_limits`、Codex 内置 `status_line`），不做提醒、预选、自动切换或凭据读取。

## 下一步

- 新增第二个 Claude 账号后，补做 Claude 多账号切换真机实测。
- 下次在 `halmi-home` 上机时，核验或用 `scripts/deploy-current.sh codex` 将旧 `~/.local/bin/codex` 包装器迁入 `~/.local/flipauth/bin/codex`（防 Codex 升级覆写）。

## 待人决定

无

## 门禁

- 离线回归全绿：`bash tests/run-all.sh`（7 组）与 `bash -n ./flipauth`。
- 真实登录、凭据迁移、清场停会话、PATH 部署与对外发布须用户授权；不改动运行中会话时仅执行只读检查与离线测试。
- 禁止重新引入凭据复制、激活标记或直连 OAuth 额度查询；禁止提交凭据、私有标签或本地账号备注。

## 搁置

- 额度提醒、预选、自动切换及服务端身份校验（已定界不做）。
- 旧快照命令（`save/activate/login/quota/doctor/legacy`）与原 pane 重开方案（已退役，留档备查）。
