# ScholarAIO 第 2 到第 10 轮收敛、核对与最终蓝图

> 内部开发文档。用于仓库内的重构与治理规划，不接入公开文档导航，也不纳入公开站点展示。

日期：2026-04-16

用途：这是在主方案书基础上继续推进的“深拆迭代稿”。它回答的不是“要不要重构”，而是：

- 为什么这样重构
- 先动哪里，后动哪里
- 哪些判断是反复核对后保留下来的
- 哪些地方我在后几轮里修正了前几轮的看法

---

## 0. 先说这份文档和主方案书的关系

主方案书负责：

- 给出总体判断
- 给出大方向
- 给出最终建议

这份文档负责：

- 展开第 2 到第 10 轮到底是怎么一步步收敛的
- 把“为什么这么定”讲得更透
- 把后续真正可执行的改造蓝图写清楚

如果用大白话说：

- 主方案书像“董事会汇报版”
- 这份文档像“项目总设计版”

---

## 1. 第 2 轮：先确认哪些骨架必须保住

### 1.1 这一轮重点看什么

我先不急着批评大文件，而是先确认：

- 这个项目里到底有没有已经成熟的“好骨架”
- 后面重构时，哪些东西应该视为“不可轻易打断的主梁”

### 1.2 这轮核到的关键事实

#### `papers.py` 很小，但位置非常关键

它不是大模块，却扮演了“唯一路径真相源”的角色。

大白话解释：

- 所有模块如果都自己拼 `data/papers/<dir>/meta.json`
- 迟早会有人拼歪
- `papers.py` 的价值就在于把这件事收口

这类模块最值钱的地方，不是代码量，而是“统一口径”。

#### `loader.py` 的 L1-L4 设计是很成熟的

`loader.py` 一眼看过去不算小，但它的思路是非常对的：

- L1：只看元数据
- L2：看摘要
- L3：看结论
- L4：看全文

这套分层不仅适合论文阅读，也特别适合 agent。

因为 agent 最怕的一件事就是：

- 还没搞清问题，就一上来把整篇全文塞进上下文

ScholarAIO 这里已经做对了。

#### notes 机制是“跨会话记忆”的雏形

`loader.py` 里的 `notes.md` 追加与读取逻辑，配合 `show --append-notes`，本质上已经是在做一种轻量但很有用的“论文级持久记忆”。

这条线很值得继续强化。

#### `toolref` 是当前仓库里最成熟的“子系统样板”

`toolref` 这块最值得学的，不是功能本身，而是它的结构意识：

- 对外有稳定入口
- 对内已经做了拆包
- 还保留了兼容层
- 有独立 guide
- 有独立 runtime skill
- 还有 onboarding 路线

一句话总结：

如果要问 ScholarAIO 现在最像“产品级 agent 基建”的是哪一块，答案不是 CLI，不是 ingest，而是 `toolref`。

### 1.3 这一轮收敛结论

后面重构不能把这些成熟骨架一起打碎。

优先保留的“主梁”是：

- `papers.py` 的单一事实来源
- `loader.py` 的分层加载思想
- `notes.md` 的持久笔记机制
- `toolref` 的公开门面 + 内部实现拆分模式

---

## 2. 第 3 轮：确认 `cli.py` 到底是“大”，还是“已经职责混装”

### 2.1 这一轮重点看什么

很多项目都说“这个文件太大了”，但真正要拆时经常说不清到底为什么。

所以这一轮我重点不是数行数，而是看：

- `cli.py` 里到底混了几层责任
- 如果拆，最安全的切口在哪

### 2.2 这轮核到的关键事实

`scholaraio/cli.py` 当前情况：

- 4129 行
- 77 个 `def`
- 40 个 `cmd_*` 命令函数

它里面同时装了这些事情：

- 顶层 CLI 说明文案
- 参数 helper
- dependency check
- 40 个命令实现
- 所有 parser 注册
- `main()` 启动逻辑
- 一些用户提示和兼容处理

大白话解释：

这已经不是“一个入口文件”，而是“一个入口总包，只是还没拆成目录”。

### 2.3 为什么这很危险

不是因为“看着难受”，而是会出现这些后果：

