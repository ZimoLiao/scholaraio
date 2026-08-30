# ScholarAIO — Agent 入口文档

这是面向多种 coding agent 的仓库入口文档。它有意保持精简：

- 这里只放持久有效的项目事实和硬约束
- 多步骤流程放进 skills
- 深度参考材料放进带索引的 `docs/` 知识库

## ScholarAIO 是什么

ScholarAIO 是一个面向 agent 的 All-in-One 学术 harness。研究者通过 coding agent 检索文献、检查证据、组织持久化项目上下文、生成可审阅研究产物，并使用边界明确的科学工具适配器；ScholarAIO 不取代当前 agent 的原生推理与编排能力。

核心 Python 包是 `scholaraio`。真正做事时，应优先走 ScholarAIO CLI 和项目 skills，而不是绕过运行时 helper 直接手改数据目录。

## 在这个仓库里如何工作

- 用户请求明显对应某个能力时，优先查看 `.claude/skills/` 中匹配的 skill。
- 优先用 `scholaraio` CLI 做真实工作，而不是只描述应该怎么做。
- 按需渐进加载信息：先元数据或摘要，再结论，最后才全文。
- 把论文结论当作“作者宣称”而不是真理；要比较证据、指出局限、区分支持性结果和作者解读。
- 用户可见的草稿、报告、导出物、研究输出，应默认写到 `workspace/`，不要落到仓库根目录或 `scholaraio/` 源码树。
- 不要随意改写或删除运行时数据。涉及运行时布局时，优先走 `Config`、migration helper 和经过测试的 accessor。
- 改动运行时布局、兼容行为、agent 入口文档或 skill 发现逻辑时，要同步更新测试和对齐文档。
- 改完代码或文档后，尽量跑相关检查，并补至少一条真实 smoke path。

## 起步顺序

建议按这个顺序看：

1. [`README.md`](README.md)：产品定位和顶层结构
2. [`STRATEGY.md`](STRATEGY.md)：修改产品范围或新增外部集成前先看
3. [`docs/DESIGN.md`](docs/DESIGN.md)：仓库知识地图
4. [`docs/getting-started/agent-setup.md`](docs/getting-started/agent-setup.md)：直接开仓库 vs 插件 / 跨项目接入
5. [`docs/guide/cli-reference.md`](docs/guide/cli-reference.md)：当前 CLI 面
6. [`docs/guide/agent-reference.md`](docs/guide/agent-reference.md)：更深的 agent、runtime、skill 组织说明
7. [`docs/internal/PLANS.md`](docs/internal/PLANS.md) 和 [`docs/internal/exec-plans/completed/scholaraio-upgrade-plan.md`](docs/internal/exec-plans/completed/scholaraio-upgrade-plan.md)：涉及运行时布局、迁移、兼容层时先看

## Skill 优先工作流

canonical skill 源是 `.claude/skills/`。其他 agent 发现入口都只是它的包装：

- `.agents/skills/`
- `.qwen/skills/`
- `skills/`

代表性 skills：

- 核心科研：`search`、`show`、`ingest`、`workspace`、`audit`、`translate`
- 写作：`academic-writing`、`nature-workflow`、`literature-review`、`paper-guided-reading`、`paper-writing`、`citation-check`、`writing-polish`、`review-response`、`research-gap`、`poster`、`technical-report`
- 输出与工具：`draw`、`document`、`scientific-runtime`、`scientific-tool-onboarding`

如果一个流程已经长成可复用 playbook，就把它做成 skill，而不是继续膨胀这个文件。

## 仓库结构速览

- `scholaraio/core/`：配置、日志、运行时基础设施
- `scholaraio/providers/`：外部服务客户端和解析后端
- `scholaraio/stores/`：持久化库根和存储 helper
- `scholaraio/projects/`：用户项目与 workspace 行为
- `scholaraio/services/`：领域逻辑与编排
- `scholaraio/interfaces/cli/`：CLI parser、startup、命令 handler

breaking cleanup generation 已移除 `scholaraio.index`、`scholaraio.workspace`、`scholaraio.translate` 这类 legacy 根级 public facade。新代码应直接 import canonical namespace。

高信号 canonical 实现入口：

