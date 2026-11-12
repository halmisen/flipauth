# FlipAuth 目录启动器交付记录

此文件保留初版目录能力交付。后续用户已同意全局退出重启和默认命令跟随，最新范围与证据见 [short-commands.md](short-commands.md)。

日期：2026-11-12。范围：研究、实现、离线验证、文档。未部署或提交。

## 实际交付

新入口统一为 `flipauth <claude|codex> account <add|list|run|login|bind>`。
它在旧模式初始化前进入独立 Python 模块。旧快照命令与进程保护逻辑没有改动。

| 命令 | 行为 |
|---|---|
| `account add <name> <absolute-directory>` | 登记已有目录，不读写其凭据 |
| `account add <name> <absolute-directory> --create --bare` | 明确选择独立初始配置，创建私有目录；Codex 写入文件存储设置 |
| `account add <name> <absolute-directory> --create --template <absolute-template>` | 复制审阅过的规则与配置，拒绝模板中的其他文件 |
| `account list [--json]` | 只读名称、目录及本地文件存在性；身份始终未核实 |
| `account run <name> -- <CLI arguments>` | 显式指定目录，以 `exec` 启动官方 CLI |
| `account login <name> -- <login arguments>` | 在长期账号目录运行 `claude auth login` 或 `codex login` |
| `account bind <name> <absolute-command-path>` | 按明确路径生成可执行入口，固定登记表位置并传递参数 |

普通 `claude`、`codex` 命令没有被替换，默认目录没有被改动。
要明确使用已登记的默认账号，可调用 `account run default`。
登记表位于 `FLIPAUTH_ACCOUNTS_DIR`，默认 `~/.local/state/flipauth`。
程序位置使用 `FLIPAUTH_CLAUDE_BIN` / `FLIPAUTH_CODEX_BIN`，默认从 PATH 查找。
旧模式环境变量保持原用途。

登记表只保存名称、规范化目录与 `existing` / `bare` / `template` 来源类型，不保存 token。
目录所有权检查禁止同目录和祖先/子目录重复登记，也防止占用其他服务默认目录。
重复登记相同名称与目录不写文件。写登记表加锁并原子替换。
快捷命令只接受新路径或完全相同内容；不会依据一个标记覆盖现有文件。

## 配置与运行状态边界

| 内容 | 处理 |
|---|---|
| Claude `CLAUDE.md`、`settings.json` | 仅由明确的模板复制，各目录独立可写 |
| Codex `AGENTS.md`、`config.toml` | 同上；Codex TOML 检查需要 Python 3.11+ |
| 凭据、登录元数据、会话、历史、数据库 | 不复制，不共享，不解析真实 token |
| 插件安装与运行状态、权限数据库、信任/首次启动状态 | 不复制；官方 CLI 内重新配置和验收 |
| hooks、权限规则、插件引用、配置中的路径 | 模板明确带入时保留，使用前由目录所有者审阅 |
| 跨项目规则与技能 | 本轮没有复用；遵循所属项目的共享资产规则 |

`--bare` 显式接受没有继承规则、设置和插件的新环境，创建时也会提示。
模板只能包含允许的文件，拒绝目录、符号链接和已识别的凭据字段/提供商覆盖项。
这是边界检查，不是完整秘密扫描器；模板必须先经过审阅。
相对路径、外部 hook 或插件引用可能需要调整，复制不证明相应功能已可用。

启动检查已知环境覆盖项、用户配置及部分 CLI 覆盖参数。
报错只列变量名/键名，不回显值或配置内容。继承的同名 home 变量由所选账号替换。
已有 Codex 配置若使用非文件存储则拒绝启动，不自动改设置或迁移凭据。
未显式配置存储时保持原文件不变，使用官方默认值，不据此宣称已验证身份。
启动使用私有 umask，拒绝已识别的共享符号链接/硬链接状态文件和数据库。

目录模式从不扫描或停止其他进程。相同目录内并发和 daemon 行为由官方 CLI 管理。
旧模式的原地换凭据仍保留原来的同服务进程退出闸门，两者适用条件不同。

## 研究依据与取舍

已核对交接书 SHA256：`4937afd63dcd2afbf7d373cc81e9599ede987ffe6dfcdb210851430d55f5d850`。
Magpie 只读快照 commit 已核对为 `805e5c29a33540a4e968613a0ef41682c43f423f`。
没有安装或执行 Magpie，没有复制其源文件。

审阅的 Magpie 机制：

