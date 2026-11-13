# 单终端切换（2026-11-13）

用户明确修正此前的原 pane 全量重开方案：关闭旧会话，只在输入命令的新终端启动一个
新会话。（同日再修正：同账号不重启，见文末。）停止旧 daemon 即可，新 daemon 交给官方 CLI 自动启动。
本文件替代 refactor.md 中的旧重启位置和 daemon 绕过约定。

## 当前合同

`cod/cc NAME` 或 `account bind NAME PATH --switch` 生成的入口：

1. 要求独立 TTY，拒绝从待关闭 CLI 的工具子进程调用；检查目标配置与登录文件存在性。
2. 持有操作锁和启动闸门，识别全部同服务 CLI、注册目录、真实执行文件和进程出生身份。
   无法检查的进程、未登记目录、已知认证旁路或无归属的后台 server 均在停止前拒绝。
3. 旧 CLI 按服务退出（2026-11-13 修正，见下节）：Codex 必须在 Herdr pane 内，预检时把每个
   PID 映射到唯一 pane，停止时经 `herdr agent send-keys <pane> ctrl+c` 逐次发送并复核 PID 出生与
   pane 前台，直到 PID 消失且 pane 前台不再含它；不在 Herdr 的 Codex 在停止任何进程前拒绝，
   超时也只拒绝，不退回信号。Claude 仍用 pidfd SIGTERM。不回答任何审批界面。
4. 校验官方 daemon PID 记录及 boot ID、PID start ticks、home、argv，先停止 updater，
   等待退出后再停 server。出现新进程或无法退出就终止操作，不 SIGKILL、不自动重试。
5. 确认没有旧同服务进程后记录选择，在请求终端及其 cwd exec 官方客户端。
   不增加 `--no-daemon`，不显式调用 `daemon start`，不迁移或恢复跨账号会话。

回执记录每个旧 CLI 和 daemon 的 PID/start/home、计划/退出状态和交接 PID。
`exec-admitted` 只证明交接已安排，status 的 `launch_observed` 再按实际进程检查。
并发请求在交接后如观察到官方启动过程中的新进程，会保守失败并留回执，不自动重试。
客户端真实身份、请求成功、新 daemon 自动启动与界面效果仍属实机验收。

普通 `account run/current` 维持并行启动语义；普通官方服务命令不被命名入口部署替换。
命名入口由 `scripts/deploy-launchers.sh <service> [--check]` 使用同一个绑定生成器部署。
默认 home、账号独立状态和凭据不因生成命令而改变。

## 验证与部署

新增的同账号命名入口测试先因缺少 `--switch` 失败；原生 daemon 启用测试先因被强制添加
`--no-daemon` 失败。修复后完整离线入口七项、零失败，63 个场景通过：
账号目录 19、入口契约 6、清理 6、观察 3、进程事实 12、切换 17。
日志：[terminal-verification.txt](terminal-verification.txt)。Bash/Python 语法与 diff 检查通过。

切换 fixture 使用真实受控假 CLI/server/updater 进程与 PTY，验证先退出旧进程再在请求 cwd
启动一次、当前账号也重启、跨服务不受影响、停止失败保持选择、进程出生改变不发信号、
未知进程拒绝、调用者祖先保护及并发出现新进程时拒绝。假官方客户端自己拉起 daemon；
任何显式 `app-server daemon start` 调用都会使测试失败。

本机已部署当前登记的 Codex 命名入口并通过只读内容检查。
部署只增加命令并记录稳定官方入口；部署前后三个真实 Codex 进程的 PID/start/home、
默认记录与启动选择完全一致，Claude 默认/选择仍未设置。没有触发真实切换、登录或模型请求。
真实账号标签及本机操作记录由 HarnessBase 的本机部署案例维护，不写入公开项目记录。

## 终端退出修正（2026-11-13，Claude）

