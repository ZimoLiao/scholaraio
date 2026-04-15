# ScholarAIO 升级、重构、完善方案书

> 内部开发文档。用于仓库内的重构与治理规划，不接入公开文档导航，也不纳入公开站点展示。

日期：2026-04-16

作者：Codex（基于本仓库代码、测试、文档、skills、外部最佳实践调研整理）

适用对象：项目作者、核心维护者、后续协作者

---

## 0. 先说结论

ScholarAIO 现在还不是“屎山”。

但它已经到了一个很关键的阶段：

- 底子是好的：测试全绿、核心数据流清楚、没有明显循环依赖、功能确实能跑。
- 风险也已经出现了：入口文件过大、文档重复、skill 边界开始变糊、知识在多个地方重复维护。

一句大白话总结：

现在最该做的，不是把整个项目推倒重写，而是“趁房子结构还稳，赶紧做一次系统装修和线路整理”。

如果继续一边加功能、一边把说明都往 `AGENTS.md`、`CLAUDE.md`、大 skill、大 CLI 文件里堆，后面维护成本会越来越高，最后就会真的变成屎山。

所以当前阶段最合理的策略是：

1. 保住现有对外接口，不大改用户入口。
2. 先做结构治理，再继续大规模扩功能。
3. 把“常驻规则”“按需工作流”“给人看的文档”“给 agent 的上下文”彻底分开。

---

## 1. 这份方案书是怎么得出来的

这不是拍脑袋写的，是我按下面几条线并行做出来的。

### 1.1 本地代码和文档摸底

我重点看了这些东西：

- `scholaraio/cli.py`
- `scholaraio/ingest/pipeline.py`
- `scholaraio/config.py`
- `scholaraio/index.py`
- `scholaraio/loader.py`
- `scholaraio/explore.py`
- `scholaraio/toolref/*`
- `.claude/skills/*`
- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `docs/*`

### 1.2 运行验证

我本地实际跑了测试，不是只看文件名。

结果：

- 全量测试：`807 passed in 93.15s`
- 说明项目当前整体可运行性是比较强的

这点很重要，因为它说明现在不需要“推倒重建”，而是应该“边保运行边治理结构”。

### 1.3 结构量化

我额外做了几项量化检查：

- `scholaraio/cli.py`：4128 行
- `scholaraio/ingest/pipeline.py`：2621 行
- `AGENTS.md`：531 行
- `CLAUDE.md`：531 行
- `AGENTS.md` 与 `CLAUDE.md` 相似度：99.43%
- 顶层 CLI 命令数：38 个
- skills 数量：40 个
- skill 中位长度：119 行
- 超过 200 行的 skill：7 个
- 超过 300 行的 skill：2 个
- 内部 Python 模块循环依赖：0

这组数据说明：

- 架构还没烂掉
- 但“入口膨胀”和“文档重复”已经非常明显

---

## 2. 当前项目最值得肯定的地方

如果只批评，不指出优势，方案会失真。

ScholarAIO 目前最有价值的，不是单个功能，而是已经形成了几条很对的主线。

### 2.1 数据目录和研究工作流是成体系的

项目不是随便堆功能，而是围绕科研流程组织的：

- 搜索
- 阅读
- 富化
- 分析
- 写作
- 导出
- 工具文档查阅

这意味着它有“产品方向”，不是纯脚本集合。

### 2.2 有几个关键模块边界其实已经很好

最明显的是：

- `papers.py`
  - 它像一个“路径真相源”
  - 大意就是：论文目录的路径规则，大家不要各自乱拼
- `loader.py`
  - 它把论文阅读分成 L1-L4 四层
  - 这个设计非常适合 agent，因为 agent 不应该一上来就读全文
- `toolref`
  - 已经开始形成“稳定公开入口 + 内部实现可重构”的思路

这三类设计都值得保住。

### 2.3 测试覆盖面不错

不仅有普通单元测试，还有几类很关键的测试：

- 文档对齐测试
- skill 路由冒烟测试
- CLI 文案测试
- toolref 兼容性测试

