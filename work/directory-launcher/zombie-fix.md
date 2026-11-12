# CLI 退出后未重启：僵尸进程判定修复

2026-11-12。实现与离线修复完成，未提交，真实重测待用户执行。

## 原因与两次回执

第一次真实切换已退出旧 CLI，worker 在 `stopping` 阶段因 `process is already a zombie` 失败。
`processes()` 将 ps 中尚未回收的退出进程继续列为存活，`still_original()` 随后调用 `identity()`，
而 `identity()` 对 Z 状态直接抛错。于是“退出成功、尚待父进程回收”被误判为切换失败，选择和重启均未执行。

第二次请求只有官方 daemon 留存，无法找到可重启的 CLI pane，因此拒绝；没有提交选择或发送重启。
后续只读现场已看到用户重新启动的 CLI，与留下的官方 daemon 均在默认配置目录。
此处不推断真实认证身份，没有读取真实凭据，也没有代为取消、退出或启动任何会话。

原假 ps 使用 `alive()` 提前排除了所有僵尸，原套件从未经过真实 Linux 的未回收退出阶段，故漏检。

## 修复与相邻边界

- `processes()` 通过同一份 `/proc` 身份判定过滤已退出进程，而非仅依赖 ps 列表。
- `identity()` 对消失、Z 和 X 状态返回无存活身份；非当前用户仍拒绝。
- 预检时 CLI 已退出则在任何停止前拒绝；退出等待期间消失或变成僵尸则确认结束。
- 即使进程在快照后才退出也可完成等待；仍存活但启动标识改变的 PID 仍被拒绝。
- managed daemon 在检查或 pidfd 信号阶段自行消失时按已退出处理，避免给已退出进程发信号。
- PID 复用、归属变化、未知进程、停止失败、返回 shell 和重启 home 回读等闸门保留。

检查同类调用：身份检查在预检、退出等待、daemon 信号前各处；均明确区分缺失与身份变化。
旧 Bash daemon 检查原本已排除 Z，未改动旧凭据交换路径。

## 可复跑验证

回归命令：

```sh
python3 tests/short-commands-test.py ShortCommands.test_exited_unreaped_cli_restarts_for_both_services ShortCommands.test_exit_between_process_scan_and_identity_check
```

旧代码红灯已实际运行：前者在 Codex 和 Claude 两分支均失败，回执精确为 `process is already a zombie`；
后者在旧模块出现同样异常。修复后的两测试均通过，包括存活 PID 身份改变仍拒绝的配对断言。
只等待测试自己启动的假 CLI，刻意保留其 Z 状态直到 worker 完成，随后由测试父进程回收。

全套命令：`bash tests/run-all.sh`。结果 `Suites/checks: 10; failed: 0`。
包含生命周期 11 场景、目录 16 场景、清理 6 场景、六个旧套件和 Bash 语法检查。
当前源码摘要：[zombie-source-sha256.txt](zombie-source-sha256.txt)。
原始红绿日志及全套输出在 Git 忽略的 `docs/local/20261112-zombie-*.txt`、
`docs/local/20261112-exit-race-*.txt`，旧模块保存在同目录 `zombie-repro/` 供红灯核对。
私人回执内容与本机路径不进入公开材料，原真实回执未改写。

## 仍需实机验收

由用户在普通 shell 再发起一次明确切换，确认原 pane 出现目标 home 的新 CLI 并检查 `status`。
本次补丁不恢复上次已失败 worker、不自动重投，不宣称已完成真实重启。
真实认证身份、界面就绪、请求及刷新仍不是离线通过或进程 home 回读所能证明。
