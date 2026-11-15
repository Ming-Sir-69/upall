# AI 纵向层（Skill / MCP / 插件）开发契约

产品原则（2026-11-15 已定）：
- 默认只检查；空格/1 才更新；不擅自改宿主配置里的钉死版本。
- 默认界面薄（AI 主场）；能力可以厚，进阶类型可发现但不全部铺在首页（索尼相机逻辑）。
- 能调官方命令就不自写更新器；topgrade 不集成，只借鉴清单与“未装跳过”。
- 本迭代范围 = 调研方案 **A**：MCP（npx 缓存检测）+ Skill（厂商附带多宿主同步，先 WebBridge）+ 监测类型开关骨架。插件类目只留分组/开关位，不做全宿主适配。

## 分组与监测类型
- 现有 GROUPS 保留：`cli` / `agent` / `app` / `host`。
- 新增监测类型（monitor kinds，可多选过滤，不等于 GROUPS）：
  - `runtime` — 编程工具本体（默认开）
  - `plugin` — 各宿主插件（默认关；本迭代仅占位）
  - `skill` — Skill（默认开；本迭代实现厂商附带同步检测）
  - `mcp` — MCP（默认开；本迭代实现 npx 缓存只读检查）
- 配置位：用户级可选 `~/.config/upall/monitors.json`（或并入现有 host 配置字段 `monitors`）；缺省 = AI 默认集。
- CLI：`--monitor runtime,skill,mcp`；文档写全，TUI 不堆开关墙。

## 文件所有权（并行防冲突）
| Owner | 可改 | 禁止 |
|---|---|---|
| A 类型开关 | `discovery.py`（GROUPS 旁 MONITORS）、`hosttools.py`、`cli.py`、相关测试、`docs/adapters.md` | `engine.py` 大改、layers/* |
| B MCP | 仅新建 `src/upall/layers/mcp.py`、`tests/test_mcp.py`；可在 `src/upall/layers/__init__.py` 导出 | discovery/cli/engine 主体 |
| C Skill | 仅新建 `src/upall/layers/skills.py`、`tests/test_skills.py`；导出同上 | discovery/cli/engine 主体 |
| Lead（主控） | `engine.py` 接线、`terminal.py` 轻提示、CHANGELOG、版本号、PR | — |

## 安全
- check 阶段只读配置与缓存元数据，不执行第三方包、不联网跑安装脚本。
- 版本比对可只读查 npm registry / MCP registry；失败记 network，不装作最新。
- 不读取 API 密钥；日志脱敏。

## 验收
- `python3 -m unittest discover -s tests -v` 全绿。
- 默认 upall 行为不变（仍先检查已装 CLI）；`--monitor mcp` / `skill` 能跑通演示或真实只读检查。
- 公共文档说明隐藏能力；不把所有类型铺进首屏 TUI。
