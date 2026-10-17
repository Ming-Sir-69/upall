# 模块抽离开源的规范与实践对照

UPALL 的场景是：从现有私有项目中提取可复用工具，独立开源后，原项目继续使用这个工具。采用独立仓库、独立软件包、宿主按固定版本接入。仓库可以单独存放，不要求保留本地目录父子关系。

以下区分正式规范、官方实践指南和项目取舍，不把任何一种目录布局称为普遍适用的“行业强制规范”。

| 对应问题 | 官方依据与性质 | UPALL 的适配 |
|---|---|---|
| 怎样从大项目独立出去 | [GitHub 子目录拆仓指南](https://docs.github.com/en/get-started/using-git/splitting-a-subfolder-out-into-a-new-repository)，实践指南 | 仅公开模块文件，不上传整个父项目。本项目原目录没有 Git 历史，所以从整理后的源码建立新仓库，没有伪造或重写父仓库历史。 |
| 怎样成为可安装模块 | [PyPA pyproject.toml](https://packaging.python.org/en/latest/specifications/pyproject-toml/)，正式打包规范；[src 布局指南](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)，实践建议 | 用 src/upall、pyproject.toml、命令入口、Python 版本要求与 MIT 元数据；验证 wheel 和源码包在新环境可安装、可测试。 |
| 原项目怎样继续使用 | [uv 工具管理](https://docs.astral.sh/uv/concepts/tools/)，工具官方文档；[PyPA 依赖表达式](https://packaging.python.org/en/latest/specifications/dependency-specifiers/)，依赖规范 | CLI 在独立工具环境安装，宿主通过命令入口调用；用含完整提交的直接引用固定依赖，不默认使用可编辑源码或跟随 main。requirements 文件是 pip 的文件格式约定，不称为通用锁文件标准。 |
| 配置与状态放哪里 | [XDG Base Directory](https://specifications.freedesktop.org/basedir/latest/)，目录规范 | 用户状态默认放 XDG_STATE_HOME/upall 或 ~/.local/state/upall；忽略无效的相对 XDG 路径。UPALL_LOG_ROOT 是本工具的显式覆盖接口。父项目真实路径和私有配置不进入公共仓库。 |
| 如何升级并避免旧项目突然变化 | [Semantic Versioning 2.0.0](https://semver.org/)，版本兼容规范 | 明确命令、按键、JSON 和环境接口；发布版本与提交不原地改写。当前为 0.x 初期开发，破坏性变更需明确记录。宿主先验收再更换依赖锁，保留前一个提交用于回退。 |
| 修改如何进入主分支 | [GitHub 受保护分支](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)，平台官方机制 | 通过 PR 合入 main、保持线性历史、解决评审对话，禁止强推和删除。单维护者不强制另一个人批准，但测试和自查不能省。 |
| 要不要用 submodule | [Git submodules](https://git-scm.com/book/en/v2/Git-Tools-Submodules)，Git 官方机制 | submodule 适用于父仓库要把子仓库放在内部并锁定提交的情况；当前选择本地解耦，不需要它。未来只有父项目已有 Git 且确需嵌套检出时才另行采用。 |

## 不依赖父项目的公开模块

公开包不能依赖某个人的绝对路径、父项目文件、专用 Python 启动器或私人配置。模块代码和隔离测试保存在一个权威仓库；宿主不复制第二套实现。公共默认值与示例保持通用，宿主值通过明确接口注入。

这是一种从具体项目提取组件、再由原项目消费组件的组合做法；不是单靠一个 Git 命令就能完成的“解耦”。

## 正式使用与开发分离

正常使用固定版本或完整提交，避免本地开发改动立刻影响日常入口。开发时可以使用单独检出或可编辑安装，但必须明确区分，并在验证后恢复固定版本。模块测试通过之后，宿主还需验证原快捷入口、默认不升级、配置路径和退出行为。

固定依赖文件及本机验收回执属于宿主；只记录上游、版本、提交、配置接口、前一版本和验收结果，不保存密钥。安装后的 [direct_url.json 元数据](https://packaging.python.org/en/latest/specifications/direct-url-data-structure/) 可核对实际 Git 提交，避免只凭版本号猜来源。UPALL 不会自动读取或修改宿主依赖记录。

## 本项目有意保留的取舍

自动化 CI 是常见工程实践，并非这里引用的打包或版本规范的强制要求。当前仓库按照维护者的额度约束禁用 Actions，使用本地测试、安装包验证和 PR 流程。后续启用托管构建或包注册表发布，需要单独决定成本与权限。

主要验收平台是 macOS；其他系统只在实测之后扩展支持声明。采用某项规范不等于所有供应商适配器、输入法或平台都已验证。
