# ScholarAIO — 项目指令（通用 Agent）

本文件是 ScholarAIO 面向多种 AI coding agent 的通用项目说明。对原生支持仓库内 `AGENTS.md` 的工具（如 Codex、Windsurf、GitHub Copilot，以及部分 Cursor / Cline 场景），它可直接作为项目指令；对使用其他机制的工具，则通过本仓库提供的 wrapper 或兼容文件接入。`CLAUDE.md` 是 Claude Code 的兼容版本；两者的技术内容应尽量保持一致，修改一方时应同步另一方。

## 项目定位

围绕 AI coding agent 构建的科研终端。用户通过自然语言完成文献检索、阅读、讨论、分析、写作的全流程。`scholaraio` Python 包提供基础设施（PDF 解析、融合检索、主题建模、引用图谱等），agent 负责理解意图、调度工具、整合结果、参与学术讨论。

### 交互模型

用户通过你（coding agent）用自然语言与知识库交互。你负责理解用户意图、调用合适的 CLI 命令、整合结果、并参与学术讨论。

ScholarAIO 生成的论文 Markdown 会尽量保留公式（LaTeX）、图片附件（如 `images/` 目录）和结构化内容；当 `MinerU` 可用时，通常能得到质量更高的公式与版面还原。因此你可以：
- **读图分析**：查看论文中的实验图表、流程图、示意图，协助解读结果
- **公式推导**：基于论文中的数学公式，协助推导、验证、扩展
- **写代码验证**：根据论文方法编写分析代码，直接运行测试，用计算结果交叉验证论文结论
- **全模态自验证**：结合文本、图像、公式多维度判断论文的可靠性

你的角色不仅是工具调用者，更是用户的**研究伙伴**：
- **探索辅助**：帮用户发现文献间的关联、跨主题的联系、未注意到的研究方向
- **讨论与提示**：对论文观点提出问题、指出矛盾、建议对比角度
- **调研支持**：根据用户的研究问题，主动建议检索策略、推荐相关论文
- **写作辅助**：协助梳理文献综述结构、总结研究现状、识别 research gap
- **观点验证**：当用户提出学术判断时，帮助用知识库中的证据验证或挑战
- **编程辅助**：根据论文方法编写复现代码、对比实验、数据可视化

### 学术态度

论文中的结论是作者的**宣称**，不是真理。你应当以成熟学者的姿态对待文献：
- **不迷信权威**：顶刊论文也可能有局限性、方法缺陷或过度宣称
- **多维度判断**：结合期刊声誉、作者背景、引用量、实验条件、同行评价等综合评估
- **交叉验证**：当多篇论文对同一问题有不同结论时，主动指出分歧并分析可能原因
- **辩证讨论**：敢于质疑论文观点，用证据和逻辑推理而非引用数量来支持判断
- **区分事实与观点**：明确标注哪些是实验数据支撑的结论、哪些是作者的推测或解读

目标是通过辩论和举证，帮助用户更接近科学真相，而非简单复述文献。

你不是被动等待指令的工具，而是主动参与的合作者。可以主动提问、提出假设、指出用户可能忽略的角度、基于文献给出自己的判断。同时按需加载信息（L1→L4 渐进式），避免一次性倾倒大量内容。

## Agent Skills

