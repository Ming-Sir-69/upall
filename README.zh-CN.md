# UPALL

[English](README.md) · [开发说明](docs/development.md) · [扩展方向](docs/roadmap.md)

面向 AI CLI 的安装检测、版本检查和终端更新工具。默认操作统一为：

**自动检查 → 空格更新 → 回车退出**

中文界面、固定数字提示、全角按键、同屏日志；运行时只依赖 Python 标准库。当前为 0.1.0 初始版本，主要验证环境是 macOS，其他 POSIX 环境仍属实验范围，原生 Windows 暂不支持。

本仓库是从一个较大私有项目中抽离的通用模块。通用代码、测试和接口由这里维护；父项目负责本机配置、快捷入口、私有记录及依赖版本锁定。接入、配置、升级与回退规范见 [模块集成说明](docs/module-integration.md)。

![演示数据，非实时版本](assets/demo.png)

## 使用

需要 Python 3.11 及以上。可直接从源码运行，无需安装：

~~~sh
git clone https://github.com/Ming-Sir-69/upall.git
cd upall
python3 tools/upall --demo
~~~

使用 uv 独立安装：

~~~sh
uv tool install git+https://github.com/Ming-Sir-69/upall.git
upall
~~~

更新 UPALL 本身用 uv tool upgrade upall-cli；卸载用 uv tool uninstall upall-cli。不会为缺少的 AI 软件自动安装。

| 按键 | 功能 |
|---|---|
| 空格 / 1 / U | 检查结束后更新有新版的工具 |
| 回车 / 0 / Esc / Q / X | 当前任务结束后退出 |
| 2 / R | 只重试失败项 |
| 3 / L | 显示或隐藏日志 |
| ↑↓、J/K、Tab | 选择工具 |
| [ / ] | 滚动日志 |
| Ctrl-C | 停止本任务及其子进程 |

支持全角 ０１２３ 和全角空格。运行中按空格不排队升级；运行中按回车不会打断更新。数字功能提示保持固定。输入法候选窗口可能先处理按键，PTY 测试不能替代所有输入法的实际体验。

## 常用命令

| 命令 | 效果 |
|---|---|
| upall | 自动发现已安装 CLI，检查后等空格更新 |
| upall claude codex | 只检查指定工具，空格更新 |
| upall --list | 本机安装清单，不联网查询版本 |
| upall --all | 同时展示缺少的候选并跳过 |
| upall --plain / --json | 纯文本或最终 JSON，默认只检查、完成即退出 |
| upall --retry | 重查上轮失败项 |
| upall --update | 显式直接检查并更新，适合脚本 |
| upall --demo | 演示交互，不执行真实更新 |

upcheck 是兼容入口，与默认 upall 相同。支持目录和更新来源详见 [适配器说明](docs/adapters.md)。

状态和日志默认放在 $XDG_STATE_HOME/upall 或 ~/.local/state/upall，目录仅当前用户可访问。安装清单与更新结果分别保存，不覆盖失败重试记录。UPALL_LOG_ROOT 可覆盖根目录；UPALL_SEARCH_PATH 可限定发现目录，便于隔离测试。

命令路径、运行日志及报告只保留在本机；分享时先脱敏。工具不读取 API 密钥、登录凭据或会话历史。官方升级和 npm 安装脚本会执行第三方代码，仅在明确按空格/1或传入 --update 后调用。

## 后续开发

使用独立分支和 PR；默认只检查、固定键位和安装来源识别是兼容约定。先运行本地测试，再提交变更。项目未配置自动计量服务，GitHub Actions 保持禁用。

[贡献指南](CONTRIBUTING.md) · [安全边界](SECURITY.md) · [变更记录](CHANGELOG.md) · [MIT 许可](LICENSE)