- 改某个命令的 parser，容易碰到别的命令
- 命令帮助文案和实现混在一个文件里，久了很难保持同步
- 新人不敢动
- 如果以后要做 API / MCP / Web 层复用，很多逻辑会卡在 CLI 里面拿不出来

### 2.4 这轮修正了一个判断

我前面已经知道 `cli.py` 必拆，但这一轮之后，我更明确了一点：

不能按“功能模块”直接硬拆，否则风险太高。

更稳的拆法是按责任拆：

1. 先拆 parser 注册
2. 再拆 command handlers
3. 最后才考虑把通用逻辑继续下沉到业务层

### 2.5 这一轮收敛结论

`cli.py` 的第一阶段目标不是“变优雅”，而是：

- 让命令定义和命令实现先分开
- 让用户可见行为保持完全不变

也就是说：

- 先拆文件
- 不先改命令名
- 不先改用户习惯

---

## 3. 第 4 轮：确认 `pipeline.py` 的问题本质不是“流程长”，而是“责任太杂”

### 3.1 这一轮重点看什么

我要确认的不是 pipeline 长不长，而是：

- 它是不是只是一个大 orchestrator（调度器）
- 还是已经把太多层都卷进来了

### 3.2 这轮核到的关键事实

`scholaraio/ingest/pipeline.py` 当前情况：

- 2622 行
- 42 个 `def`
- 3 个类 / 数据结构

关键函数包括：

- `_process_inbox`
- `run_pipeline`
- `import_external`
- `batch_convert_pdfs`
- `_collect_existing_ids`

它当前同时承担了：

- inbox 扫描
- 云端批量预处理
- 单文件 step 执行
- thesis / patent / document / proceedings 分流
- papers scope 并发执行
- global scope 收尾
- 外部导入流程复用
- 批量补转换

这说明：

它已经不只是“流水线定义文件”，而是在兼任半个子系统总控。

### 3.3 为什么这件事必须马上纳入治理

如果继续在这里加分支，后面最容易发生两件事：

1. 同一个新需求要改三四个位置
2. 没人能快速讲清“某一步到底属于哪一层”

这就是屎山最典型的早期信号：

- 不是代码不能跑
- 而是责任边界慢慢被吃掉

### 3.4 这一轮修正了一个判断

我之前觉得 pipeline 最大问题是“太长 + 分支多”。

但这一轮更准确的说法应该是：

它现在最危险的地方，是把“状态机、扫描器、流程编排器、导入入口、批量处理器”几种身份装进了一个文件。

### 3.5 这一轮收敛结论

`pipeline.py` 后面建议拆成 4 层：

1. `context.py`
   - 放 `InboxCtx`、StepResult、StepDef 这类上下文和公共结构
2. `steps/`
   - 放每个 step 的真实实现
3. `runner.py`
   - 放 `run_pipeline()`、scope 编排、并发逻辑
4. `sources.py` 或 `external.py`
   - 放 `import_external()`、`batch_convert_pdfs()` 这类复用入口

原则只有一个：

- 先把“谁负责什么”说清
- 不急着换流程协议

---

## 4. 第 5 轮：确认 skill 体系的问题不只是“长”，而是“工作流和手册没分开”

### 4.1 这一轮重点看什么

我这一轮专门查了几类 skill：

- `document`
- `draw`
- `setup`
- `scientific-runtime`
- `academic-writing`
- `technical-report`

### 4.2 这轮核到的关键事实

当前 skill 总数：

- 40 个

其中比较长的几个：

- `document`：464 行
- `scientific-tool-onboarding`：314 行
- `draw`：273 行
- `bioinformatics`：250 行
- `export`：236 行
- `scrub`：227 行

更关键的一点：

- 当前 skill 目录里，基本没有 `references/`
- 也几乎没有 `scripts/`
- 也没有 `assets/`

也就是说：

现在很多 skill 的详细内容，还是直接堆在 `SKILL.md` 本体里。

### 4.3 哪些 skill 是“好样板”

我反复看下来，比较像“好样板”的反而是这些：

- `scientific-runtime`
- `technical-report`
- `academic-writing`

它们的共同特点是：

- 先定义什么时候用
- 再定义流程
- 不试图变成完整工具手册

### 4.4 哪些 skill 已经开始变形，哪些又不能粗暴瘦身

最典型的“说明书化”其实是：

