---
name: document
description: Use when the user wants to create or inspect DOCX, PPTX, or XLSX files, generate a downloadable Office deliverable, or verify its structure and layout warnings with scholaraio document inspect.
---

# Office 文档生成与检查

## Capability Routing

**当前 Agent 原生能力优先，但必须先做能力检查**：按最终交付物路由，不按 Agent 品牌路由。若当前会话实际提供内容写作、演示设计、图表或版式能力，就由当前使用的 Agent 原生能力先完成内容与视觉方案。只有用户需要可下载、可复现的 `DOCX/PPTX/XLSX` 文件时，才使用本 skill 的 Office API 和检查闭环。

## Output Contract

| 用户要的产物 | 默认实现 | 必做检查 |
|---|---|---|
| 正式报告、综述、简报 | `python-docx` → DOCX | 标题层级、段落、表格、图片、样式 |
| 汇报、演示、答辩 | `python-pptx` → PPTX | 页数、shape 边界、文字溢出警告、图片、表格 |
| 数据表、统计、清单 | `openpyxl` → XLSX | sheet、数据范围、冻结窗格、格式、图表 |

把用户交付物写到 `workspace/` 下；正式文件默认放 `workspace/reports/`，系统生成图表默认放 `workspace/_system/figures/`。不要把产物写到仓库根目录。

## Workflow

1. 明确最终格式、受众、语言、模板、页数或篇幅，以及是否需要可编辑源文件。
2. 使用当前会话实际可用的原生能力完成内容、故事线和视觉方案；需要文献数据时再组合 ScholarAIO 的检索或写作 skill。
3. 只读取与目标格式对应的实现参考：
   - DOCX：读取 [references/docx.md](references/docx.md)
   - PPTX：读取 [references/pptx.md](references/pptx.md)
   - XLSX：读取 [references/xlsx.md](references/xlsx.md)
4. 用一个可重复运行的 Python 脚本生成文件。脚本与产物都放在对应 workspace 中，避免散落临时代码。
5. 运行 `scholaraio document inspect <file>`；发现结构问题或溢出警告时，修改脚本、重新生成并再次检查。
6. 若当前会话实际具备 Office/PDF 渲染或页面预览能力，再对所有页面或幻灯片做视觉检查。否则明确说明只完成了结构检查和启发式布局检查，不要声称已经视觉验收。
7. 向用户提供最终文件路径、格式和已完成的检查。

## Inspection Commands

```bash
scholaraio document inspect workspace/reports/report.docx
scholaraio document inspect workspace/reports/presentation.pptx
scholaraio document inspect workspace/reports/data.xlsx
```

`document inspect` 是结构化检查器：

- PPTX：报告每页 shape 的位置、尺寸和内容，并给出边界/文字溢出启发式警告。
- DOCX：报告章节、段落、表格、图片和样式结构。
- XLSX：报告 sheet、数据范围、冻结窗格、合并单元格、预览和图表。

它不能代替完整的 Office 渲染器。无警告不等于视觉布局一定正确。

## Composition Rules

| 前置任务 | 组合方式 |
|---|---|
| 绘制流程图或论文图 | `/draw` 生成 SVG/PNG，再嵌入 Office 文件 |
| 搜索或整理论文 | `/search`、`/workspace` 或写作 skill 先生成有来源的内容 |
| 文献综述或论文章节 | `/literature-review` 或 `/paper-writing` 先完成内容，再封装 DOCX |
| 普通演示稿 | 先完成故事线与逐页内容，再生成 PPTX |

## Quality Gates

- 保留输入数据、生成脚本和最终 Office 文件，使交付可重复生成。
- 不编造引用、图表数据或缺失内容；无法核验的内容必须标注。
- DOCX 使用语义化标题样式，不用手工字号假装标题层级。
- PPTX 统一页面尺寸、边距、标题层级和视觉网格，避免默认模板堆字。
- XLSX 保留原始数据精度，显式设置数字格式、冻结表头和筛选范围。
- 检查结果失败或出现警告时，先修复再交付；不能修复时明确列出剩余问题。

## Simple Conversion Escape Hatch

只有简单 Markdown → DOCX 且不需要高级排版时，才使用：

```bash
scholaraio export docx --input workspace/report.md --output workspace/reports/report.docx
```

即使使用快捷转换，也要运行 `scholaraio document inspect`。

## Examples

用户说：“帮我总结文献库，交付一份 Word 简报”
→ 先检索和核验内容 → 读取 DOCX 参考 → 生成 DOCX → inspect → 有渲染能力时再视觉检查

用户说：“把工作区论文做成给导师汇报的 PPT”
→ 先组织故事线和逐页信息 → 读取 PPTX 参考 → 生成 PPTX → inspect → 逐页视觉检查

用户说：“把论文统计导出为 Excel”
→ 获取结构化数据 → 读取 XLSX 参考 → 生成带格式和筛选的 XLSX → inspect