这说明项目已经开始从“能跑”走向“可维护”。

### 2.4 多 agent / 多宿主适配做得早

当前仓库已经考虑了：

- Claude Code
- Codex / OpenClaw
- Cursor
- Cline
- Qwen
- Windsurf
- Copilot

这件事做得早，有好处也有代价：

- 好处：你一开始就在构建“可复用 agent 基建”
- 代价：文档和入口容易重复维护

---

## 3. 当前最危险的四个问题

### 3.1 问题一：CLI 入口过胖

代表文件：

- `scholaraio/cli.py`

问题不是“它很长”这么简单，而是它同时承担了太多角色：

- 命令注册
- 参数解析
- 输出格式化
- 跨模块编排
- 一部分业务逻辑
- 一部分容错逻辑

这会带来几个后果：

- 新人不敢动
- 改一个命令时容易碰到别的命令
- CLI 和业务层很难真正分开测试
- 后续如果想做 API、MCP、Web 界面，复用成本高

一句大白话：

现在的 `cli.py` 已经像“前台、客服、仓库管理员、调度员都坐在同一个房间里”。

### 3.2 问题二：pipeline 已经开始变成“总杂物间”

代表文件：

- `scholaraio/ingest/pipeline.py`

这个文件里现在混了很多层责任：

- inbox 扫描
- 文件类型分流
- Office 转 Markdown
- PDF 转 Markdown
- 元数据提取
- 去重
- 入库
- 富化
- 批处理
- 后处理
- 状态统计

这些事情不是不能放在一个大流程里，但不应该都塞在一个文件里。

风险是：

- 以后每加一个新 inbox 或新步骤，复杂度继续上升
- Bug 容易藏在“流程分支”里
- 很难解释“哪一层负责什么”

### 3.3 问题三：`AGENTS.md` / `CLAUDE.md` 过长且重复

这是当前最明显、也最容易先动手治理的问题。

这两个文件现在同时承担了四种完全不同的职责：

1. 项目定位
2. agent 行为规范
3. 架构说明
4. 命令和模块速查

于是结果就变成：

- 内容太长
- 复制过多
- 改一处要同步多处
- agent 每次都读大段重复信息

更关键的是，这违反了现在主流 agent 生态越来越明确的一条原则：

`AGENTS.md` / `CLAUDE.md` 应该放“稳定、常驻、不会频繁变化”的内容；
复杂流程、长说明、专门操作手册，应该放到 skills 或 docs 里按需加载。

### 3.4 问题四：部分 skill 已经从“工作流”变成“第二份文档手册”

典型例子：

- `.claude/skills/document/SKILL.md`
- `.claude/skills/draw/SKILL.md`
- `.claude/skills/setup/SKILL.md`

它们本来应该做的事是：

- 告诉 agent 什么时候该用这个 skill
- 用什么流程解决问题
- 遇到什么边界怎么退化处理

但现在其中一部分已经写成了：

- 大量 API 样例
- 大段命令说明
- 大片参考内容

这会有两个问题：

1. 主 skill 文件变重
2. 后续信息更新时，很难维护

换句话说：

skill 的主文件应该更像“作战步骤卡”，而不是“厚说明书”。

---

## 4. 我对当前架构的判断

### 4.1 现在不是烂架构，而是“正在从好架构走向高耦合”

“耦合”这个词，大白话解释一下：

就是很多东西绑得太紧，动一个地方，别的地方也容易被带着抖。

ScholarAIO 现在的情况不是已经散架，而是有这种趋势。

### 4.2 当前架构的真实状态

我把它概括成一句话：

“核心能力层基本可用，入口层和说明层开始发胖。”

更具体点：

- 能力层：
  - `index`
  - `loader`
  - `papers`
  - `toolref`
  - `vectors`
  - `explore`
  - 这些模块大体上各管各的，方向是对的
- 入口层：
  - `cli.py`
  - `pipeline.py`
  - 这里开始承担过多调度职责
- 说明层：
  - `AGENTS.md`
  - `CLAUDE.md`
  - 若干超长 skill
  - 这里开始重复堆信息