- `document`
- `draw`

这几个已经越来越像：

- API 手册
- 操作大全
- 大块知识说明

这样写短期很方便，因为所有信息都在一处。

但长期会出问题：

- 主 skill 变重
- agent 每次都得读大块内容
- 更新细节时更容易改漏

但 `setup` 这里要单独说：

- 它确实也长
- 但它和 `document` / `draw` 不是同一类问题

`setup` 里很大一块内容不是“长参考资料”，而是：

- 核心配置 vs 附加配置的顺序
- MinerU / Docling 的推荐逻辑
- 检测结果应该怎样向用户转述
- 初次上手时哪些收费 / 免费边界必须说明

这些内容本质上是 onboarding 策略，不只是说明文字。

### 4.5 这一轮收敛结论

后面 skill 要分两种方式治理。

第一种：reference-heavy skill，改成“三层结构”

1. `SKILL.md`
   - 只放触发条件、主流程、关键边界、稳定入口
2. `references/`
   - 放 API 细表、长示例、参数说明
3. `scripts/` / `assets/`
   - 放可复用脚本、模板和素材

这条最适合：

- `document`
- `draw`
- `scientific-tool-onboarding`
- `bioinformatics`

第二种：strategy-heavy skill，保住主策略，再拆附录。

这条最典型的是：

- `setup`

对它来说，应该外置的是：

- 部署附录
- 长命令样例
- 高级字段对照表

不该外置的是：

- 关键推荐逻辑
- 用户沟通模板
- 初次上手顺序

一句大白话：

skill 主文件通常应该像“作战步骤卡”，但像 `setup` 这样的策略型 skill，仍然需要保留关键判断。

---

## 5. 第 6 轮：确认 agent 文档体系真正的问题是“信息层次混了”

### 5.1 这一轮重点看什么

这一轮我主要重新对照：

- `AGENTS.md`
- `CLAUDE.md`
- `AGENTS_CN.md`
- wrapper 文件

我想确认的问题是：

- 现在到底是文档太长
- 还是本该分层的信息混写了

### 5.2 这轮核到的关键事实

`AGENTS.md` / `CLAUDE.md`：

- 各 531 行
- 相似度 99.43%

`.qwen/QWEN.md`：

- 明显更薄
- 已经更像宿主特定的桥接文件

wrapper 文件反而都挺轻：

- `.cursor/rules/scholaraio.mdc`
- `.clinerules`
- `.windsurfrules`
- `.github/copilot-instructions.md`

而且 wrapper 轻量化这件事，还有测试守着。

这说明现在的真正问题不是“所有入口都太重”，而是：

- `AGENTS.md` / `CLAUDE.md` 太重
- `.qwen/QWEN.md` 和 wrapper 反而更接近目标形态

### 5.3 这一轮修正了一个判断

我前面会下意识觉得“多 agent 适配很容易造成全面混乱”。

但这一轮之后更准确的判断是：

- 多宿主适配这条路本身没错
- 错的是把过多技术内容都压进了 AGENTS / CLAUDE

所以后面不是减少宿主适配，而是减少重复承载。

### 5.4 这一轮收敛结论

后面文档层次应该改成：

1. `README` / `docs`
   - 给人看的
2. `AGENTS.md` / `CLAUDE.md`
   - 给 agent 常驻加载的“薄目录 + 必要契约”
3. `.qwen/QWEN.md`
   - 更薄的宿主特定桥接文件
4. wrapper
   - 只做轻量转发和宿主说明

其中 `AGENTS.md` / `CLAUDE.md` 应该只保留：

- 项目定位
- 硬规则
- 稳定入口
- T1/T2/T3 + notes 契约
- 关键数据目录语义
- 详细文档去哪看

而不是继续承担百科全书角色，也不是缩成空目录页。

---

## 6. 第 7 轮：确认“代码-文档一致性”现在还没有进入强治理状态

### 6.1 这一轮重点看什么

这一轮不是继续看风格，而是看事实：

- 代码和文档到底哪里已经统一
- 哪里还靠人工同步

### 6.2 这轮新增确认的事实

已经对得上的：

- 英文 skill 清单和磁盘一致
- CLI reference 顶层命令没漏
- MinerU token 说明和 `config.py` 一致
- 写作 stack 有专门的多表面对齐测试