- [Claude 目录所有权](https://github.com/yetone/magpie/blob/805e5c29a33540a4e968613a0ef41682c43f423f/internal/provider/claude_dirs.go)：CLI 在自己的长期目录内持有与刷新登录。
- [Codex home](https://github.com/yetone/magpie/blob/805e5c29a33540a4e968613a0ef41682c43f423f/internal/appdir/codex.go) 与 [switchSavedLogin](https://github.com/yetone/magpie/blob/805e5c29a33540a4e968613a0ef41682c43f423f/internal/provider/logins.go)：目录归属与第二份刷新凭据之间的冲突。
- [启动器及其测试](https://github.com/yetone/magpie/blob/805e5c29a33540a4e968613a0ef41682c43f423f/internal/update/launcher_test.go)：参数保留、shell 引用、`exec` 和用户文件冲突。

本实现保留上述机制，省去账号扫描、凭据同步、网关、数据库和后台协调。
快捷命令冲突处理更保守：只认完全相同内容，不更新带有旧标记的不同文件。

2026-11-12 读取的官方文档：

- [Claude 多账号认证](https://code.claude.com/docs/en/authentication#log-in-with-multiple-accounts)说明独立配置目录，也列出 Console 无 API key 浏览器登录的共享存储例外。
- [Codex 配置与状态位置](https://learn.chatgpt.com/docs/config-file/config-advanced)说明 `CODEX_HOME` 定位配置和本地状态。
- [Codex 凭据存储](https://learn.chatgpt.com/docs/auth?surface=cli)说明 `file` 在对应 home 内保存凭据，官方 CLI 负责使用期间刷新。

最强反方是两个账号只需两条环境变量命令，新增登记表本身会增加维护量。
这里增加的价值限于目录冲突保护、显式配置准备、只读列表与可重复生成的脚本入口。
没有引入常驻组件。保留旧模式是为了避免未经授权迁移已有账号；最终退役另行决定。

## 离线验证证据

完整命令：`bash tests/run-all.sh`。
原始成功输出：[verification.txt](verification.txt)。汇总为 `Suites/checks: 8; failed: 0`。
对应源码与测试摘要：[source-sha256.txt](source-sha256.txt)，可用 `sha256sum -c work/directory-launcher/source-sha256.txt` 核对。

| 验证入口 | 结果与实际边界 |
|---|---|
| `bash -n flipauth` | Bash 语法通过 |
| `tests/claude-doctor-test.sh` | 原套件通过，保留脱敏约束 |
| `tests/claude-quota-cache-test.sh` | 原套件通过，仅本地 HTTP stub |
| `tests/codex-quota-test.sh` | 原套件通过，仅假 app-server |
| `tests/parity-test.sh` | 原保存、激活与诊断行为通过 |
| `tests/process-safety-test.sh` | 原进程保护测试通过，仅模拟进程与 Herdr |
| `tests/windows-boundary-test.sh` | 原 WSL/Windows 边界测试通过 |
| `python3 tests/directory-accounts-test.py` | 16 个端到端场景通过，全部使用假官方 CLI |

目录测试直接驱动 Bash 分派、Python 实现和生成的快捷命令，证明：

- Claude 与 Codex 各两个目录内的登录和运行写入分开，不创建旧快照标记。
- 启动第二个账号不修改第一个的文件，不停止第一个仍运行的假 CLI。
- 参数中的空格、单双引号、美元符号、反引号、空字符串与 CLI 的 `--` 保留；启动器和登记表路径也含特殊字符。
- 工作目录、stdin/stdout/stderr、非零退出码与 PTY 终端描述符保留。
- 执行链保持同一个 PID；INT、TERM、HUP 送达选定假 CLI，其他假进程仍运行。
- `list` 不创建登记表、不调用 CLI、进程控制或 HTTP 工具，不解析凭据内容，身份始终未核实。
- 模板字节保留但 inode 独立，源模板后续修改不影响账号配置；凭据/运行文件不能进入模板。
- 同名目录、嵌套目录、默认 home 冲突、命令冲突、递归、Windows 路径/二进制、共享状态符号链接/硬链接、损坏登记表均拒绝且不覆盖目标。
- 首次并发登记保留两个条目；相同绑定与登记可重复执行。

开发中离线测试发现并修复首次并发创建的竞争、模板对存储设置的误拒绝，以及重复移除 `--`。
首次汇总运行因执行期间修改汇总脚本而中断，未作为成功证据。
修正后固定脚本重新完整运行，最终日志只保存该次完整通过的输出。
另已运行 `git diff --check`，并检查新增公开文件无私人标签或机器绝对路径。

## 未验证与后续步骤

没有启动真实官方 CLI，也没有读取、迁移或改写真实登录材料。
没有真实账号登录、退出、刷新、身份、配额或服务端请求验收。
没有部署到真实命令目录、变更网络、停止既有进程、跨项目写入、提交、推送或发布。

目录隔离不能证明文件沙箱、网络隔离或服务端身份互不关联。
项目/系统策略、尚未识别的环境覆盖、hooks、插件和外部资源仍可能影响官方 CLI；
当前检查不是其完整配置求值器。官方 daemon 或同目录并发刷新也没有实机验收。

下一步由用户决定并另行授权真实准备与验收：先审查每个目标目录所需规则、权限、插件及存储方式；
再登记目录、在独立长期目录执行官方登录，并通过官方 CLI 确认身份和会话保存；
最后安装可选快捷命令，在可验收会话检查 Herdr 与刷新后的目录状态。
这些步骤不需要为了切换目录而停止无关账号，也不应复制旧快照充当已登录结果。