### 4.3 这一阶段最不该做什么

最不该做的是：

- 大规模重命名命令
- 改数据目录协议
- 一口气重写全部 skill
- 不做迁移层直接重排包结构

这会伤到项目当前最有价值的部分：

- 已有测试
- 已有用户习惯
- 已有跨 agent 入口

---

## 5. 外部最佳实践对 ScholarAIO 的启发

下面这些不是拿来照抄的，而是用来判断“世界先进项目现在怎么做”。

### 5.1 Anthropic / Claude Code 的启发

关键信号有三条：

1. `CLAUDE.md` 应该放持久上下文，不该塞太多流程细节。
2. skill 的正文只在需要时加载，长流程应该拆 skill，不该都塞进 `CLAUDE.md`。
3. skill 的 `description` 非常关键，要写清楚“它做什么、什么时候用、用户会怎么说”。

这和 ScholarAIO 现状一对比，结论很清楚：

- 你的方向是对的
- 但 `AGENTS.md/CLAUDE.md` 还没有真正瘦下来
- 部分 skill 也还没有真正做到“按需加载”

### 5.2 Agent Skills 官方规范的启发

Agent Skills 官方规范里有两条特别重要：

1. 主 `SKILL.md` 最好控制在合理长度，详细参考资料放 `references/`
2. 采用“渐进加载”

“渐进加载”用大白话说就是：

- 先给模型一个简版目录
- 真需要时再读细节

这和 ScholarAIO 本身的 L1-L4 论文分层理念其实是非常一致的。

也就是说：

你项目最该做的，不是再发明一套文档哲学，而是把自己的“分层读取思想”也应用到 skill 和 agent 文档上。

### 5.3 OpenHands 的启发

OpenHands 现在也把上下文分成三类：

- 永久加载的项目规则
- 触发加载的 skill
- 更深层的渐进式资源

这个模型和 ScholarAIO 很契合。

所以你完全可以借这个思路，把仓库里的信息分成三层：

1. `AGENTS.md/CLAUDE.md`：常驻规则
2. `SKILL.md`：任务工作流
3. `references/`：详细说明

### 5.4 OpenAI Codex 的启发

OpenAI 官方讲 Codex 使用经验时，明确提到：

- `AGENTS.md` 适合放命名约定、业务规则、已知坑
- prompt 最好像 GitHub issue 一样具体、结构化

对 ScholarAIO 的启发是：

- `AGENTS.md` 不该当百科全书
- 它应该更像“这个仓库的长期操作须知”

### 5.5 Vercel 的启发

Vercel 有两条很值得重视：

1. 技能文件要短，触发词要准，支持资料要分出去
2. 好 agent 往往不是工具越多越好，而是上下文更清晰、文件系统更可读

ScholarAIO 非常适合吸收这个思路。

因为你本来就是一个“文件系统很重要”的项目：

- `data/papers/`
- `data/explore/`
- `workspace/`
- `toolref` 缓存

这些都说明：仓库本身就是 agent 的工作台，不需要再给它叠一大层复杂抽象。

### 5.6 Aider 的启发

Aider 很强调一件事：

让模型先理解 repo 的结构，再做编辑。

ScholarAIO 现在最缺的，不是更多 feature，而是更好的“仓库地图”。

这可以通过两件事补：

- 更清晰的 architecture docs
- 更薄、更稳定的 `AGENTS.md`

### 5.7 Diataxis 的启发

Diataxis 是一个文档框架，可以粗暴理解成四类文档不要混着写：

1. 教程：带新人上手
2. How-to：告诉人怎么做一件事
3. Reference：参数和接口手册
4. Explanation：解释为什么这样设计

你现在的问题就是这四种经常混在一起了。

---

## 6. 10 轮收敛后的最终判断

下面这 10 条，是我把本地代码理解和外部最佳实践来回对照后得到的最终结论。

### 第 1 轮

项目当前健康度高于“应该重写”的程度。

### 第 2 轮

