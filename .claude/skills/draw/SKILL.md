---
name: draw
description: Generate diagrams from structured text via an intermediate representation
  (IR). Supports multiple rendering backends including Mermaid flowcharts, Graphviz
  DOT/SVG, drawio XML, and custom vector graphics via cli-anything-inkscape.
  Use when the user wants to visualize workflows, architecture, data relationships,
  research timelines, concept maps, or create polished figures for papers.
version: 1.1.0
author: ZimoLiao/scholaraio
license: MIT
tags:
- academic
- diagram
- vector-graphics
- visualization
tier: visualization
destructive: false
---

# 绘图工具（Text → IR → Diagram）

`draw` skill 的核心工作流是**两步式**：先将文字描述或论文内容转换为统一的中间表示（IR），再将 IR 渲染为多种可编辑格式。

## 后端选择速查表

| 需求 | 推荐后端 | 输出格式 | 特点 |
|------|----------|----------|------|
| 快速画流程图/架构图，零依赖预览 | **Mermaid** | `.mermaid` / 嵌入 Markdown | 文本即代码，GitHub/Obsidian/Claude Code 原生渲染 |
| 论文插图，LaTeX Beamer 直插 | **Graphviz SVG** | `.svg` + `.dot` 源码 | 矢量图，可版本控制，`<?xml>` 级精确 |
| 在线协作/精调布局 | **drawio** | `.drawio` XML | 导入 [diagrams.net](https://app.diagrams.net) 后手动拖拽调整 |
| 自定义实验示意图、信息图 | **cli-anything-inkscape** | `.svg` | Python API 自由绘制形状、文字、渐变 |
| 程序化批处理、版本控制 | **Graphviz DOT** | `.dot` | 纯文本，Diff 友好，任何平台可编译 |

## 工作流架构

```
┌─────────────┐     extract_diagram_ir()      ┌────────────┐
│  文字描述    │  ────────────────────────────> │     IR     │
│  或论文全文  │                               │  {nodes,   │
└─────────────┘                               │   edges,   │
                                              │   layout}  │
                                              └─────┬──────┘
                                                    │ render_ir(fmt)
              ┌─────────────────────────────────────┼─────────────────────────────────────┐
              ▼                                     ▼                                     ▼
        ┌──────────┐                          ┌──────────┐                        ┌──────────┐
        │  Mermaid │                          │   SVG    │                        │  drawio  │
        │ flowchart│                          │ (Graphviz│                        │  XML     │
        └──────────┘                          └──────────┘                        └──────────┘
```

- **IR（Intermediate Representation）**：标准化 JSON，包含 `title`、`nodes[]`、`edges[]`、`layout_hint`
- **提取**：可由 LLM 从论文 Method/Architecture 章节自动提取，也可由用户直接提供文字描述后调用 LLM 生成 IR
- **渲染**：通过 `render_ir(ir, fmt)` 分发到注册的后端，完全解耦

## 使用方式

### 方式 1：从论文自动生成（调用 diagram CLI）

```bash
# 提取论文中的模型架构，渲染为 SVG
scholaraio diagram <paper-id> --type model_arch --format svg

# 只提取 IR，保存 JSON 供后续二次渲染
scholaraio diagram <paper-id> --type model_arch --dump-ir

# 从已有 IR 渲染为 drawio
scholaraio diagram --from-ir workspace/figures/xxx.ir.json --format drawio

# 启用 Critic-Agent 闭环迭代自审（自动检查完整性、准确性、一致性并修正）
scholaraio diagram <paper-id> --type model_arch --format svg --critic

# 指定 Critic 最大迭代轮次（默认 3 轮）
scholaraio diagram <paper-id> --type model_arch --format svg --critic --critic-rounds 2
```

### 方式 2：从文字描述生成 IR 再渲染

当用户给出一段文字描述（如研究流程、实验设计）时：

1. 调用 LLM 将描述转换为 IR JSON
2. 使用 `render_ir()` 或 `scholaraio diagram --from-ir` 生成目标格式

### 方式 3：Mermaid 零依赖渲染

若用户只需要快速预览流程图，直接在 Markdown 中写 Mermaid 语法即可：

```markdown
```mermaid
flowchart TD
    A[文献调研] --> B[问题定义]
    B --> C[方法设计]
    C --> D[实验实施]
```
```

Claude Code 预览自动渲染，无需任何外部工具。

### 方式 4：cli-anything-inkscape 自定义矢量图

适合需要精确控制每个像素的信息图、实验装置示意图。

```python
from pathlib import Path
from cli_anything.inkscape.core import (
    document as doc_mod, shapes as shape_mod,
    text as text_mod, styles as style_mod, export as export_mod,
)

SVG = Path("workspace/figures/diagram.svg")
SVG.parent.mkdir(parents=True, exist_ok=True)

proj = doc_mod.create_document(width=800, height=300, units='px', background='#f8f9fa')

# 添加矩形
shape_mod.add_rect(proj, x=50, y=100, width=170, height=90, rx=8, ry=8)
style_mod.set_fill(proj, len(proj['objects']) - 1, "#4A90D9")

# 添加文字
text_mod.add_text(proj, text="数据输入", x=135, y=148,
                  font_size=15, font_weight='bold', text_anchor='middle', fill='#ffffff')

# 导出
export_mod.export_svg(proj, str(SVG), overwrite=True)
```

## 各后端详细用法

### Graphviz DOT / SVG

需要系统安装 `dot`：

```bash
# Ubuntu/Debian
sudo apt-get install graphviz

# macOS
brew install graphviz
```

生成 SVG（同时保留 `.dot` 源码）：

```bash
scholaraio diagram <paper-id> --format svg -o workspace/figures/
```

LaTeX Beamer 插入代码（需 `-shell-escape` + Inkscape）：

```latex
\begin{frame}
\centering
\includesvg[width=0.8\columnwidth]{workspace/figures/diagram_xxx.svg}
\end{frame}
```

### drawio XML

```bash
scholaraio diagram <paper-id> --format drawio -o workspace/figures/
```

用浏览器打开 [https://app.diagrams.net](https://app.diagrams.net) 后选择 **File → Open from → Device** 导入编辑。

### Mermaid

```bash
scholaraio diagram <paper-id> --format mermaid -o workspace/figures/
```

输出 `.mermaid` 文件，可直接嵌入 Markdown 或用 `mmdc` 本地渲染为 PNG/SVG。

## 执行逻辑

1. **判断输入来源**：
   - 用户提供了论文 ID → 调用 `scholaraio diagram` 提取 + 渲染
   - 用户提供了文字描述 → LLM 生成 IR → `render_ir()`
   - 用户已有 Mermaid 代码 → 直接嵌入 Markdown 或转 IR 后多格式输出

2. **选择后端**：参照上方「后端选择速查表」，根据用户的最终使用场景推荐格式

3. **输出到 `workspace/figures/`**：
   ```
   workspace/figures/
   ├── diagram_xxx.svg
   ├── diagram_xxx.dot
   ├── diagram_xxx.drawio
   └── diagram_xxx.mermaid
   ```

4. **提示嵌入方式**：SVG → Beamer `\includesvg`；drawio → diagrams.net 导入；Mermaid → Markdown 嵌入

## 示例

用户说："画一个我的研究流程图"
→ 若已有论文：提取 Method → IR → SVG
→ 若无论文：根据描述生成 IR → Mermaid flowchart

用户说："帮我画一个实验装置示意图"
→ 用 cli-anything-inkscape Python API 绘制自定义 SVG

用户说："把这个 Mermaid 代码转成 SVG"
→ 解析为 IR → `render_ir(ir, "svg")`

用户说："把这篇论文的模型架构画成可编辑的图"
→ `scholaraio diagram <paper-id> --type model_arch --format drawio`