- `scholaraio/stores/explore.py`
- `scholaraio/projects/workspace.py`
- `scholaraio/services/insights.py`
- `scholaraio/services/translate.py`
- `scholaraio/interfaces/cli/`
- `scholaraio/interfaces/cli/compat.py` 用于内部 CLI wiring
- `scholaraio/cli.py` 仅作为发布入口保留

## 当前运行时模型

- runtime 只接受 fresh layout：`data/libraries/`、`data/spool/`、`data/state/`
- `data/papers/`、`data/explore/`、`data/proceedings/`、`data/inbox*` 等 legacy 根不再作为常规运行时输入；请用 `scholaraio migrate upgrade --migration-id <migration-id> --confirm` 执行受支持的一键迁移，或用 `scholaraio migrate ...` inventory、verify、逐 store 迁移
- `workspace/<name>/` 保持自由项目树
- workspace paper 引用放在 `workspace/<name>/refs/papers.json`
- `workspace.yaml` 只是 additive metadata，不替代 `refs/papers.json`
- 系统拥有的 workspace 输出放在 `workspace/_system/`，尤其是：
  - `workspace/_system/translation-bundles/`
  - `workspace/_system/figures/`
  - `workspace/_system/output/`
- 运行时布局迁移控制面在 `.scholaraio-control/`；标准一键升级 gate 是 `scholaraio migrate upgrade --migration-id <migration-id> --confirm`，`finalize` 仍作为逐 store 迁移后的清理/最终验证步骤

## 常用命令

- `scholaraio --help`
- `scholaraio setup check`
- `scholaraio search --help`
- `scholaraio show --help`
- `scholaraio pipeline --help`
- `scholaraio ws --help`
- `scholaraio migrate --help`
- `scholaraio migrate upgrade --help`
- `scholaraio migrate finalize --help`

仓库常用校验命令：

- `python -m pytest -q -p no:cacheprovider`
- `python -m ruff check scholaraio tests`
- `python -m ruff format --check scholaraio tests`
- `python -m mkdocs build --strict`

## 多 Agent 入口

- Claude Code：`CLAUDE.md` + `.claude/skills/`
- Codex / OpenClaw：`AGENTS.md` + `.agents/skills/`
- Qwen：`.qwen/QWEN.md` + `.qwen/skills/`
- Cursor：`.cursor/rules/scholaraio.mdc`，然后 `AGENTS.md`
- Cline：`.clinerules`，然后 `AGENTS.md`
- Windsurf：`.windsurfrules`，然后 `AGENTS.md`
- GitHub Copilot：`.github/copilot-instructions.md`，然后 `AGENTS.md`

这些 wrapper 都应保持轻量，不要把每个 wrapper 都做成第二份大手册。

## 深入参考

按最小必要原则阅读：

- 仓库知识地图：[`docs/DESIGN.md`](docs/DESIGN.md)
- 计划地图与执行历史：[`docs/internal/PLANS.md`](docs/internal/PLANS.md)、[`docs/internal/exec-plans/`](docs/internal/exec-plans/index.md)
- 知识质量与清理：[`docs/internal/QUALITY_SCORE.md`](docs/internal/QUALITY_SCORE.md)
- Agent 与 skill 组织：[`docs/guide/agent-reference.md`](docs/guide/agent-reference.md)
- 安装与配置：[`docs/getting-started/agent-setup.md`](docs/getting-started/agent-setup.md)、[`docs/getting-started/installation.md`](docs/getting-started/installation.md)、[`docs/getting-started/configuration.md`](docs/getting-started/configuration.md)
- CLI 行为：[`docs/guide/cli-reference.md`](docs/guide/cli-reference.md)
- 写作工作流：[`docs/guide/writing.md`](docs/guide/writing.md)
- 运行时布局与迁移：[`docs/internal/exec-plans/completed/scholaraio-upgrade-plan.md`](docs/internal/exec-plans/completed/scholaraio-upgrade-plan.md)、[`docs/design-docs/directory-structure-spec.md`](docs/design-docs/directory-structure-spec.md)、[`docs/design-docs/directory-migration-sequence.md`](docs/design-docs/directory-migration-sequence.md)、[`docs/design-docs/migration-mechanism-spec.md`](docs/design-docs/migration-mechanism-spec.md)

拿不准时，遵循三条：入口文档保持精简，流程性内容进 skills，深细节进专项参考文档。