真正的危险不是功能不够，而是入口和说明越来越胖。

### 第 3 轮

要优先保住 `papers.py`、`loader.py`、`toolref` 这种已经形成明确边界的模块。

### 第 4 轮

`cli.py` 必拆，但只能做“分文件重构”，不能先改命令名。

### 第 5 轮

`pipeline.py` 必拆，但只能先拆职责，不能先换协议。

### 第 6 轮

`AGENTS.md` 和 `CLAUDE.md` 必瘦身，而且应改为“入口文件”，不再做百科全书。

### 第 7 轮

skill 体系方向正确，但要从“重文档 skill”回到“轻工作流 skill”。

### 第 8 轮

文档站必须补 `architecture/`，否则 README、AGENTS、guide 会反复重复架构说明。

### 第 9 轮

以后新能力进入仓库时，必须同时经过“代码、测试、文档、agent 路由”四道门。

### 第 10 轮

现在最适合做的是“结构治理期”，不是“继续猛堆功能期”。

---

## 7. 升级总策略：旧门牌不动，内部重装

### 7.1 这句话的含义

“旧门牌不动”是说：

- CLI 命令名尽量不改
- 目录结构协议尽量不改
- skill 名尽量不改
- 对外能力表述尽量不改

“内部重装”是说：

- 模块内部拆层
- 文档重新分工
- skill 主文件瘦身
- 自动生成重复清单

### 7.2 为什么这样做

因为当前项目最值钱的，是已经积累下来的这些东西：

- 测试
- 用户习惯
- agent 入口
- 技术路线

重写最容易把这些都打掉。

---

## 8. 分阶段重构方案

## Phase 0：冻结接口，先建治理规则

目标：防止项目在治理过程中越改越乱。

必须先立的规矩：

1. 单文件超过 1500 行，进入预警
2. `SKILL.md` 超过 200 行，必须评估是否拆 `references/`
3. 同一事实不能在三个地方手写维护
4. 新功能合并前必须补四样：
   - 代码
   - 测试
   - 用户文档
   - agent 路由

建议新增文档：

- `docs/architecture/governance.md`

## Phase 1：先治文档，不先动业务

这是最值得马上开始的一阶段。

### 8.1 重写 `AGENTS.md`

建议新结构：

1. 项目一句话定义
2. 这个仓库的硬规则
3. 稳定入口
4. skills 发现规则
5. 数据目录速查
6. 去哪里看详细文档

控制目标：

- 120 到 200 行
- 不放大段模块介绍
- 不放冗长 skill 列表解释
- 不放大段架构说明

### 8.2 重写 `CLAUDE.md`

原则：

- 只保留 Claude 专属说明
- 其余内容与 `AGENTS.md` 共用
- 不再复制 500 行

### 8.3 建 `docs/architecture/`

建议拆成：

- `docs/architecture/overview.md`
- `docs/architecture/data-model.md`
- `docs/architecture/agent-surfaces.md`
- `docs/architecture/ingest-pipeline.md`
- `docs/architecture/search-and-index.md`
- `docs/architecture/skill-system.md`

### 8.4 把 README 的角色限制住

README 只做这几件事：

- 项目是什么
- 为什么有用
- 怎么快速开始
- 主要能力有哪些
- 去哪里看细节

不要再让 README 承担“半本手册”的职责。

## Phase 2：skill 瘦身

### 8.5 skill 改写总原则

每个 skill 主文件只保留：

1. 什么时候用
2. 不什么时候用
3. 主流程
4. 关键边界
5. 调用哪些 CLI / 下游 skill

详细内容放：

- `references/`
- `scripts/`
- `assets/`

### 8.6 第一批优先处理的 skill

按优先级建议：

1. `document`
2. `draw`
3. `setup`
4. `scientific-tool-onboarding`
5. `bioinformatics`

原因很简单：

- 这些 skill 本身很有用
- 但主文件已经有“说明书化”的趋势

### 8.7 skill 描述字段统一改造

现在大部分 skill 的 `description` 主要是英文。

建议改成：