已经确认漂移的：

- `AGENTS_CN.md` 漏了 `backup`
- `AGENTS_CN.md` 漏了 `ingest-link`
- `AGENTS_CN.md` 漏了整条 proceedings 流程
- 三份 agent 总说明的插件目录树都没写 `inbox-proceedings` / `proceedings`
- README 还写“四种 inbox 分类”，但真实情况更像“4 个常规 inbox + 1 条 proceedings 专用入口”
- `toolref fetch` CLI help 还在写 `git clone`，但实现已经支持 `manifest + discovery`

### 6.3 这一轮收敛结论

文档治理后面必须补到“规则化”。

我建议以后新增任何 skill / 数据流 / 目录时，都要同时满足：

1. 代码已落地
2. 文档已更新
3. 自动校验已补上

否则就不算完整交付。

---

## 7. 第 8 轮：确认 docs 站现在缺的不是“更多页面”，而是“解释层”

### 7.1 这一轮重点看什么

我重新看了 `docs/` 目录结构，想确认：

- 是不是文档量不够
- 还是分类方式不对

### 7.2 这轮核到的关键事实

当前 docs 主要是：

- `getting-started/`
- `guide/`
- `api/`

但没有真正的：

- `architecture/`

这意味着现在文档站主要覆盖了两类东西：

- 怎么开始
- 怎么操作

却没有系统覆盖：

- 为什么结构是这样
- 模块边界怎么理解
- 数据目录契约是什么
- agent 文档、skill、wrapper 各自负责什么

### 7.3 为什么这会导致 README / AGENTS / guide 重复

因为没有“解释层”的时候，任何需要解释架构的地方都会自己写一段：

- README 写一点
- AGENTS 写一点
- CLAUDE 写一点
- guide 再写一点

这就是现在重复的源头之一。

### 7.4 这一轮收敛结论

docs 后面要补一个明确的 `architecture/`：

- `overview.md`
- `data-model.md`
- `agent-surfaces.md`
- `ingest-pipeline.md`
- `search-and-index.md`
- `skill-system.md`
- `toolref-architecture.md`

这样可以把“为什么这样设计”集中收口。

---

## 8. 第 9 轮：把“怎么做”从建议清单收敛成执行蓝图

### 8.1 这一轮重点看什么

前几轮已经能判断方向了，但还缺一件事：

- 到底按什么顺序做，风险最小

### 8.2 这轮最终排出来的顺序

我现在最认可的顺序是：

#### 第一阶段：事实对齐期

先改：

- `AGENTS_CN.md`
- README / README_CN
- `toolref fetch` help
- 插件模式目录树

目的：

- 先把“说的不对”改对

#### 第二阶段：入口瘦身、必要契约与最小守卫补齐期

再改：

- `AGENTS.md`
- `CLAUDE.md`
- `.qwen/QWEN.md`
- `docs/architecture/`
- `docs/reference/`
- 最小黄金路径回放测试

目的：

- 先让常驻入口瘦下来，同时把必要契约留下，再把“为什么这样设计”集中收口

#### 第三阶段：skill 与代码结构治理期

再做：

- `document` / `draw`
- `setup`（保核心策略、拆附录）
- `cli.py` 拆分
- `pipeline.py` 拆分

目的：

- 让重 skill、CLI 和 ingest 结构同时变清楚

#### 第四阶段：守规矩期

最后补：

- 一致性测试
- 扩展真实任务回放评测
- 文件体积预警

目的：

- 防止项目回弹

### 8.3 这一轮收敛结论

ScholarAIO 当前不需要“革命式重构”，需要的是“分期治理”。

大白话说：

- 先把门牌贴对
- 再把大厅收拾干净
- 再拆内部隔断
- 最后立规矩防止重新堆乱

---

## 9. 第 10 轮：最后把“目标状态”说清楚，避免越改越偏

### 9.1 这一轮重点看什么

重构最怕的一件事就是：

- 大家都知道现在不理想
- 但不知道最后到底要变成什么样

所以这一轮我把“目标状态”明确定义出来。

### 9.2 我建议的目标状态

#### 目标一：对用户来说，入口不变

用户继续用：

- `scholaraio <command>`
- 现有 skill 名
- 现有数据目录习惯