根因：旧 CLI 用 SIGTERM 关闭。终端模式（raw、备用屏幕 1049、焦点 1004、粘贴 2004、
鼠标 1000/1002/1003/1006）是终端模拟器里的状态，只有 TUI 自己写出关闭序列才能清除。
bash 在作业被信号杀死后可以恢复 termios，但无法关闭模拟器模式，于是鼠标上报以
`35;24;1M` 这类文本出现在旧提示符后。

| 证据（隔离、未登录、临时 home、只对自建子进程操作） | 结果 |
|---|---|
| 原生 Codex 0.167.2，裸 PTY：启用 1000/1002/1003/1004/1006/1007/1049/2004 与 kitty 键盘协议；SIGTERM/SIGINT/SIGHUP（另测 SIGQUIT/SIGTSTP/SIGUSR1） | 全部遗留 1004/2004/1049，kitty 压栈 2 次、出栈 0 次 |
| 同上，键盘 Ctrl+C | 模式全部关闭，kitty 出栈，cooked/echo 恢复 |
| 原生 Claude，裸 PTY：启用 1004/2004/2031 与 kitty；SIGTERM/SIGINT/SIGHUP | 均恢复，无遗留（Claude 保留 SIGTERM） |
| 一次性 Herdr pane + `script`：Claude 启用 1004/2004、kitty `>5u`、modifyOtherKeys `>4;2m`，随后发 SIGTERM | 全部复位，回到 bash |
| 一次性 Herdr pane + `script` 抓输出：Codex 启用 1000/1002/1003/1004/1006/1007/1049/2004；`pane send-keys ctrl+c` ×2 | 仅剩 25（光标可见，正常），回到 bash |
| 同 pane 直接调用新 `locate`/`exit_in_band` | 0.57 s、2 次按键退出，前台回到 shell，`icanon echo` |
| 同 pane SIGTERM 反例 | 遗留 1004/1007/1049/2004 |

Codex 运行时启用了任意移动鼠标上报（1003/1006），截图里的鼠标坐标洪泛正与此吻合。
探测数据见 `native-terminal-probe.jsonl`，其中 `modes_seen` 是正例对照。
实测 `processes()` 识别出的 Codex PID 与 Herdr pane 前台 PID 一致（普通 `codex` 入口）。

回归：假 CLI 改为在测试持有的 PTY 中运行，启用上述模式并进入 raw；只有键盘 Ctrl+C
会恢复（假 Codex 不装 SIGTERM 处理器，假 Claude 收 SIGTERM 会恢复，与原生一致）。
假 Herdr 把 `send-keys` 写入测试持有的 PTY master。断言先确认模式确实被启用（正例），
再检查退出后无遗留模式、cooked/echo 已恢复。日志：`terminal-exit-verification.txt`。旧实现跑新用例 6 项失败
（终端用例断言泄漏 `1003/1006/1049/...`），新实现离线 7 套检查零失败：
账号目录 19、入口契约 6、清理 6、观察 3、进程事实 12、切换 19。

未验证：Ctrl+C 在审批界面上应为拒绝或中断，但尚未实测；已登录 Claude（可能启用鼠标/备用屏）
收到 SIGTERM 后的终端收尾；无 TTY 的 `codex exec` 现在也会被当作 CLI，因不在 pane 中而让切换拒绝；
真实已登录且忙碌的 Codex 会话的完整切换（第一次 Ctrl+C 先中断任务，再次退出）、
旧终端鼠标移动不出字、新终端只启动目标账号、原生 daemon 自动出现。这一步会结束当前会话，
需用户在可中断时执行。Codex 升级后，先重跑 `native-terminal-probe.py` 确认这个分工仍然成立。

## 只在换账号时清场（2026-11-13 再修正）

用户日常只用命名切换入口（如 `codex-primary` / `codex-secondary`）；普通 `codex` 保持官方入口（不覆盖 PATH，避免官方升级改写链接，
也不影响后台工具调用）。规则：