- 保留英文关键词
- 补充常见中文触发词
- 写明“不适用场景”

原因：

- 更适合中文用户输入
- 更利于 agent 自动匹配

## Phase 3：CLI 拆文件

### 8.8 目标结构

建议把 CLI 改成类似这样：

```text
scholaraio/cli/
  __init__.py
  main.py
  parser.py
  common.py
  formatters.py
  commands/
    search.py
    show.py
    ingest.py
    export.py
    workspace.py
    toolref.py
    setup.py
```

### 8.9 拆法原则

先拆“命令定义”和“命令执行函数”的文件位置，不先改逻辑。

也就是说：

- 参数名先不改
- 输出文案先不大改
- 命令行为先不改

先把文件边界理顺。

## Phase 4：pipeline 拆职责

### 8.10 目标结构

建议把 ingest pipeline 拆成：

```text
scholaraio/ingest/
  pipeline/
    __init__.py
    context.py
    registry.py
    runner.py
    inbox.py
    postprocess.py
    detect.py
    steps/
      office.py
      mineru.py
      extract.py
      dedup.py
      ingest.py
      enrich.py
      index.py
```

### 8.11 拆法原则

只拆“职责”，不先换“流程协议”。

比如：

- `InboxCtx` 可以保留
- `STEPS` / `PRESETS` 可以保留
- CLI 的 `pipeline full`、`pipeline ingest` 等名字先保留

这样风险最低。

## Phase 5：自动生成重复文档

建议自动生成的内容：

- CLI 命令参考
- skills 索引页
- 多 agent wrapper 的能力速查

原因：

现在这些信息很多地方都在手写同步，后面非常容易漂。

## Phase 6：加“真实任务评测”

当前测试已经很多了，但还缺一类东西：

面向真实用户任务的回放测试。

建议至少补这些场景：

1. 搜索论文
2. show 摘要 / 结论
3. 导入后 enrich
4. `toolref show/search`
5. academic-writing 路由
6. technical-report 路由
7. setup 推荐解析器
8. 生成 DOCX / PPTX

---

## 9. 文档重写蓝图

### 9.1 文档应该怎么分层

建议以后固定采用这套分工：

### A. 给人看的产品文档

- `README.md`
- `docs/getting-started/*`
- `docs/guide/*`

### B. 给人看的架构文档

- `docs/architecture/*`

### C. 给 agent 的常驻上下文

- `AGENTS.md`
- `CLAUDE.md`
- 各宿主薄包装文件

### D. 给 agent 的任务工作流

- `.claude/skills/*/SKILL.md`

### E. 给 agent 的详细参考

- `.claude/skills/*/references/*`
- `.claude/skills/*/scripts/*`

### 9.2 一条简单判断规则

如果一段内容回答的是：

- “这个项目是什么、有哪些硬规则”
  - 放 `AGENTS.md`
- “这件事怎么做”
  - 放 skill
- “为什么这么设计”
  - 放 architecture docs
- “参数有哪些、命令怎么写”
  - 放 reference docs

### 9.3 对 `AGENTS.md` 的一句硬建议

`AGENTS.md` 不该再做“项目百科全书”，它应该变成“项目操作宪法”。

---

## 10. skill 设计改写模板

下面这套模板可以直接作为后续统一风格。

```text
---
name: xxx
description: 它做什么。什么时候用。用户可能会怎么说。哪些情况不要用。
---

# 这个 skill 是干什么的

## 什么时候用

## 不什么时候用

## 主流程
1. ...
2. ...
3. ...

## 关键边界
- ...

## 相关命令 / 下游 skill
- ...

## 详细资料
- references/xxx.md
- scripts/xxx.py
```

重点是：

- 主文件轻
- 资料外置
- 触发明确

---

## 11. 未来 3 个月最合理的执行顺序

### 第 1 周

- 精简 `AGENTS.md`
- 精简 `CLAUDE.md`
- 新建 `docs/architecture/`

### 第 2 周

- 重写 `document` skill
- 重写 `draw` skill
- 重写 `setup` skill

