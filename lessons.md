# Lessons

> Project-level durable prevention rules. Current state is in `KANBAN.md`; long-task evidence is in `work/<id>/card.md`.

Record only user corrections that establish a reusable rule for future similar work. State the trigger, mistake, and next action; do not record current state, one-off evidence, raw incident narrative, credentials, or rules already owned by `AGENTS.md`.

- **When**：验证 CLI 退出后重启的流程。**Do**：测试保留真实未回收子进程，并覆盖进程快照到身份检查之间的退出；不能让假进程列表提前隐去所有僵尸进程。区分已退出与仍存活但身份改变。**Evidence**：[两种服务的未回收退出和相邻检查退出回归](tests/short-commands-test.py)，旧实现出现 `process is already a zombie`，修复后完成重启且存活 PID 身份改变仍被拒绝。
- **When**：修改官方 CLI 的启动入口或进程识别。**Do**：验证时解析实际文件，执行时保留稳定入口；用真实 NUL argv 和安装版本族识别进程。至少覆盖 PATH 前置包装、稳定链接升级后仍运行的旧版本，以及含服务名参数的普通进程。**Evidence**：[入口契约](tests/launcher-contract-test.py)、[进程事实](tests/process-state-test.py) 分别验证升级/包装与旧版本识别、普通子进程排除；不再依赖 `comm == claude` 或 shell 格式的 ps 文本。
