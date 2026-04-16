---
name: academic-writing
description: Use when the user needs help choosing or organizing the right academic-writing workflow by deliverable, writing stage, or final document type such as review article, guided single-paper reading, paper section, rebuttal, PPT, poster, or technical report.
version: 1.0.0
author: ZimoLiao/scholaraio
license: MIT
tags: ["academic", "writing", "router", "workflow", "report"]
---
# Academic Writing Router

Route academic-writing requests to the right specialized skill with minimal overlap.

## Purpose

This skill is the **entry point** for users who know what they want to produce, but do not know which writing workflow to use.

Do not duplicate the full instructions of the downstream skills. Your job is to:
- identify the target deliverable
- identify the current writing stage
- select the right specialized skill or skill combination
- explain the route briefly, then continue with that workflow

## Route By Deliverable

| User wants | Route |
|------------|-------|
| 文献综述 / survey / review article | `/literature-review` |
| 单篇论文引导式精读 / guided deep reading of one paper | `/paper-guided-reading` |
| 论文具体章节（Introduction / Method / Results / Discussion / Conclusion） | `/paper-writing` |
| 审稿回复 / rebuttal / response letter | `/review-response` |
| 研究空白分析 / 选题调研 | `/research-gap` |
| 语言润色 / 去 AI 味 / 风格迁移 | `/writing-polish` |
| 引用真实性检查 | `/citation-check` |
| 正式 Word 报告 | 写作 skill + `/document` |
| 汇报 PPT / 答辩幻灯片 | 写作 skill + `/document` |
| 海报内容包 | `/poster` |
| 专题/技术调研报告 | `/technical-report` |

## Route By Writing Stage

| Stage | Route |
|-------|-------|
| 还没确定应该用哪个 skill | 留在本 skill，先做任务分流 |
| 需要先锁定并深读一篇论文 | `/paper-guided-reading` |
| 已有论文集合，需要组织叙述 | `/literature-review` |
| 已有研究内容，需要写论文段落 | `/paper-writing` |
| 已收到审稿意见 | `/review-response` |
| 还在找空白和方向 | `/research-gap` |
| 只需要修语言 | `/writing-polish` |
| 快交稿了，要核验引用 | `/citation-check` |
| 需要交付 DOCX / PPTX | `/document` |

## Deliverable Guidance

### PPT / Beamer

- 当前一等支持的演示文稿交付是 `PPTX`，通过 `/document` 生成和检查。
- 如果用户明确说 `beamer`，先按“演示文稿内容工作流”组织结构、标题、每页要点、图表需求。
- 除非用户明确要求 LaTeX 模板实现，否则默认优先走 `PPTX`，不要假设仓库已经有 beamer 专用后端。

### Poster

- 海报任务优先交给 `/poster`，由它负责 poster 专属的版块和文本密度控制。
- `/poster` 会继续组合 `/literature-review`、`/paper-writing`、`/research-gap`、`/draw`、`/document`。

### Technical Report / Special-Topic Report

- 这类任务优先交给 `/technical-report`，由它负责 audience、结构和建议层组织。
- `/technical-report` 会继续组合 `/literature-review`、`/research-gap`、`/paper-writing`、`/document`。

## Workflow

1. 明确用户最终要交付什么。
2. 判断用户现在处于哪个阶段：选题、搜集、起草、润色、回复、排版交付。
3. 选择一个主 skill；只有在确有必要时才组合多个 skill。
4. 用一句话告诉用户接下来走哪条路线。
5. 转入下游 skill 的工作流，避免在本 skill 中重复实现它们。

## Principles

- **路由优先**：本 skill 负责分流，不负责取代其他写作 skill。
- **最小组合**：能用一个 skill 解决时，不要堆多个。
- **交付物导向**：按用户最终产物组织流程，而不是按内部模块名组织。
- **诚实表达能力边界**：当前一等文档交付是 `DOCX/PPTX/XLSX`；对 `beamer/poster` 用“工作流支持”表述，不要伪装成已有独立后端。

## Examples

用户说："我想做一个给导师汇报的 PPT，但还没想好结构"
→ 先用本 skill 路由到 “汇报 PPT” 工作流，再转 `/document`，必要时补 `/research-gap` 或 `/literature-review`

用户说："帮我写一个技术调研报告"
→ 先判断是偏综述还是偏研究空白分析，然后转 `/literature-review` 或 `/research-gap`，最后如需正式文件再接 `/document`

用户说："我想先找一篇最相关的论文，然后带着我精读"
→ 先路由到 `/paper-guided-reading`

用户说："我想写 beamer"
→ 先确认是否真的需要 LaTeX beamer；若不是硬要求，默认走演示内容 + `PPTX` 工作流