### 第 3 到 4 周

- 拆 `cli.py`
- 先拆 parser 和 command handler

### 第 5 到 6 周

- 拆 `pipeline.py`
- 保持外部行为不变

### 第 7 到 8 周

- 自动生成 CLI reference
- 自动生成 skill index
- 加文档漂移检查

### 第 9 到 12 周

- 上真实任务评测
- 再决定是否继续做更深层抽象

---

## 12. 什么叫“治理完成”

不是说代码变短就算完成。

我建议用下面这些标准判断：

1. 新人能在 30 分钟内看懂主要结构
2. `AGENTS.md` 能在 3 分钟内读完核心规则
3. skill 主文件普遍不再像厚说明书
4. `cli.py` 不再是四千行单文件
5. `pipeline.py` 的职责边界能一句话讲清
6. CLI、文档、skill 的重复信息明显减少
7. 新功能加入时，不再需要在 6 个地方手工同步说明

---

## 13. 最后一句判断

ScholarAIO 当前最难得的地方，是它已经有了“研究工作台”的整体方向，而且代码并没有坏到要重来。

所以现在最值钱的选择不是“推翻”，而是“定规矩、拆入口、瘦文档、收边界”。

这一步做完，后面再扩功能，项目才会越长越稳；
不做这一步，后面每多一个能力，维护成本都会更快上涨。

---

## 14. 本次分析的关键证据

### 本地仓库证据

- 全量测试通过：`807 passed`
- 循环依赖：`0`
- `scholaraio/cli.py`：4128 行
- `scholaraio/ingest/pipeline.py`：2621 行
- `AGENTS.md` / `CLAUDE.md`：各 531 行
- `AGENTS.md` / `CLAUDE.md` 相似度：99.43%

### 重点参考资料

- Anthropic Claude Code skills 文档  
  https://code.claude.com/docs/en/skills
- Anthropic Claude Code subagents 文档  
  https://code.claude.com/docs/en/sub-agents
- Anthropic《The Complete Guide to Building Skill for Claude》  
  https://resources.anthropic.com/hubfs/The-Complete-Guide-to-Building-Skill-for-Claude.pdf
- Agent Skills 官方规范  
  https://agentskills.io/specification
- OpenHands Agent Skills & Context  
  https://docs.openhands.dev/sdk/guides/skill
- OpenAI《How OpenAI uses Codex》  
  https://cdn.openai.com/pdf/6a2631dc-783e-479b-b1a4-af0cfbd38630/how-openai-uses-codex.pdf
- Vercel《Anatomy of a Skill》  
  https://vercel.com/academy/agent-friendly-apis/anatomy-of-a-skill
- Vercel《We removed 80% of our agent’s tools》  
  https://vercel.com/blog/we-removed-80-percent-of-our-agents-tools
- Aider Repository Map  
  https://aider.chat/docs/repomap.html
- Diataxis  
  https://diataxis.fr/

---

## 15. 下一步建议

如果继续推进，我建议直接基于这份文档做三件落地动作：

1. 产出精简版 `AGENTS.md`
2. 产出精简版 `CLAUDE.md`
3. 搭好 `docs/architecture/` 目录骨架

然后再开始拆 `document` / `draw` / `setup` 三个重 skill。

---

## 16. 代码-文档交叉验证结果

这一节不是“凭印象觉得哪里不对”，而是把代码、CLI、README、AGENTS/CLAUDE、测试文件放在一起核对后的结论。

### 16.1 已经对齐、可以放心保留的部分

这些地方说明项目不是完全靠人工记忆在维持，一部分一致性已经被结构或测试守住了。

- skill 真实目录与多宿主暴露方式是对得上的  
  `.claude/skills/` 是主目录，`.agents/skills`、`.qwen/skills`、根目录 `skills/` 确实都是符号链接
- `AGENTS.md` 和 `CLAUDE.md` 的 skill 清单与磁盘上的 skill 目录是对得上的  
  说明英文主文档这条线目前还比较稳