不要在第一阶段大量改外部名字。

#### 目标二：对维护者来说，责任清楚

应该能快速回答这些问题：

- 命令注册在哪
- 命令实现在哪
- ingest 步骤在哪
- pipeline 调度在哪
- 架构解释文档在哪
- agent 常驻规则在哪
- skill 长资料在哪

如果这些问题还得靠“熟人记忆”，那就说明治理还没完成。

#### 目标三：对 agent 来说，上下文更轻、更准

理想状态是：

- `AGENTS.md` / `CLAUDE.md` 明显变薄，但必要契约还在
- `.qwen/QWEN.md` 继续保持更薄的宿主桥接定位
- skill 主文件明显变短
- 长资料按需加载
- wrapper 继续保持很轻

#### 目标四：对项目长期演化来说，新增能力不再靠人工全库同步

后面新增一项能力时，应该有固定交付清单：

1. 代码
2. 测试
3. 人类文档
4. agent surface

### 9.3 反目标：什么不该做

为了避免重构走偏，我也明确列几个“不该做”：

- 不要先推倒重写 CLI
- 不要先重构所有 skill
- 不要一上来做抽象大一统
- 不要为了“优雅”改一堆命令名
- 不要让文档重写先于事实对齐

### 9.4 这一轮最终收敛结论

ScholarAIO 最适合的路径不是：

- 功能停摆半年，搞一次大重写

而是：

- 保住外壳
- 清理入口
- 逐层拆分
- 用测试把治理成果钉住

---

## 10. 最终版升级蓝图

这一节是第 2 到第 10 轮全部收敛后的“执行版结论”。

### 10.1 总原则

1. 先治理，再扩张
2. 先事实对齐，再谈文档美化
3. 先拆责任，不先改外部接口
4. 一切新增能力都必须带自动守卫

### 10.2 代码侧优先级

#### 优先级 A：必须尽快治理

- `scholaraio/cli.py`
- `scholaraio/ingest/pipeline.py`
- `document` / `draw` 这类 reference-heavy 大 skill
- `setup`（但只做保守分层，不拆核心策略）
- `AGENTS.md` / `CLAUDE.md` / `.qwen/QWEN.md`

#### 优先级 B：要保住、可当样板

- `scholaraio/papers.py`
- `scholaraio/loader.py`
- `scholaraio/toolref/*`

#### 优先级 C：先不大动

- 搜索、workspace、citation graph 这类已经相对清楚的能力层

### 10.3 文档改写蓝图

建议目标结构：

```text
README.md / README_CN.md
  只做产品介绍、快速开始、能力总览、入口链接

docs/
  getting-started/
  guide/
  architecture/
    overview.md
    data-model.md
    agent-surfaces.md
    ingest-pipeline.md
    search-and-index.md
    skill-system.md
    toolref-architecture.md
  reference/
    cli.md
    skills.md

AGENTS.md / CLAUDE.md
  薄目录 + 必要契约

.qwen/QWEN.md
  更薄的宿主特定桥接文件
```

### 10.4 skill 改写蓝图

统一模板建议：

```text
---
name:
description:
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

## 稳定入口
- CLI:
- Python:

## 详细资料
- references/...
- scripts/...
```

补一句很关键的边界：

- 对 `document` / `draw` 这类 reference-heavy skill，尽量按这个模板收口
- 对 `setup` 这类 strategy-heavy skill，`关键边界` 必须继续保留推荐逻辑和用户沟通规则

### 10.5 自动守卫蓝图

后面建议最少补这 5 类测试：

1. 全量 skill 清单同步测试
2. proceedings 数据流文档覆盖测试
3. 插件目录树与 `ensure_dirs()` 一致性测试
4. `toolref` 帮助文案与 source type 一致性测试
5. 最小黄金路径回放测试（前置到 `cli.py` / `pipeline.py` 拆分前）
6. 扩展真实用户任务回放评测

---

## 11. 最后一句话

这 9 轮做完以后，我的判断比最开始更坚定了：

ScholarAIO 现在最需要的不是“再多长几个能力”，而是“把已经长出来的能力收进一个长期能维护的框架里”。

如果现在做这一步，后面项目会越来越稳。

如果现在不做，后面每加一个新能力，复杂度都会以更快的速度上涨。