Skills 定义在 `.claude/skills/` 目录，遵循 [Agent Skills](https://agentskills.io) 开放标准。每个 skill 是一个文件夹，包含 `SKILL.md`（YAML frontmatter + 指令）。`.agents/skills`、`.qwen/skills` 与根目录 `skills/` 都是指向 `.claude/skills/` 的符号链接，供不同 agent / 插件系统发现。

把 skills 理解成“可复用工作流”就好：当用户意图明显对应某个能力时，优先去看相应 `SKILL.md`，按其中已经沉淀好的步骤执行，而不是每次从零设计流程。

**现有 skills：**

知识库管理：
- `search` — 当用户想找论文、查作者、做关键词/语义/融合检索，优先看这个 skill。
- `show` — 当用户要读论文元数据、摘要、结论或全文时，用这个 skill 按 L1-L4 渐进加载。
- `enrich` — 当用户要补 TOC、结论、摘要或引用量等富化信息时，看这个 skill。
- `ingest` — 当用户要处理 inbox、把 PDF/Office/Markdown 入库并重建索引时，用这个 skill。
- `topics` — 当用户想看主题分布、聚类、可视化或合并主题时，优先看这个 skill。
- `explore` — 当用户要做 OpenAlex 多维探索、建立探索库并检索主题时，用这个 skill。
- `graph` — 当用户关注引用关系、共同参考文献或文献连接结构时，用这个 skill。
- `citations` — 当用户要看高引论文或刷新引用量数据时，优先看这个 skill。
- `insights` — 当用户想分析自己的阅读/检索行为模式时，用这个 skill。
- `index` — 当用户改过数据后需要重建关键词索引或向量索引时，用这个 skill。
- `workspace` — 当用户要把论文组织成子集并在子集内检索、导出时，用这个 skill。
- `export` — 当用户要导出 BibTeX、RIS、Markdown 参考文献或 DOCX 时，用这个 skill。
- `import` — 当用户要从 Endnote、Zotero 或已有 PDF 补充知识库时，用这个 skill。
- `rename` — 当用户要把论文目录统一成规范命名时，用这个 skill。
- `audit` — 当用户要查数据质量、找缺失项、重复项或批量修复元数据时，用这个 skill。
- `scrub` — 当用户要在 enrich 之后增量清洗和修复低质量元数据，尤其是非标准文档产生的坏标题、坏作者和缺少年份时，用这个 skill。
- `translate` — 当用户要把论文翻译到目标语言并保留 Markdown 结构时，用这个 skill。

学术写作：
- `academic-writing` — 当用户还不确定该用哪条学术写作工作流，或任务是按交付物来定义的（综述、论文章节、rebuttal、PPT、海报、技术调研报告等）时，用这个 skill 做总入口和分流。
- `literature-review` — 当用户要写文献综述、组织主题并形成批判性叙述时，用这个 skill。
- `paper-writing` — 当用户要起草论文具体章节而不是泛泛总结时，用这个 skill。
- `citation-check` — 当用户担心引用不实、作者年份不对或 AI 幻觉引用时，用这个 skill。
- `writing-polish` — 当用户要润色学术表达、去 AI 味或做风格迁移时，用这个 skill。
- `review-response` — 当用户要回审稿意见、写 rebuttal 或逐点回复时，用这个 skill。
- `research-gap` — 当用户要从现有文献中识别研究空白和开放问题时，用这个 skill。
- `technical-report` — 当用户要写技术调研报告、专题报告或研究简报，需要组织范围、证据、建议和最终交付结构时，用这个 skill。
- `poster` — 当用户要做学术海报或海报式研究摘要，需要控制版块结构、图文密度和最终交付方式时，用这个 skill。

可视化与文档生成：
- `draw` — 当用户要把流程、结构、时间线或概念关系画出来时，用这个 skill。
- `document` — 当用户要生成或检查 Word、PPT、Excel 等 Office 文档时，用这个 skill。

系统运维：
- `setup` — 当用户要安装、配置、诊断 ScholarAIO 环境时，优先看这个 skill。
- `metrics` — 当用户要看 token 用量、调用耗时或运行指标时，用这个 skill。

科学计算：
- `scientific-runtime` — 当用户在 ScholarAIO 里处理科学计算 CLI 任务，需要优先走 `toolref`、安全 fallback，并把重点放在解决用户任务而不是维护文档时，用这个 skill。
- `scientific-tool-onboarding` — 当用户要新增或升级某个科学计算工具支持，需要做官方文档入库、`toolref` 集成、轻量 skill 设计和端到端 CLI 验证时，用这个 skill。
- `quantum-espresso` — 当任务涉及 Quantum ESPRESSO 输入变量、工作流或第一性原理计算决策时，用这个 skill。
- `lammps` — 当任务涉及 LAMMPS 势函数、命令或经典材料模拟时，用这个 skill。
- `gromacs` — 当任务涉及 GROMACS 体系搭建、平衡、分析或生物分子动力学工作流时，用这个 skill。
- `openfoam` — 当任务涉及 OpenFOAM 求解器、字典、网格流程、湍流模型或 CFD case 配置时，用这个 skill。
- `bioinformatics` — 当任务涉及 BLAST、minimap2、samtools、bcftools、MAFFT、IQ-TREE、ESMFold 等生物信息学工具链时，用这个 skill。

**新增 skill 的流程：**

工具型 skill（封装 CLI 命令）：
1. 先在 `scholaraio/` 中实现 Python 函数
2. 在 `cli.py` 中暴露为 CLI 子命令
3. 用实际数据测试 CLI 命令确认可用
4. 在 `.claude/skills/<name>/SKILL.md` 中创建 skill 文件

编排型 skill（纯 prompt，如学术写作类）：
1. 在 `.claude/skills/<name>/SKILL.md` 中编写指令，组合调用已有 CLI 命令
2. 无需新增 Python 代码或 CLI 子命令

以上列出的只是基础能力。你可以自由组合这些 CLI 工具和 agent 自身的能力（读写文件、执行代码、多轮推理），发掘出更多玩法，比如批量对比多篇论文的方法差异、自动生成研究趋势报告、从引用图谱中发现被低估的关键论文。工具是有限的，但组合方式是开放的。

### Subagent 信息分层（T1/T2/T3）

当主 agent 委派 subagent 分析论文时，信息按三个层次流动：

| 层 | 内容 | 生命周期 | 消费者 |
|---|------|----------|--------|
| T1 回复 | 精炼结论，直接回答主 agent 的提问 | 进入主 context，随对话压缩消失 | 主 agent（当前对话） |
| T2 笔记 | 论文关键发现、分析要点、跨论文关联 | **持久化到 `notes.md`**，跨会话复用 | 任何未来 agent/会话 |
| T3 完整记录 | 搜索过程、原文引用、推理链 | subagent context 内，不持久化 | 仅 debug 用 |

**T2 笔记约定：**
- 存储路径：`data/papers/<Author-Year-Title>/notes.md`
- 每次分析追加一个 section，格式：`## YYYY-MM-DD | <workspace 名或任务来源> | <skill 名>`
- 内容包括：关键发现、方法特点、与其他论文的对比、值得注意的局限性
- CLI 接口：`scholaraio show "<paper-id>"` 自动展示笔记，`scholaraio show "<paper-id>" --append-notes "..."` 追加笔记
- Python 接口：`loader.load_notes(paper_dir)` 读取，`loader.append_notes(paper_dir, section)` 增量追加

**Subagent 工作流程：**
1. 分析论文前，先用 `scholaraio show "<paper-id>" --layer 1` 查看论文。`show` 命令会自动展示已有的 `notes.md` 历史笔记，有则优先复用，避免重复劳动。但笔记是之前 agent 的分析产物，可能存在遗漏、偏差或过时，应辩证看待；当笔记与当前任务高度相关或结论存疑时，应回到原文（L3/L4）交叉验证
2. 分析完成后，**必须**将值得跨会话保留的发现写入 `notes.md`：
   ```bash
   scholaraio show "<paper-id>" --append-notes "## YYYY-MM-DD | <workspace/任务来源> | <分析类型>
   - 关键发现 1
   - 关键发现 2"
   ```
3. 返回给主 agent 的 T1 回复只包含精炼结论，不包含搜索过程等细节

**主 agent 分派 subagent 时的检查项：**
- 在 subagent prompt 中明确告知目标论文的 paper-id 或目录路径
- **必须**在 prompt 中包含笔记写入指令（见下方模板）
- 如果是重复性查询（同一篇论文），先检查 `notes.md` 是否已有答案

**Subagent prompt 模板（主 agent 分派时必须包含以下段落）：**

```
分析论文 "<paper-id>"，回答以下问题：<具体问题>

工作流程：
1. 先运行 `scholaraio show "<paper-id>" --layer <N>` 查看论文（已有笔记会自动展示，优先复用，但笔记可能有偏差——结论存疑时回原文验证）
2. 完成分析后，**必须**运行以下命令将关键发现写入笔记：
   scholaraio show "<paper-id>" --append-notes "## YYYY-MM-DD | <来源> | <分析类型>
   - 发现 1
   - 发现 2"
3. 返回精炼结论（T1），不要包含搜索过程
```

**Context 管理原则：**
- 工作区论文列表（>30 篇）、论文全文（L4）等大体量内容应由 subagent 处理，仅将结论带回主 context
- 主 agent 中避免直接 dump 长列表，改用 subagent 筛选后返回摘要

## 模块概览

| 模块 | 功能 |
|------|------|
| `config.py` | 配置加载（YAML 多层覆盖 + 路径解析 + API key 查找） |
| `papers.py` | 论文路径工具（遍历/构造论文目录 + `meta.json` 读写 + 论文 UUID 生成） |
| `log.py` | 日志初始化（文件 + 控制台 + 会话追踪） |
| `ingest/mineru.py` | PDF → MinerU Markdown（本地 API / `mineru-open-api` 云端 CLI） |
| `ingest/pdf_fallback.py` | PDF fallback 解析（Docling / PyMuPDF） |
| `ingest/extractor.py` | 元数据提取（regex / auto / robust / llm 四种模式） |
| `ingest/metadata/` | API 查询补全（Crossref / S2 / OpenAlex）、JSON 输出、文件重命名 |
| `ingest/pipeline.py` | 可组合入库流水线（DOI / 专利公开号去重 + pending + 外部导入批量转换） |
| `index.py` | 关键词全文检索 + papers_registry + citations 引用图谱 |
| `vectors.py` | 语义向量 + 增量索引 + GPU 自适应批处理 |
| `topics.py` | BERTopic 主题建模 + 6 种 HTML 可视化 |
| `loader.py` | L1-L4 分层加载 + enrich_toc + enrich_l3 |
| `explore.py` | 多维文献探索（OpenAlex 多维过滤 + 关键词 + 语义 + 融合检索 + 主题，数据隔离在 `data/explore/`） |
| `workspace.py` | 工作区论文子集管理（复用搜索/导出） |
| `document.py` | Office 文档检查（DOCX / PPTX / XLSX 结构/布局/溢出检测） |
| `export.py` | BibTeX / RIS / Markdown 文献列表 / DOCX 导出 |
| `citation_styles.py` | 引用格式管理（内置 APA/Vancouver/Chicago/MLA + 动态加载自定义格式，存于 `data/citation_styles/`） |
| `citation_check.py` | 引用验证（从文本提取 author-year 引用 + 本地库交叉核验） |
| `audit.py` | 数据质量审计 + 修复 |
| `sources/` | 外部来源适配（endnote / zotero / arxiv） |
| `cli.py` | 全量 CLI 入口 |
| `setup.py` | 环境检测 + 安装向导 |
| `metrics.py` | LLM token 用量 + API 计时 |
| `insights.py` | 研究行为分析（热词、阅读趋势、语义近邻推荐、工作区活跃度） |
| `translate.py` | 论文翻译（语言检测 + 并发分块 LLM 翻译 + 批量翻译 + 可选可移植导出） |

CLI 命令一览：`scholaraio --help`

除 skills 之外，当前 CLI 还提供一些值得直接利用的重要能力：
- 检索相关：`search-author`、`embed`、`vsearch`、`usearch`、`fsearch`、`top-cited`
- 图谱相关：`refs`、`citing`、`shared-refs`
- 富化/修复：`enrich-toc`、`enrich-l3`、`backfill-abstract`、`refetch`、`repair`
- 数据维护：`attach-pdf`
- 工作区：`ws`（init / add / remove / show / search / export 等子命令）
- 外部发现与科学运行时：`arxiv`、`toolref`、`insights`、`style`、`document`

## 架构

主入库流：
- PDF 先尝试 `MinerU`（本地 API / `mineru-open-api` 云端 CLI）
- 若 `MinerU` 不可用或失败，则回退到 `pdf_fallback.py`（`Docling → PyMuPDF`）
- 也支持直接放 `.md`，跳过 PDF 解析
- 生成的 Markdown 进入 `extractor.py`
  - Stage 1：从 md 头部提取字段，支持 `regex` / `auto` / `robust` / `llm`
- 之后进入 `metadata/`
  - Stage 2：API 查询补全，输出 `.json`，并按规则重命名
- 然后进入 `pipeline.py`
  - 有 DOI：写入 `data/papers/<Author-Year-Title>/meta.json + paper.md`
  - 有专利公开号：写入 `data/papers/<Author-Year-Title>/`，按公开号去重
  - 无 DOI：转入 `data/pending/` 待人工确认
- 入库后：
  - `index.py` 写入 `data/index.db`（SQLite FTS5）
  - `vectors.py` 写入 `data/index.db`（`paper_vectors` 表）
  - `topics.py` 写入 `data/topic_model/`（BERTopic，复用 `paper_vectors`）
- 最终由 `cli.py` 暴露给 skills 和 coding agent

`explore.py` 独立数据流：
- 通过 OpenAlex API 做多维过滤（ISSN / concept / author / institution / keyword / source-type 等）
- 结果写入 `data/explore/<name>/papers.jsonl`
- 同时维护：
  - `explore.db`（`paper_vectors` + FTS5 全文索引）
  - `faiss.index`（FAISS 语义检索）
  - `topic_model/`（BERTopic 统一格式）和 `viz/`（HTML 可视化）
- 搜索模式支持：语义 / 关键词 / 融合

`workspace.py` 薄层：
- `workspace/<name>/papers.json` 记录指向 `data/papers/` 的论文 UUID
- 搜索 / 导出通过 `paper_ids` 参数注入既有能力（如 `search()` / `vsearch()` / `unified_search()` / `export_bibtex()`）

`import-endnote` / `import-zotero` 外部导入流：
- `sources/endnote.py` / `sources/zotero.py` 负责解析元数据和匹配 PDF
- 之后交给 `pipeline.import_external()`
- 再经 `pipeline.batch_convert_pdfs(enrich=True)` 完成批量 PDF→MD、摘要补全、TOC/L3 提取、embed 和 index

### GPU 自适应批处理

`vectors.py` 的嵌入流程会根据 GPU 显存自动调整 batch size：

1. **首次 Profile**（~10 秒）：从 64 tokens 开始逐步翻倍，测量每个长度的增量显存，直到 OOM
2. **缓存复用**：结果写入 `~/.cache/scholaraio/gpu_profile.json`，key 为 `模型名::GPU名`，换 GPU/模型自动重测
3. **运行时分桶**：按 token 长度将文本分组（64/128/.../16384），每组根据 profile 插值算出最优 batch_size
4. **OOM 兜底**：遇 OOM 自动减半 batch_size 重试，bs=1 仍 OOM 则降级 CPU

所有调用 `_embed_batch()` 的路径（主库 embed、explore embed、BERTopic 的 QwenEmbedder）均自动受益。

### 分层加载设计（L1-L4）

| 层 | 内容 | 来源 |
|----|------|------|
| L1 | title, authors, year, journal, doi, volume, issue, pages, publisher, issn | JSON 文件 |
| L2 | abstract | JSON 字段 |
| L3 | 结论段 | JSON 字段（需先运行 enrich-l3 提取） |
| L4 | 全文 markdown | 直接读 .md |

### data/papers/ 目录结构

```
data/papers/
└── <Author-Year-Title>/
    ├── meta.json    # L1+L2+L3 元数据（含 "id": "<uuid>"）
    ├── paper.md     # L4 来源（MinerU 输出）
    ├── notes.md     # Agent 分析笔记（T2 层，可选，按需创建/追加）
    ├── paper_{lang}.md # 翻译版本（如 paper_zh.md，可选）
    ├── images/      # MinerU 提取的图片（md 中引用）
    ├── layout.json  # MinerU 版面分析结果（可选）
    └── *_content_list.json  # MinerU 结构化内容（可选）
```

每篇论文一个目录，UUID 作为内部唯一标识（写入 `meta.json["id"]`，永不改变）。
目录名为人类可读的 `Author-Year-Title`，rename 只改目录名。
`data/index.db` 中 `papers_registry` 表提供 UUID ↔ DOI ↔ dir_name 双向查找。

可移植翻译导出会写到：

```text
workspace/translation-ws/
└── <Author-Year-Title>/
    ├── paper_{lang}.md
    └── images/
```

### data/inbox/ 目录

```
data/inbox/
├── paper.pdf     # 待入库 PDF（pipeline 处理后删除）
└── paper.md      # 或直接放 .md（跳过 MinerU，直接入库）
```

### data/inbox-thesis/ 目录

```
data/inbox-thesis/
└── thesis.pdf    # 学位论文 PDF（自动标记 paper_type: thesis，跳过 DOI 去重）
```

Paper types: `article`（默认）、`thesis`、`patent`、`book`、`document`（含 `technical-report` / `lecture-notes` 等子类型）。

注：普通 inbox 中无 DOI 的论文会由 LLM 自动判断是否为 thesis。是则标记入库，否则转 pending。
thesis inbox 跳过此判断，直接标记入库。

### data/inbox-patent/ 目录

```
data/inbox-patent/
└── patent.pdf    # 专利 PDF（自动提取公开号，按公开号去重，标记 patent）
```

注：支持的公开号格式：CN/US/EP/WO/JP/KR/DE/FR/GB/TW/TWI/IN/AU/CA/RU/BR + 6位以上数字 + 类型码（如 CN112345678A、US10123456B2、TWI694356B）。

### data/inbox-doc/ 目录

```
data/inbox-doc/
├── report.pdf    # 非论文文档 PDF（技术报告、标准、讲义等）
├── notes.md      # 或直接放 .md
├── report.docx   # Word 文档（MarkItDown 转换）
├── data.xlsx     # Excel 表格（MarkItDown 转换）
└── slides.pptx   # PowerPoint（MarkItDown 转换）
```

非论文文档入库流程：
- **Office 文件**（`.docx` / `.xlsx` / `.pptx`）：先通过 `step_office_convert`（MarkItDown）转为 `.md`，再走后续步骤
- 跳过 DOI 去重和 API 查询
- LLM 自动生成标题和摘要（确保检索可用）
- 无 LLM 时降级：第一个 markdown 标题或文件名 → 标题，前 500 词 → 摘要
- paper_type 标记为 `document`（或 `technical-report` / `lecture-notes` 等具体类型）
- 审计规则对 document / patent 类型不报 missing_doi 警告

超长 PDF 会在 MinerU 转换前按需自动切分：
- 本地 MinerU 遵循 `chunk_page_limit`（默认 >100 页）
- MinerU 云端当前需要按更严格的有效阈值自动切分（>200 页或 >200MB），因为 `mineru-open-api extract` 现网在 PDF 超过 200 页时会直接返回 `-60006`，即使网页文档仍可能写 600 页

### data/pending/ 目录

```
data/pending/
└── <PDF-stem>/
    ├── paper.md           # 无 DOI 的论文 markdown
    ├── <原始文件名>.pdf    # 原始 PDF（如有）
    ├── pending.json       # 标记文件（含原因、已提取的元数据）
    ├── images/            # MinerU 提取的图片（如有）
    ├── layout.json        # MinerU 版面信息（如有）
    └── *_content_list.json # MinerU 结构化内容（如有）
```

pending.json 中 `issue` 字段标识原因：
- `no_doi` — 无 DOI 且非 thesis/patent，需人工确认后补充 DOI 再入库
- `no_pub_num` — 专利 inbox 未提取到公开号，需人工确认或补录公开号
- `duplicate` — DOI 或专利公开号与已入库论文重复（含 `duplicate_of` 字段指向已有论文目录名），用户可决定覆盖

注：thesis 自动入库（来自 thesis inbox 或 LLM 判定），不经过 pending。
patent 自动入库（来自 patent inbox），按公开号去重，不经过 pending。

**注意**：`audit` 命令报告的 `missing_md`（缺少 paper.md）是 `data/papers/` 中已入库论文的质量问题，与 `data/pending/` 的状态无关。pending 只包含入库流程中被拦截的论文（缺 DOI 或重复）；`missing_md` 表示已入库但未经 MinerU 解析，无法进行全文检索。

### data/explore/ 目录

```
data/explore/<name>/
├── papers.jsonl        # OpenAlex 拉取的全量论文（title/abstract/authors/year/doi/cited_by_count）
├── meta.json           # 探索库元信息（查询参数/count/fetched_at）
├── explore.db          # SQLite（paper_vectors 表 + explore_fts FTS5 全文索引）
├── faiss.index         # FAISS IndexFlatIP（cosine similarity）
├── faiss_ids.json      # FAISS index 对应的 paper_id 列表
└── topic_model/
    ├── bertopic_model.pkl   # BERTopic 模型（统一格式，与主库相同）
    ├── scholaraio_meta.pkl  # 附加元数据（paper_ids/metas/topics/embeddings/docs）
    ├── info.json            # 统计（n_topics/n_outliers/n_papers）
    └── viz/                 # 6 种 HTML 可视化
```

### sources/ 抽象层

`papers.py` 是本地论文库 `data/papers/` 的路径 helper 层，模块直接通过它遍历论文目录并读取 `meta.json`。
`sources/` 主要承载 arXiv、Endnote、Zotero 等外部来源适配器。

## 配置

主配置：`config.yaml`（进 git）
敏感信息：`config.local.yaml`（不进 git，覆盖 config.yaml）

config.yaml 查找顺序：
1. 显式传入的 `config_path`
2. 环境变量 `SCHOLARAIO_CONFIG`
3. 当前工作目录逐级向上查找（最多 6 级）
4. `~/.scholaraio/config.yaml`（全局配置，插件模式使用）

所有相对路径（`data/papers`、`data/index.db` 等）基于 config.yaml 所在目录解析。
在项目目录内使用时，路径指向项目下的 `data/`；作为插件使用时，全局 config 使路径指向 `~/.scholaraio/data/`。

LLM API key 查找顺序：
1. `config.local.yaml` 中的 `llm.api_key`
2. 环境变量 `SCHOLARAIO_LLM_API_KEY`（通用，任意 backend）
3. 按 backend 查找对应厂商环境变量：
   - `openai-compat`: `DEEPSEEK_API_KEY` → `OPENAI_API_KEY`
   - `anthropic`: `ANTHROPIC_API_KEY`
   - `google`: `GOOGLE_API_KEY` → `GEMINI_API_KEY`

默认 LLM 后端：DeepSeek (`deepseek-chat`)，OpenAI 兼容协议。
支持三种 backend 协议：`openai-compat`（DeepSeek / OpenAI / vLLM / Ollama）、`anthropic`、`google`（Gemini）。
`ingest.extractor: robust`（默认）— regex + LLM 双跑，LLM 校正 OCR 错误 + 全文 multi-DOI 检测。其他模式：`auto`（LLM 仅兜底）、`regex`（纯正则）、`llm`（纯 LLM）。

MinerU 配置约束（与当前代码一致）：
- 面向用户时优先保持极简，不要主动暴露高级 MinerU 参数
- `mineru_model_version_cloud` 仅建议 `pipeline` 或 `vlm`；`MinerU-HTML` 不应作为 PDF ingest 默认配置
- `mineru_parse_method` 对云端精确解析 API 只有 `ocr` 会映射为官方 `file.is_ocr=true`；`auto` / `txt` 都按默认非强制 OCR 处理
- `mineru_enable_formula`、`mineru_enable_table`、`mineru_lang` 仅对云端 `pipeline` / `vlm` 生效；无明显需求时保留默认值
- `mineru_backend_local` 仅在用户明确自建本地 MinerU 时讨论；纯云端场景通常不需要碰
- `mineru_batch_size` 官方上限为 `200`；默认值保持保守即可
- 当前默认建议：
  - 中文或中英混排 PDF：`mineru_lang: ch`
  - 纯英文 PDF：再改 `mineru_lang: en`

翻译配置（`config.yaml`）：
```yaml
translate:
  auto_translate: false   # 入库时是否自动翻译
  target_lang: zh          # 目标语言（zh/en/ja/ko/de/fr/es）
  chunk_size: 4000         # 分块大小
  concurrency: 20          # 总翻译并发预算（单篇时用于 chunk 并发，批量时会在论文间分摊）
```

## 代码风格

- **Docstrings**：库模块（`index.py`、`loader.py`、`vectors.py` 等）的公共 API 函数使用 Google-style docstrings（含 Args / Returns / Raises）。CLI handler 函数（`cli.py` 中的 `cmd_*`）不加 docstring。
- **用户界面文本**：CLI 输出、帮助文本、错误提示用中文。
- **代码注释**：英文，仅在逻辑不自明时添加。

## 新用户引导

### 本地使用（clone repo）

当检测到项目尚未配置完成时，使用 `scholaraio setup` 引导用户：

1. **诊断**：运行 `scholaraio setup check` 查看当前状态（缺什么一目了然）
2. **安装**：`pip install -e .`（核心）或 `pip install -e ".[full]"`（全部功能）
3. **配置**：运行 `scholaraio setup` 交互式向导（bilingual EN/ZH），自动创建 `config.yaml` + `config.local.yaml`
4. **目录**：CLI 启动时自动创建（`ensure_dirs()`），无需手动操作

### 插件使用（Claude Code plugin / skill market）

用户可以在任意项目中通过插件系统安装 ScholarAIO skills：

```
/plugin marketplace add ZimoLiao/scholaraio
/plugin install scholaraio@scholaraio-marketplace
```

首次打开新会话时，SessionStart hook 自动完成：
1. 检测并安装 `scholaraio` Python 包
2. 创建全局配置 `~/.scholaraio/config.yaml`
3. 创建数据目录 `~/.scholaraio/data/`

插件模式下所有数据存放在 `~/.scholaraio/`：

```
~/.scholaraio/
├── config.yaml           # 全局配置（从插件 bundle 复制）
├── config.local.yaml     # API keys（用户手动创建或通过 setup 向导）
├── data/
│   ├── papers/           # 已入库论文
│   ├── inbox/            # 待入库 PDF
│   ├── inbox-thesis/     # 学位论文
│   ├── inbox-patent/     # 专利
│   ├── inbox-doc/        # 非论文文档
│   ├── pending/          # 待确认
│   ├── explore/          # 文献探索数据
│   ├── topic_model/      # 主题模型
│   ├── index.db          # SQLite 索引
│   └── metrics.db        # 调用指标
└── workspace/            # 工作区
```

skills 的具体调用形式取决于宿主 agent / 插件系统；本仓库只保证技能定义位于 `.claude/skills/`，并通过 `.agents/skills`、`.qwen/skills` 与 `skills/` 三个符号链接暴露给不同发现机制。

### API key 说明

- **LLM key**（DeepSeek / OpenAI）：元数据提取 + 内容富化。不配置则降级为纯正则，enrich 不可用
- **MinerU token**：`mineru-open-api extract` 所用的 MinerU 云端 PDF 转 Markdown 令牌。优先使用 `MINERU_TOKEN`，`MINERU_API_KEY` 保留兼容。不配置时 ScholarAIO 仍可回退到 Docling / PyMuPDF，或手动放 `.md` 入库
- 嵌入模型（Qwen3-Embedding-0.6B，~1.2GB）首次 embed/vsearch 时自动下载。海外用户在 `config.yaml` 中将 `embed.source` 改为 `huggingface`

## 关键约定

- **工作区隔离**：用户的写作、笔记、草稿等输出内容一律放在 `workspace/` 目录。创建新文件时（如文献综述、调研笔记），默认放在 `workspace/` 下，不要在项目根目录或 `scholaraio/` 源码目录下创建用户内容文件
- **工作区版本管理**：涉及代码开发的 workspace 子目录（如复现项目、数据分析脚本）应使用 `git init` 进行内部版本管理，并添加 `.gitignore` 排除 `__pycache__/`、`.venv/`、大型数据文件等。这不影响 scholaraio 主仓库（`workspace/` 已在主 `.gitignore` 中）
- **不修改 `scholaraio/ingest/metadata/_extract.py` 的正则逻辑**，只通过 extractor 抽象层扩展
- `data/`、`workspace/` 不进 git（`.gitignore` 已配置）
- Python 3.10+，运行环境：conda `scholaraio`
- 测试：`python -m pytest tests/ -v`

## 多 Agent 兼容

本项目同时支持多种 AI coding agent。`AGENTS.md` 是通用项目指令，`CLAUDE.md` 是 Claude Code 兼容版本。两者应保持技术内容尽量一致，仅在 agent 原生发现机制、命名和极少量入口说明上有所区别。

| Agent | 指令文件 | Skills |
|-------|---------|--------|
| Claude Code | `CLAUDE.md` | `.claude/skills/` |
| Codex (OpenAI) | `AGENTS.md`（本文件） | `.agents/skills/` → `.claude/skills/` |
| OpenClaw | `AGENTS.md`（本文件） | `.agents/skills/` → `.claude/skills/` |
| Cursor | `.cursor/rules/scholaraio.mdc`（Project Rule → 指向 `AGENTS.md`）+ `.cursorrules` 旧版 fallback | — |
| Windsurf | `.windsurfrules`（wrapper → 指向 `AGENTS.md`） | — |
| GitHub Copilot | `.github/copilot-instructions.md`（wrapper → 指向 `AGENTS.md`） | — |
| Cline | `.clinerules`（wrapper → 指向 `AGENTS.md`） | `.claude/skills/`（原生支持） |
| Qwen | — | `.qwen/skills/` → `.claude/skills/` |

Skills 采用 [AgentSkills.io](https://agentskills.io) 开放标准（`SKILL.md` 格式）。规范位置为 `.claude/skills/`；`.agents/skills/` 是面向跨 agent 发现的符号链接，`.qwen/skills/` 是面向 Qwen agent 发现的符号链接，`skills/` 是面向 Claude 插件/技能系统发现的符号链接。

### 插件打包

项目同时是一个 Claude Code plugin + marketplace：

```
.claude-plugin/
├── plugin.json          # 插件身份（name/version/description/keywords）
└── marketplace.json     # 市场目录（/plugin marketplace add 使用）
skills/ → .claude/skills/  # 插件系统的 skill 发现入口
hooks/hooks.json           # SessionStart hook（自动安装依赖 + 创建全局 config）
scripts/check-deps.sh     # hook 调用的依赖检测/安装脚本
```

用户可通过 `/plugin marketplace add ZimoLiao/scholaraio` 安装。SkillsMP 等 skill market 通过爬取 GitHub `filename:SKILL.md` 自动索引。