- `docs/guide/cli-reference.md` 对顶层 CLI 命令覆盖是完整的  
  它不是每个子命令都逐项展开，但至少没有把顶层命令漏掉
- `docs/getting-started/configuration.md` 里关于 `MINERU_TOKEN` / `MINERU_API_KEY` 的说明与 `config.py` 真实行为一致
- 仓库已经有一部分“文档对齐测试”  
  比如 `tests/test_writing_docs_alignment.py` 会检查写作类 skill 是否同时出现在 skill 目录、`AGENTS.md`、`CLAUDE.md`、`AGENTS_CN.md`、README 和 docs index 中
- 宿主 wrapper 的“轻量转发”策略也有测试守着  
  比如 `tests/test_cursor_rules.py` 会检查 Cursor 规则文件足够轻，并且确实把主规则指向 `AGENTS.md`

这组结论说明：ScholarAIO 现在的问题不是“完全没有治理”，而是“治理范围还不够广”。

### 16.2 已确认存在的文档漂移

下面这些不是风格问题，而是已经核实的“代码真相”和“文档描述”不完全一致。

#### 漂移 1：`AGENTS_CN.md` 的 skill 清单没有跟上真实 skill 目录

已确认缺少：

- `backup`
- `ingest-link`

这意味着中文总说明对中文用户的引导已经不完整。

#### 漂移 2：`AGENTS_CN.md` 缺了整条 `proceedings` 数据流

我实际核对后发现，中文版总说明里没有这些关键信息：

- `proceedings.py`
- `ingest/proceedings.py`
- `proceedings` CLI 能力
- `data/inbox-proceedings/`
- `data/proceedings/`

但英文 `AGENTS.md` / `CLAUDE.md` 和代码实现里，这条线是存在的。

这不是小疏漏，而是会直接导致中文使用者不知道项目还有“论文集专用入库流”。

#### 漂移 3：插件模式目录树没有写出 `inbox-proceedings` 和 `proceedings`

`config.py` 的 `ensure_dirs()` 明确会创建：

- `data/inbox-proceedings`
- `data/proceedings`

但 `AGENTS.md`、`CLAUDE.md`、`AGENTS_CN.md` 在插件模式目录树示意里都没把这两个目录写进去。

这属于“局部目录树示意过时”。

#### 漂移 4：README 说“四种 inbox 分类”，但当前真实情况更像“4 个常规 inbox + 1 个 proceedings 专用入口”

`README.md` 和 `README_CN.md` 的 feature 表里写的是“四种 inbox 分类”。

但当前代码和 `docs/guide/ingestion.md` 已经明确支持：

- `data/inbox/`
- `data/inbox-thesis/`
- `data/inbox-patent/`
- `data/inbox-doc/`
- `data/inbox-proceedings/`

这里最准确的说法不是简单改成“五种”，而是要说清楚：

- 常规有 4 类 inbox
- 另外还有 1 条显式手动触发的 proceedings 专用入库流

也就是说，现在的问题主要不是“功能没做”，而是首页文案压缩过头，容易让人误解。

#### 漂移 5：CLI 里的 `toolref fetch` 帮助文案已经落后于真实实现

当前 CLI 帮助把 `toolref fetch` 描述成：

- `git clone -> 提取 -> 索引`

但 `toolref` 真实支持两类来源：

- `git + parser`
- `manifest + discovery`

其中 `openfoam` 和 `bioinformatics` 现在走的就是 `manifest` 路线，不是 `git clone`。

这说明 `toolref` 详细 guide 是新的，但 CLI 帮助文案还是旧心智模型。

### 16.3 为什么这些漂移现在就该处理

因为它们不是“文案不够优雅”，而是会带来真实维护成本：

- 新人看中文文档会少知道一部分能力
- 宿主 agent 读到的长期上下文可能不是最新全貌
- CLI 帮助会给出错误心智模型
- 后面继续加 skill 或新数据流时，重复维护点只会越来越多

### 16.4 这轮交叉验证带来的直接建议

我建议把“修文档”和“补自动守卫”一起做，不要只修文字。

优先级顺序：