| 情况 | 动作 |
|---|---|
| 运行中有其他账号目录的 CLI 或 daemon | 换账号：关闭全部同服务 CLI（含目标账号）、停止全部 daemon，再在本终端启动 |
| 只有目标账号进程或无进程 | 直接再开一个，不停任何进程，回执 `mode: same-account` |
| 首参是 `exec/e/review/login/logout/mcp/plugin/app-server/remote-control/completion/update/doctor/sandbox/debug/apply/a/queue/archive/delete/migrate-*/unarchive/exec-server/features/help`，或任意位置有 `--version/-V/-v/--help/-h`（Claude 另含 `-p/--print`） | 直通：在该账号目录执行，不切换、不改选择 |

Codex 旧 pane 的 Ctrl+C 改为每轮发给全部待退出 pane。验证：新增/改写 5 项用例，旧实现上 2 失败 3 错误；
并行用例改为检查“任一 pane 退出前所有 pane 已收到首个 Ctrl+C”，对串行实现失败。新实现离线 7 套零失败
（切换 22）。两个一次性 Herdr pane 内未登录 Codex 并行退出 0.53 s，各 2 次按键，前台回到 shell。
日志：`terminal-exit-verification.txt`。

已知边界：子命令只看首参（`codex-secondary -m x exec` 会被当作交互式）；直通的 `exec` 等若拉起该账号 daemon，
下次切到另一账号时会连同全部会话一起清场；`codex-secondary update` 会在该账号目录下执行官方更新，升级请用普通 `codex update`。

## 独立只读审查修复（2026-11-13）

- P1 发键竞态：改用 `herdr agent send-keys`（agent 已不占 pane 时 Herdr 拒绝），且前台查询返回后、发键前再核对出生身份。
  真实 Herdr 实测：退出后再发 `agent send-keys` 被拒；彻底消除仍需 Herdr 提供按进程身份的条件发键，文档确认目前没有。
- P2 回执：每个 CLI 确认退出即落盘；任何退出路径（含失败）最后按实时出生身份把每个 CLI/daemon 记为 `exited`/`running`/`unknown`，
  未确认送达的按键标 `key_delivery: unconfirmed`。
- P3 直通误判：标志扫描止于官方 `--`，其后视为提示词原文。
- P4 文档：`--switch` 帮助与 card.md 当前闭环已更新。
- 回归：3 项新用例在修复前代码上全部失败，修复后离线 7 套零失败（切换 25）。日志：`terminal-exit-verification.txt`。

## halmi-home 实机热切换验证与 npm `execve` 修复（2026-11-13 晚）

- 首次在 `halmi-home`（npm `@openai/codex 0.169.0` + Node `v24.22.3`）热切换时，因 `codex.js` 调用 `process.execve` 原地替换为 `.../@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex`，原 `_official_signatures("codex")` 仅覆盖 `codex.js` 与 `releases/`，导致运行中的 CLI 未被识别（`stopped_cli: []`）。
- 修复：`lib/process_state.py` 新增 `_codex_npm_vendors()`，识别嵌套、提升、自带及同 `nvm` 版本族下的 `@openai/codex*/vendor/<triple>/bin/codex`，并保持排除 `codex-code-mode-host` 与嵌套资源子目录；`tests/process-state-test.py` 补全回归测试（先红后绿），完整 7 套测试通过。
- 实机结果：在 Herdr `wJ:pP` 与 `wJ:pN` 之间完成两次已登录热切换（`sen` → `az` → `sen`，回执 `codex-a30b556e3ef2489696016467bfa697a7.json` 与 `codex-fe658206a6a14bce99a6321aab4d45d6.json`），均经 `herdr agent send-keys ctrl+c` 退出旧 CLI（`key_delivery: acknowledged`）、旧终端退回 shell、旧 daemon 全停、新账号启动与 `launch_observed: true` 验证通过。仍待验证：Codex 忙碌输出中或审批弹窗时的 Ctrl+C、Claude 多账号切换，以及 `workman` 拉取本提交后的复验。
