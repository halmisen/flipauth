# 官方 CLI 账号启动器重构

2026-11-12 用户授权从第一性原理重构 FlipAuth。只修改本仓库，不部署入口、
不登录、迁移凭据、停止真实进程或改动其他项目。现有未提交工作纳入此次实现。

## 验收与设计

1. 一个账号拥有一个独立可写 home，官方 CLI 是登录、刷新与请求的唯一写者。
2. `LaunchPlan(service, account, home, executable, argv, env)` 是所有启动入口的公共契约。
   executable 保留稳定入口；解析后的版本文件只用于校验，不持久化到包装。
3. `process_state` 从同 UID PID 和 `/proc` 读取实际 argv、启动标识、home、执行文件。
   不能从选择、程序安装目录、Herdr sidebar 或 shell 格式的 ps 文本猜请求身份。
4. `session_switch` 仅编排退出/重启；保留全服务切换、回执、pidfd、未知进程拒绝、
   不确定投递回读及不跨账号续接。完成前重验所有目标。
5. 旧 snapshot 写入和直接请求额度的命令退役。旧数据不删除、不导入。
   `observe` 保留静默兼容出口，避免已有 statusLine 调用报错；不再写旧缓存。
6. `selected` 是后续启动偏好；`defaults` 是初始记录；status 单独列实际 PID/home。

候选 A 以 LaunchPlan 为中心，候选 B 以 registry/launch/process facts 分层。
采用 B 的模块边界与 A 的启动计划；保留可选 bind-current，但它只调用统一计划。
不采用继续补 legacy 写入闸门的方案：两个凭据写者没有必要同时存在。
两位同模型代理独立只读比较后收敛；本环境没有技能要求的其他模型系列，未作跨模型裁判。

## 实现分工与阶段

- Ground/Sketch：现有代码、测试、Git 历史及实机只读结论已核对；设计完成。
- Implement：主执行者负责启动计划、目录/短命令入口、legacy 退役和文档。
  辅助执行者分别拥有进程/生命周期及入口契约测试，文件所有权分开。
- Verify：完整离线套件，重点覆盖真实 argv、原生版本命名、包装位于 PATH 前端、
  稳定 symlink 升级、并行账号、daemon 归属和失败恢复。真实身份/请求验收单列。

## 收口结果

实现完成。`bash tests/run-all.sh` 为 7 个入口、0 失败，共 58 个离线场景：
目录 18、入口契约 6、清理 6、状态观察 3、进程事实 11、切换生命周期 14；
另含 Bash 语法检查。Python 源码 AST 语法与 `git diff --check` 通过。
最终日志：[refactor-verification.txt](refactor-verification.txt)。

独立只读审查发现并已修复：argv0/basename 伪造误识别、Codex 嵌套旧版本识别、
已有 home 的 owner/group-write 边界。主执行者另外验证并修复了 daemon 预检后的 PID
复用、updater/server 顺序，以及完成前的全部目标复核；均有离线回归。

最后通过新版 status 实机只读观察到原生版本 Claude，以及不同 home 的 Codex
CLI/managed app-server；同时排除了同一官方安装中的 code-mode host 辅助程序。
这些观察未读取 token、修改登记表/选择或停止会话。原生 Claude 的 Herdr 提示仅对
新启动进程生效；现有未识别会话不会被后台伪造为已识别。

原 `verification.txt`、`short-verification.txt`、`zombie-fix.md` 为历史证据。
当前源码与本次最终日志是下一步的恢复点。没有提交、部署、登录或实机切换。
四账号官方身份、刷新、Herdr 展示、实际 PATH 与完整切换仍需单独实机验收。
