# ScholarAIO 代码-文档交叉验证附录

> 内部开发文档。用于仓库内的重构与治理规划，不接入公开文档导航，也不纳入公开站点展示。

日期：2026-04-16

用途：给主方案书做证据补充，专门回答“代码实现”和“文档描述”到底哪里一致、哪里已经漂移。

---

## 1. 这份附录怎么做的

我没有只看文档，也没有只看代码，而是按下面几条线交叉核对：

1. 看磁盘上的真实 skill / 目录 / 文件
2. 看 `scholaraio/cli.py` 的命令注册和 help 文案
3. 看 `config.py` 的真实目录创建逻辑和配置解析逻辑
4. 看 `README.md`、`README_CN.md`、`AGENTS.md`、`CLAUDE.md`、`AGENTS_CN.md`
5. 看已有测试到底在自动守什么，哪些还没人守

一句大白话：

这份附录不是“我觉得”，而是“代码里确实这样写，文档里确实那样写”。

---

## 2. 已确认对齐的部分

这些部分说明 ScholarAIO 不是纯手工维护，已经有一部分一致性机制。

### 2.1 skill 真实目录和多宿主暴露方式一致

实际存在：

- `.claude/skills/`
- `.agents/skills -> ../.claude/skills`
- `.qwen/skills -> ../.claude/skills`
- `skills -> .claude/skills`

这和 `AGENTS.md` / `CLAUDE.md` 的描述一致。

结论：

- 这一块的“发现路径”是可信的
- 不是文档随便写了几个路径

### 2.2 `AGENTS.md` / `CLAUDE.md` 的 skill 清单与磁盘一致

我按磁盘上的 `.claude/skills/*` 目录逐个核对，英文两份主说明都没有漏 skill。

结论：

- 英文主说明这条线当前是完整的
- 问题主要出在中文同步没有完全跟上

### 2.3 CLI reference 对顶层命令覆盖完整

我把 `scholaraio/cli.py` 里注册的顶层命令和 `docs/guide/cli-reference.md` 做了比对。

结论：

- 顶层命令没有漏掉
- 但子命令不是逐项展开的

这意味着：

- 作为“总览页”，它是合格的
- 但如果以后子命令继续增多，单靠手写总览还是容易慢慢失真

### 2.4 MinerU token 文档和真实配置逻辑一致

`docs/getting-started/configuration.md` 说明：

- `MINERU_TOKEN` 优先
- `MINERU_API_KEY` 是兼容旧名字

`config.py` 的真实查找顺序也确实是：

1. 配置文件里的 `ingest.mineru_api_key`
2. 环境变量 `MINERU_TOKEN`
3. 环境变量 `MINERU_API_KEY`

结论：

- 这一块文档是可靠的

### 2.5 已有一部分“文档对齐测试”

已经存在的自动守卫包括：

- `tests/test_writing_docs_alignment.py`
  - 会检查 `academic-writing`、`poster`、`technical-report` 是否同时出现在 skill 目录、AGENTS、CLAUDE、AGENTS_CN、README、docs index 中
- `tests/test_cursor_rules.py`
  - 会检查 Cursor wrapper 是否仍然保持轻量，并且确实把规则导向 `AGENTS.md`

结论：

- 仓库已经有“多表面同步”的意识
- 但当前覆盖范围偏窄，主要集中在写作 stack 和 wrapper

---

## 3. 已确认漂移的部分

这一节只写已经核实的，不写模糊怀疑。

### 3.1 `AGENTS_CN.md` 漏了两个真实存在的 skill

磁盘中存在、英文说明中也存在，但 `AGENTS_CN.md` 没写的有：

- `backup`
- `ingest-link`

这说明：

- 中文主说明已经不是“完整镜像”
- 以后如果继续靠手工复制，缺口还会继续增大

影响：

- 中文用户会直接少知道两项能力
- 这类遗漏如果出现在 agent 长期上下文里，会影响路由判断

优先级：

- 高

### 3.2 `AGENTS_CN.md` 没同步 proceedings 专用数据流

我用关键词核对了 `AGENTS_CN.md`，确认缺失：

- `proceedings.py`
- `ingest/proceedings.py`
- `proceedings`
- `data/inbox-proceedings/`
- `data/proceedings/`

但这些内容在英文 `AGENTS.md` / `CLAUDE.md` 里存在，在代码里也存在。

这不是一个词条没补，而是一整条功能线没同步。

影响：

- 中文用户基本不知道还有论文集专用 ingest 流程
- 会误以为所有论文集都该走普通 inbox

优先级：

- 很高

### 3.3 三份 agent 总说明的插件模式目录树都少了 proceedings 相关目录

`config.py` 的 `ensure_dirs()` 真实会创建：

- `data/inbox-proceedings`
- `data/proceedings`

但 `AGENTS.md`、`CLAUDE.md`、`AGENTS_CN.md` 的插件模式目录树示意里都没有把它们列出来。

这说明：

- 目录树示意不是代码驱动生成的
- 所以很容易在新增目录时漏同步

影响：

- 读文档的人会以为插件模式下没有 proceedings 数据目录
- 目录结构心智模型会被带偏

优先级：

- 中高