1. 先补 `AGENTS_CN.md` 中缺失的 `backup`、`ingest-link`、`proceedings`
2. 同步修正三份 agent 总说明里的插件模式目录树
3. 把 README 的“四种 inbox 分类”改成更准确的说法
4. 把 `toolref fetch` 的 CLI 帮助改成中性描述，不再硬写 `git clone`
5. 新增自动测试，专门检查：
   - 中文总说明是否覆盖全部现有 skill
   - 三份 agent 总说明的目录树是否包含 `inbox-proceedings` / `proceedings`
   - `toolref` 帮助文案是否与 `source_type` 集合一致

---

## 17. 深度拆解附录

为了避免主方案书继续膨胀，我把这一轮“代码-文档交叉验证”的细表单独整理成了附录：

- `workspace/reports/2026-04-16-code-doc-cross-validation.md`

这个附录更适合当整改清单直接用，里面会把：

- 哪些点已对齐
- 哪些点已漂移
- 每个漂移对应的代码依据
- 建议补哪些测试

单独列清楚。

---

## 18. 第 2 到第 10 轮最终收敛说明

按你的要求，我又继续把第 2 到第 10 轮做完了，不在中途停。

这几轮的详细过程、每轮新增证据、被修正的判断、以及最后收敛成什么方案，我单独整理成了一份更适合细看的文档：

- `workspace/reports/2026-04-16-rounds-2-to-10-refinement.md`

这一版不只是“继续补内容”，而是把方案从“总体判断”推进到了“可执行蓝图”。

### 18.1 这 9 轮新增确认的关键事实

- `papers.py` 很小，但承担了非常重要的“唯一路径真相源”角色，这个骨架值得保住
- `loader.py` 虽然不算小，但它的 L1-L4 + notes 设计思路是成熟的，属于应该推广的好模式
- `toolref` 是当前仓库里最像“产品级可维护子系统”的部分：有 façade（门面层）、内部拆分、兼容层、独立 guide、独立 runtime skill
- `cli.py` 现在不是普通意义上的“大文件”，而是同时装了命令注册、参数设计、helper、用户提示、命令实现
- `pipeline.py` 现在也不是普通意义上的“流程文件”，而是已经开始兼做目录扫描器、批处理调度器、状态机、辅助 inbox 分发器、外部导入入口
- 40 个 skill 里，目前没有哪个 skill 真正把详细资料拆到 `references/` / `scripts/` / `assets/`
- `document`、`draw`、`setup` 等大 skill 已经接近“第二份操作手册”
- docs 站当前只有 `getting-started` 和 `guide` 两大类，没有真正的 `architecture/` 解释层
- 英文主说明比中文主说明更完整，说明现在的同步机制还没有把中英文放在同一治理级别

### 18.2 这 9 轮最终把方案收敛成了什么

现在我对 ScholarAIO 的最终判断更明确了：

1. 不要重写，要做“保外壳、换内脏”的重构
2. 先收敛接口和文档，再继续猛加功能
3. 先把 `cli.py` / `pipeline.py` / 大 skill / agent 总说明四个入口治理掉
4. 文档治理不能只靠人工同步，必须补自动校验
5. 后续所有新能力都要遵守“代码 + 测试 + 人类文档 + agent surface”一起交付

### 18.3 现在最值得立刻执行的动作顺序

如果按真实落地价值排序，我现在建议顺序再收紧成下面 6 步：

1. 先修事实漂移：`AGENTS_CN.md`、README、`toolref fetch` help
2. 再瘦 `AGENTS.md` / `CLAUDE.md`
3. 再建 `docs/architecture/`
4. 再重写 `document` / `draw` / `setup` 三个重 skill
5. 再拆 `cli.py`
6. 最后拆 `pipeline.py`

原因很简单：

- 如果事实都没对齐，先谈“优雅重写文档”收益不高
- 如果 agent 常驻入口还很胖，skill 体系再怎么改也会继续重复
- 如果 `cli.py` / `pipeline.py` 先一起大拆，风险会明显上升
