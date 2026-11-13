# Lessons

> Project-level durable prevention rules. Current state is in `KANBAN.md`; long-task evidence is in `work/<id>/card.md`.

Record only user corrections that establish a reusable rule for future similar work. State the trigger, mistake, and next action; do not record current state, one-off evidence, raw incident narrative, credentials, or rules already owned by `AGENTS.md`.

- **When**：验证 CLI 退出后重启的流程。**Do**：测试保留真实未回收子进程，并覆盖进程快照到身份检查之间的退出；不能让假进程列表提前隐去所有僵尸进程。区分已退出与仍存活但身份改变。**Evidence**：[两种服务的未回收退出和相邻检查退出回归](tests/short-commands-test.py)，旧实现出现 `process is already a zombie`，修复后完成重启且存活 PID 身份改变仍被拒绝。
- **When**：修改官方 CLI 的启动入口或进程识别。**Do**：验证时解析实际文件，执行时保留稳定入口；用真实 NUL argv 和安装版本族识别进程。至少覆盖 PATH 前置包装、稳定链接升级后仍运行的旧版本，以及含服务名参数的普通进程。**Evidence**：[入口契约](tests/launcher-contract-test.py)、[进程事实](tests/process-state-test.py) 分别验证升级/包装与旧版本识别、普通子进程排除；不再依赖 `comm == claude` 或 shell 格式的 ps 文本。
- **When**：官方 CLI 通过 Node/JS 包装脚本启动并在运行时调用 `process.execve` 原地替换为包内原生二进制（如 npm `@openai/codex` 在 Node 24 下替换为 `vendor/<triple>/bin/codex`）。**Do**：进程白名单除检查入口脚本和独立 `releases` 目录外，还须纳入同安装包（及 `nvm` 同系列 Node 版本）下嵌套、提升或自带的 `vendor/<triple>/bin/<service>` 路径，同时按完整路径层级排除同级 `codex-code-mode-host` 与 `codex-resources/...` 辅助程序。**Evidence**：[进程事实回归测试](tests/process-state-test.py) 与 2026-11-13 `halmi-home` 实机修复（旧代码在 `0.169.0` + `Node v24.22.3` 下把运行中的 Codex CLI 漏判为未运行，补齐后 `status` 正常观测且热切换成功）。
- **When**：编写依赖终端按键退出真机 TUI（如 Codex）的离线夹具和切换策略。**Do**：先实测目标版本 TUI 在活跃生成/命令、弹窗及审批遮罩下的真实按键反应，再写假 CLI 状态机；对 Codex `0.169.0` 的 `working` 态必须结合 Herdr 状态先发 `Esc` 中断回合/退出 `Task is still running` 弹窗后再发 `Ctrl+C`，且在 `agent send-keys` 拒收时按真实进程存活短窗确认是否已正常退出后再决定报错，避免假 CLI 假设与退出竞态。**Evidence**：[短命令测试](tests/short-commands-test.py) 与 2026-11-13 `halmi-home` 真机测试（旧实现先后出现 `Task is still running` 连发 30 次 `Ctrl+C` 卡死与第 4 轮退出瞬间的 `agent_not_found` 假失败，两处修补后离线 30 项与真机弹窗/审批/并切均通过）。