### 3.4 README 的“四种 inbox 分类”说法已经不够准确

`README.md` 和 `README_CN.md` 在 feature 表里都写“四种 inbox 分类”。

但真实实现里，用户可用的入口其实是：

- `data/inbox/`
- `data/inbox-thesis/`
- `data/inbox-patent/`
- `data/inbox-doc/`
- `data/inbox-proceedings/`

这里最准确的表述应该是：

- 4 个常规 inbox
- 外加 1 条专门给 proceedings 的显式入口

不是简单粗暴地把“四种”改成“五种”就完了，因为 proceedings 的语义和前四类并不完全同级。

影响：

- 首页读者会形成偏差心智模型
- 看 README 和看 ingestion guide 时会有“怎么一个说四个，一个说五个”的疑惑

优先级：

- 中

### 3.5 `toolref fetch` 的 CLI help 已经过时

CLI 里当前写法是：

- `拉取工具文档（git clone -> 提取 -> 索引）`

但 `toolref` 当前实际支持两种来源：

- `git + parser`
- `manifest + discovery`

其中这两个工具本来就不是 `git clone` 路线：

- `openfoam`
- `bioinformatics`

更有意思的是，`docs/guide/toolref-onboarding.md` 已经把这两种模式讲清楚了，说明这里不是“整体文档不懂新架构”，而是“CLI 帮助文案没更新”。

影响：

- 用户会误解 `toolref fetch` 的工作方式
- 后面继续新增 manifest 型工具时，这个帮助文案会越来越假

优先级：

- 中高

---

## 4. 当前自动守卫覆盖了什么，没覆盖什么

### 4.1 已覆盖

- 新写作 skill 是否同步到多份文档
- Cursor wrapper 是否仍然是轻量转发

### 4.2 未覆盖

- 中文总说明是否覆盖全部现有 skill
- proceedings 这条数据流是否在三份 agent 总说明里都出现
- 插件模式目录树是否与 `ensure_dirs()` 一致
- README 的 inbox 说法是否和 ingest guide / 代码一致
- CLI help 是否与内部 source type 设计一致

一句大白话：

现在的测试像是在“看几根主梁”，但还没有开始检查“新加出来的房间门牌对不对”。

---

## 5. 建议新增的自动测试

这一部分很重要。否则修完一次文档，过几周还会再漂。

### 5.1 skill 全量清单测试

建议新增：

- 遍历 `.claude/skills/*`
- 校验 `AGENTS.md`、`CLAUDE.md`、`AGENTS_CN.md` 至少都包含对应 skill 名

目的：

- 防止以后再出现 `backup`、`ingest-link` 这种“磁盘有，中文总说明没有”的情况

### 5.2 proceedings 数据流文档测试

建议新增：

- `AGENTS.md`
- `CLAUDE.md`
- `AGENTS_CN.md`

都要包含：

- `proceedings`
- `data/inbox-proceedings/`

目的：

- 防止中文或插件说明再次把整条流程漏掉

### 5.3 目录树与 `ensure_dirs()` 一致性测试

建议不要再手工目测。

更好的方式是：

- 从 `config.py` 里抽出“标准目录集合”
- 用它去比对文档中的目录树片段

哪怕一开始做不到完全自动比对，也至少可以用一个 token 列表来检查：

- `inbox-proceedings`
- `proceedings`
- `inbox-thesis`
- `inbox-patent`
- `inbox-doc`

### 5.4 `toolref` help 文案测试

建议新增一个很小的测试：

- 读取 `scholaraio/cli.py`
- 如果 `TOOL_REGISTRY` 里存在 `manifest` 类型工具，就不要允许 `toolref fetch` 的 help 只写 `git clone`

目的：

- 防止 CLI 帮助继续固化旧心智模型

---

## 6. 该怎么改，才不会越改越乱

我的建议不是“把所有文档全重写一遍”，而是分层修。

### 第一层：先修事实错误和事实缺失

先改这些：

- `AGENTS_CN.md` 补 `backup`、`ingest-link`
- `AGENTS_CN.md` 补 proceedings 全链路
- 三份 agent 总说明的插件目录树补 `inbox-proceedings`、`proceedings`
- README / README_CN 重写“四种 inbox 分类”的表述
- `toolref fetch` 的 help 改成中性表述

### 第二层：再补自动守卫

否则第一层修完后还会反复漂。

### 第三层：最后再谈“文档瘦身”和“结构重写”

因为如果事实都还没对齐，先谈写作风格和结构美感，收益没有那么大。

---

## 7. 这轮交叉验证最重要的结论

最关键的不是“发现了几处错”，而是发现了当前 ScholarAIO 文档治理的真实状态：

1. 英文主说明比中文主说明更新得更及时
2. 写作 stack 的同步机制已经比较成熟
3. proceedings 和一部分系统能力还没有被纳入同等级别的自动守卫
4. 当前最危险的不是代码乱，而是“新增能力以后，文档同步还在靠人工记忆”

所以后续方案里，文档治理不能只写“精简 AGENTS / CLAUDE”，还必须加一句更硬的话：

- 以后任何新增 skill、新数据流、新目录，都要同时补“代码 + 文档 + 自动校验”

否则项目代码会越来越强，说明却越来越不可信。
