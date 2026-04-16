"""
diagram.py — 论文 → 结构化图表 IR + 多后端渲染
=================================================

架构：
    1. 提取层：``extract_diagram_ir()`` 从文本/论文提取标准 IR（JSON）
    2. 渲染层：``render_ir()`` 根据格式分发到对应后端
    3. 快捷封装：``generate_diagram()`` = 提取 + 渲染 的完整流水线

支持的后端（持续扩展）::

    dot        → Graphviz DOT 源码（文本）
    svg        → Graphviz DOT 编译为 SVG
    drawio     → draw.io (diagrams.net) XML
    mermaid    → Mermaid 结构化图表代码
    # 未来扩展：png / svg-inkscape / ai-image

Example::

    # 两步式：提取 + 渲染
    ir = extract_diagram_ir(md_text, "model_arch", cfg)
    path = render_ir(ir, "svg", out_path=Path("out.svg"))

    # 一步式：论文 → 图
    path = generate_diagram(paper_d, "model_arch", "svg", cfg)
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from scholaraio.config import Config

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. 提取层
# ---------------------------------------------------------------------------

_METHOD_SECTION_RE = re.compile(
    r"\b(method|methods|methodology|model|architecture|"
    r"network structure|system design|framework|approach|"
    r"proposed method|model architecture|proposed framework|"
    r"overall architecture|pipeline)\b",
    re.IGNORECASE,
)

_DIAGRAM_TYPES: dict[str, str] = {
    "model_arch": "神经网络/算法模块架构图（方框表示模块，箭头表示数据流或控制流，支持多层级）",
    "tech_route": "方法流程或对比图（包含顺序、分支、条件判断、循环等控制结构）",
    "exp_setup": "实验配置/数据流图（从数据源到处理到输出的完整流程）",
}


class _HeaderEntry(TypedDict):
    line: int
    level: int
    text: str


def _escape_dot_text(text: object) -> str:
    """Escape text for DOT quoted strings."""
    return json.dumps(str(text), ensure_ascii=False)[1:-1]


def _quote_dot_id(raw_id: object) -> str:
    """Quote arbitrary node ids so DOT accepts punctuation and spaces safely."""
    return json.dumps(str(raw_id), ensure_ascii=False)


def _escape_mermaid_text(text: object) -> str:
    """Escape Mermaid label text while preserving visible newlines."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _build_mermaid_id_map(nodes: list[dict]) -> dict[str, str]:
    """Sanitize arbitrary node ids into Mermaid-safe identifiers."""
    id_map: dict[str, str] = {}
    used: set[str] = set()

    for idx, node in enumerate(nodes, start=1):
        raw_id = str(node.get("id", f"n{idx}"))
        base = re.sub(r"[^A-Za-z0-9_]", "_", raw_id)
        if not base:
            base = f"n_{idx}"
        if base[0].isdigit():
            base = f"n_{base}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        id_map[raw_id] = candidate

    return id_map


def _render_sidecar_paths(path: Path, fmt: str) -> list[Path]:
    """Return auxiliary files produced alongside the main render output."""
    if fmt == "svg":
        return [path.with_suffix(".dot")]
    return []


def _extract_method_section(md_text: str, max_chars: int = 12000) -> str:
    """从 markdown 文本中定位并截取方法/架构相关章节。"""
    lines = md_text.splitlines()
    headers: list[_HeaderEntry] = []
    for i, line in enumerate(lines, start=1):
        m = re.match(r"^(#{1,4})\s+(.+)", line.rstrip())
        if m:
            headers.append({"line": i, "level": len(m.group(1)), "text": m.group(2).strip()})

    target: _HeaderEntry | None = None
    for h in headers:
        if _METHOD_SECTION_RE.search(h["text"]):
            target = h
            break

    if not target:
        _log.warning("未定位到 Method/Architecture 章节，使用全文前 %d 字符", max_chars)
        return "\n".join(lines)[:max_chars]

    start_line = target["line"]
    end_line = None
    for h in headers:
        if h["line"] > start_line and h["level"] <= target["level"]:
            end_line = h["line"] - 1
            break

    s = max(0, start_line - 1)
    e = end_line if end_line is not None else len(lines)
    section_text = "\n".join(lines[s:e])

    if len(section_text) > max_chars:
        section_text = section_text[:max_chars] + "\n...[truncated]"
    return section_text


def _call_llm(prompt: str, cfg: Config, *, json_mode: bool = True, max_tokens: int = 8000) -> str:
    from scholaraio.metrics import call_llm

    result = call_llm(
        prompt,
        cfg,
        json_mode=json_mode,
        max_tokens=max_tokens,
        purpose="diagram",
    )
    return result.content


def _parse_json(text: str) -> dict:
    """解析 LLM 返回的 JSON，兼容 code fence 和未转义反斜杠。"""
    text = text.strip()
    text = re.sub(r"^```\w*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return json.loads(text)


def extract_diagram_ir(md_text: str, diagram_type: str, cfg: Config) -> dict:
    """使用 LLM 从论文文本提取图表的中间表示（IR）。

    IR 格式::

        {
            "title": "图标题",
            "nodes": [
                {"id": "node1", "label": "Input Data",
                 "type": "module|data|operation|decision", "layer": 1}
            ],
            "edges": [
                {"from": "node1", "to": "node2",
                 "label": "feature vector", "style": "solid|dashed|bold"}
            ],
            "layout_hint": "horizontal|vertical|hierarchical|bipartite"
        }

    Args:
        md_text: 论文 markdown 全文。
        diagram_type: 图表类型（``model_arch`` / ``tech_route`` / ``exp_setup``）。
        cfg: 全局配置。

    Returns:
        解析后的 IR 字典。

    Raises:
        ValueError: 当 ``diagram_type`` 不支持或 LLM 返回格式错误时抛出。
    """
    if diagram_type not in _DIAGRAM_TYPES:
        raise ValueError(f"不支持的 diagram 类型: {diagram_type}（支持: {', '.join(_DIAGRAM_TYPES)}）")

    section_text = _extract_method_section(md_text)

    prompt = (
        f"你是一位专业的科研可视化专家。请根据以下论文的 Method/Architecture 章节内容，"
        f"提取并结构化一幅 **{_DIAGRAM_TYPES[diagram_type]}** 的图信息。\n\n"
        f"要求：\n"
        f"1. 只提取文本中明确描述的结构，不要过度推断。\n"
        f"2. 节点（nodes）应有清晰的学术标签，避免口语化。\n"
        f"3. 边（edges）表示数据流、控制流或依赖关系，必要时添加 label。\n"
        f"4. layer 字段用于分层布局（数值越小越靠上/左），同层节点可并列。\n"
        f"5. 如果存在多个子模块/子网络，用层次化方式组织。\n\n"
        f"返回严格的 JSON 格式，不要有任何额外说明：\n"
        f"{{\n"
        f'  "title": "<图的学术标题>",\n'
        f'  "nodes": [\n'
        f'    {{"id": "n1", "label": "...", '
        f'"type": "module|data|operation|decision", "layer": 1}}\n'
        f"  ],\n"
        f'  "edges": [\n'
        f'    {{"from": "n1", "to": "n2", "label": "...", '
        f'"style": "solid|dashed|bold"}}\n'
        f"  ],\n"
        f'  "layout_hint": "horizontal|vertical|hierarchical|bipartite"\n'
        f"}}\n\n"
        f"论文内容：\n{section_text}"
    )

    raw = _call_llm(prompt, cfg, json_mode=True, max_tokens=8000)
    ir = _parse_json(raw)

    if not isinstance(ir.get("nodes"), list) or not isinstance(ir.get("edges"), list):
        raise ValueError("LLM 返回的 IR 格式不正确，缺少 nodes 或 edges 列表")

    return ir


# ---------------------------------------------------------------------------
# 2. 渲染层 —— 多后端注册表
# ---------------------------------------------------------------------------

Renderer = Callable[[dict, Path | None], Path | str]
_RENDERERS: dict[str, Renderer] = {}


def _register(fmt: str) -> Callable[[Renderer], Renderer]:
    """装饰器：注册渲染后端。"""

    def wrapper(fn: Renderer) -> Renderer:
        _RENDERERS[fmt] = fn
        return fn

    return wrapper


def list_renderers() -> list[str]:
    """返回当前支持的所有渲染格式列表。"""
    return list(_RENDERERS.keys())


# --- 2.1 Graphviz DOT 后端 ---


@_register("dot")
def _render_dot(ir: dict, out_path: Path | None = None) -> Path | str:
    """IR → Graphviz DOT 源码。"""
    title = _escape_dot_text(ir.get("title", "Diagram"))
    nodes = ir.get("nodes", [])
    edges = ir.get("edges", [])
    layout_hint = ir.get("layout_hint", "hierarchical")

    rankdir = "LR" if layout_hint in ("horizontal", "bipartite") else "TB"

    lines = [
        "// Generated by ScholarAIO paper2diagram",
        "digraph G {",
        f'    label="{title}";',
        '    labelloc="t";',
        "    fontsize=18;",
        '    fontname="Helvetica";',
        f"    rankdir={rankdir};",
        '    node [shape=box, style="rounded,filled", fillcolor="#f0f4f8", fontname="Helvetica", fontsize=12];',
        '    edge [fontname="Helvetica", fontsize=10, color="#555566"];',
        "",
    ]

    layers: dict[int, list[dict]] = {}
    for n in nodes:
        layers.setdefault(n.get("layer", 1), []).append(n)

    for layer in sorted(layers):
        ns = layers[layer]
        lines.append(f"    subgraph cluster_layer{layer} {{")
        lines.append(f'        label="Layer {layer}";')
        lines.append("        style=invis;")
        for n in ns:
            nid = n["id"]
            dot_id = _quote_dot_id(nid)
            label = _escape_dot_text(n.get("label", nid))
            ntype = n.get("type", "module")
            shape = "box"
            fillcolor = "#f0f4f8"
            if ntype == "data":
                fillcolor = "#e8f5e9"
                shape = "ellipse"
            elif ntype == "operation":
                fillcolor = "#fff3e0"
            elif ntype == "decision":
                fillcolor = "#fce4ec"
                shape = "diamond"
            lines.append(f'        {dot_id} [label="{label}", shape={shape}, fillcolor="{fillcolor}"];')
        lines.append("    }")
        lines.append("")

    for e in edges:
        src = _quote_dot_id(e["from"])
        dst = _quote_dot_id(e["to"])
        label = _escape_dot_text(e.get("label", ""))
        style = e.get("style", "solid")
        if label:
            lines.append(f'    {src} -> {dst} [label="{label}", style={style}];')
        else:
            lines.append(f"    {src} -> {dst} [style={style}];")

    lines.append("}")
    dot_text = "\n".join(lines)

    if out_path is None:
        return dot_text
    out_path.write_text(dot_text, encoding="utf-8")
    return out_path


def _dot_to_svg(dot_text: str, svg_path: Path) -> None:
    """调用系统 ``dot`` 命令将 DOT 编译为 SVG。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".dot", delete=False) as f:
        f.write(dot_text)
        dot_path = Path(f.name)
    try:
        subprocess.run(
            ["dot", "-Tsvg", str(dot_path), "-o", str(svg_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"dot 编译失败: {e.stderr}") from e
    except FileNotFoundError as e:
        raise RuntimeError("未找到 graphviz 的 dot 命令，请安装 graphviz") from e
    finally:
        dot_path.unlink(missing_ok=True)


@_register("svg")
def _render_svg(ir: dict, out_path: Path | None = None) -> Path | str:
    """IR → Graphviz DOT → SVG。"""
    if out_path is None:
        raise ValueError("svg 渲染需要提供 out_path")
    dot_path = out_path.with_suffix(".dot")
    dot_text = _render_dot(ir, dot_path)
    if isinstance(dot_text, Path):
        dot_text = dot_text.read_text(encoding="utf-8")
    _dot_to_svg(dot_text, out_path)
    return out_path


# --- 2.2 draw.io 后端 ---


@_register("drawio")
def _render_drawio(ir: dict, out_path: Path | None = None) -> Path | str:
    """IR → draw.io XML。"""
    nodes = ir.get("nodes", [])
    edges = ir.get("edges", [])
    layout_hint = ir.get("layout_hint", "hierarchical")
    rankdir = "LR" if layout_hint in ("horizontal", "bipartite") else "TB"

    node_width, node_height = 120, 60
    h_gap = 200 if rankdir == "LR" else 180
    v_gap = 100 if rankdir == "LR" else 120

    layers: dict[int, list[dict]] = {}
    for n in nodes:
        layers.setdefault(n.get("layer", 1), []).append(n)

    positions: dict[str, tuple[int, int]] = {}
    x0, y0 = 40, 40
    if rankdir == "LR":
        for li, layer in enumerate(sorted(layers)):
            for ni, n in enumerate(layers[layer]):
                positions[n["id"]] = (x0 + li * h_gap, y0 + ni * v_gap)
    else:
        for li, layer in enumerate(sorted(layers)):
            for ni, n in enumerate(layers[layer]):
                positions[n["id"]] = (x0 + ni * h_gap, y0 + li * v_gap)

    fill_map = {
        "module": "#f0f4f8",
        "data": "#e8f5e9",
        "operation": "#fff3e0",
        "decision": "#fce4ec",
    }
    shape_map = {
        "module": "rounded=1;arcSize=10;",
        "data": "ellipse;",
        "operation": "rounded=1;arcSize=5;",
        "decision": "rhombus;",
    }

    def _esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    mx_cells = []
    cell_id = 2
    node_cell_map: dict[str, int] = {}

    for n in nodes:
        nid = n["id"]
        label = n.get("label", nid)
        ntype = n.get("type", "module")
        x, y = positions.get(nid, (x0, y0))
        fill = fill_map.get(ntype, "#f0f4f8")
        shape_style = shape_map.get(ntype, "rounded=1;arcSize=10;")
        style = f"{shape_style}whiteSpace=wrap;html=1;strokeColor=#333333;fillColor={fill};fontColor=#1a1a2e;spacing=4;"
        mx_cells.append(
            f'        <mxCell id="{cell_id}" value="{_esc(label)}" style="{style}" '
            f'vertex="1" parent="1">\n'
            f'          <mxGeometry x="{x}" y="{y}" '
            f'width="{node_width}" height="{node_height}" as="geometry" />\n'
            f"        </mxCell>"
        )
        node_cell_map[nid] = cell_id
        cell_id += 1

    for e in edges:
        src = e["from"]
        dst = e["to"]
        label = e.get("label", "")
        src_cell = node_cell_map.get(src)
        dst_cell = node_cell_map.get(dst)
        if src_cell is None or dst_cell is None:
            continue
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
            "jettySize=auto;html=1;strokeColor=#555566;fontColor=#555566;"
        )
        mx_cells.append(
            f'        <mxCell id="{cell_id}" value="{_esc(label)}" style="{style}" '
            f'edge="1" parent="1" source="{src_cell}" target="{dst_cell}">\n'
            '          <mxGeometry relative="1" as="geometry" />\n'
            "        </mxCell>"
        )
        cell_id += 1

    cells_str = "\n".join(mx_cells)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxfile host="app.diagrams.net" modified="2026-04-14T00:00:00.000Z" '
        'agent="ScholarAIO" version="22.0.0" etag="scholaraio" type="device">\n'
        '  <diagram name="Page-1" id="scholaraio-diagram">\n'
        '    <mxGraphModel dx="1422" dy="822" grid="1" gridSize="10" '
        'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" '
        'pageScale="1" pageWidth="850" pageHeight="1100" math="0" shadow="0">\n'
        "      <root>\n"
        '        <mxCell id="0" />\n'
        '        <mxCell id="1" parent="0" />\n'
        f"{cells_str}\n"
        "      </root>\n"
        "    </mxGraphModel>\n"
        "  </diagram>\n"
        "</mxfile>"
    )

    if out_path is None:
        return xml
    out_path.write_text(xml, encoding="utf-8")
    return out_path


# --- 2.3 Mermaid 后端 ---


@_register("mermaid")
def _render_mermaid(ir: dict, out_path: Path | None = None) -> Path | str:
    """IR → Mermaid flowchart 代码。"""
    layout_hint = ir.get("layout_hint", "hierarchical")
    direction = "LR" if layout_hint in ("horizontal", "bipartite") else "TD"
    nodes = ir.get("nodes", [])
    edges = ir.get("edges", [])
    id_map = _build_mermaid_id_map(nodes)

    lines = [f"flowchart {direction}"]
    for n in nodes:
        raw_id = str(n["id"])
        nid = id_map.get(raw_id, raw_id)
        label = _escape_mermaid_text(n.get("label", raw_id))
        ntype = n.get("type", "module")
        # Mermaid 形状语法映射
        if ntype == "data":
            lines.append(f'    {nid}(["{label}"])')
        elif ntype == "decision":
            lines.append(f'    {nid}{{{{"{label}"}}}}')
        else:
            lines.append(f'    {nid}["{label}"]')

    for e in edges:
        src = id_map.get(str(e["from"]), str(e["from"]))
        dst = id_map.get(str(e["to"]), str(e["to"]))
        label = _escape_mermaid_text(e.get("label", ""))
        style = e.get("style", "solid")
        arrow = "--"
        if style == "dashed":
            arrow = "-.-"
        elif style == "bold":
            arrow = "=="
        if label:
            lines.append(f'    {src} {arrow}>|"{label}"| {dst}')
        else:
            lines.append(f"    {src} {arrow}> {dst}")

    mermaid_text = "\n".join(lines)
    if out_path is None:
        return mermaid_text
    out_path.write_text(mermaid_text, encoding="utf-8")
    return out_path


# --- 2.4 未来扩展占位（Inkscape / AI 文生图） ---
# @_register("png")
# def _render_png(ir: dict, out_path: Path | None = None) -> Path | str:
#    """IR → cli-anything-inkscape → PNG。"""
#    raise NotImplementedError("png 渲染器尚未实现")


# ---------------------------------------------------------------------------
# 3. 渲染分发
# ---------------------------------------------------------------------------


def render_ir(ir: dict, fmt: str, out_path: Path | None = None) -> Path | str:
    """将 IR 渲染为指定格式。

    Args:
        ir: 图表中间表示（由 ``extract_diagram_ir`` 生成）。
        fmt: 目标格式（``dot`` / ``svg`` / ``drawio`` / ``mermaid``）。
        out_path: 输出文件路径，为 ``None`` 时返回字符串内容。

    Returns:
        若提供了 ``out_path``，返回该路径；否则返回渲染结果的字符串。

    Raises:
        ValueError: 当 ``fmt`` 不支持时抛出。
    """
    if fmt not in _RENDERERS:
        raise ValueError(f"不支持的渲染格式: {fmt}（支持: {', '.join(_RENDERERS.keys())}）")
    return _RENDERERS[fmt](ir, out_path)


# ---------------------------------------------------------------------------
# 4. Critic-Agent 闭环迭代（参考 PaperVizAgent 的 Critic-Visualizer loop）
# ---------------------------------------------------------------------------


def critique_diagram_ir(
    ir: dict,
    md_text: str,
    diagram_type: str,
    cfg: Config,
    round_idx: int = 1,
) -> dict:
    """扮演严格审稿人，对 IR 进行多维度审查。

    审查维度：
        - completeness: 是否遗漏原文中明确描述的关键模块/步骤/数据流
        - accuracy: 节点标签、边方向、层级关系是否与原文一致
        - clarity: 标签是否学术化、避免口语化，同层级节点是否并列合理
        - consistency: 边的起止节点是否都存在于 nodes 列表中

    Args:
        ir: 当前轮次的 IR。
        md_text: 论文 markdown 全文（用于对照）。
        diagram_type: 图表类型。
        cfg: 全局配置。
        round_idx: 当前 critic 轮次（用于日志和 prompt）。

    Returns:
        包含 ``verdict``、``issues``、``suggestions`` 的 critique 字典。
    """
    section_text = _extract_method_section(md_text)

    prompt = (
        f"你是一位严格的科研图表审稿人。请对以下 **{_DIAGRAM_TYPES[diagram_type]}** 的"
        f"中间表示（IR）进行第 {round_idx} 轮审查，对照论文的 Method/Architecture 章节内容。\n\n"
        f"审查要求：\n"
        f"1. completeness: 是否遗漏原文中明确描述的关键模块、步骤、子网络或数据流。\n"
        f"2. accuracy: 节点标签是否准确反映原文术语，边方向是否正确，层级关系是否合理。\n"
        f"3. clarity: 标签是否学术化（避免口语化），是否简洁清晰，同层节点是否并列合理。\n"
        f"4. consistency: 所有 edges 中的 from/to 节点是否都存在于 nodes 列表中。\n\n"
        f"返回严格的 JSON（不要有任何额外说明）：\n"
        f"{{\n"
        f'  "round": {round_idx},\n'
        f'  "verdict": "needs_revision|acceptable",\n'
        f'  "issues": [\n'
        f'    {{"aspect": "completeness|accuracy|clarity|consistency", '
        f'"description": "...", "severity": "major|minor"}}\n'
        f"  ],\n"
        f'  "suggestions": ["..."]\n'
        f"}}\n\n"
        f"论文内容：\n{section_text}\n\n"
        f"当前 IR：\n{json.dumps(ir, ensure_ascii=False, indent=2)}"
    )

    raw = _call_llm(prompt, cfg, json_mode=True, max_tokens=4000)
    critique = _parse_json(raw)

    # 防御性校验：确保字段存在
    if not isinstance(critique.get("issues"), list):
        critique["issues"] = []
    if not isinstance(critique.get("suggestions"), list):
        critique["suggestions"] = []
    if critique.get("verdict") not in ("needs_revision", "acceptable"):
        critique["verdict"] = "acceptable"
    return critique


def refine_diagram_ir(
    ir: dict,
    critique: dict,
    md_text: str,
    diagram_type: str,
    cfg: Config,
) -> dict:
    """根据 critique 反馈修正 IR。

    Args:
        ir: 当前 IR。
        critique: critique_diagram_ir 的输出。
        md_text: 论文 markdown 全文。
        diagram_type: 图表类型。
        cfg: 全局配置。

    Returns:
        修正后的 IR 字典。
    """
    section_text = _extract_method_section(md_text)

    prompt = (
        f"你是一位专业的科研可视化专家。请根据审稿反馈，修正以下 **{_DIAGRAM_TYPES[diagram_type]}** 的"
        f"中间表示（IR），使其更准确、完整、清晰。\n\n"
        f"修正原则：\n"
        f"1. 只修改 critique 中指出的问题，不要过度推断或添加原文未提及的内容。\n"
        f"2. 保持 IR 的 JSON 结构不变：必须包含 title、nodes、edges、layout_hint。\n"
        f"3. nodes 中的 id 必须唯一，edges 中的 from/to 必须对应存在的 node id。\n"
        f"4. 如果反馈认为当前 IR 已足够好，可以原样返回。\n\n"
        f"返回严格的 JSON 格式，不要有任何额外说明。\n\n"
        f"论文内容：\n{section_text}\n\n"
        f"审稿反馈：\n{json.dumps(critique, ensure_ascii=False, indent=2)}\n\n"
        f"当前 IR：\n{json.dumps(ir, ensure_ascii=False, indent=2)}\n\n"
        f"修正后的 IR："
    )

    raw = _call_llm(prompt, cfg, json_mode=True, max_tokens=8000)
    refined = _parse_json(raw)

    if not isinstance(refined.get("nodes"), list) or not isinstance(refined.get("edges"), list):
        raise ValueError("LLM 返回的修正 IR 格式不正确，缺少 nodes 或 edges 列表")

    return refined


def generate_diagram_with_critic(
    paper_d: Path,
    diagram_type: str,
    fmt: str,
    cfg: Config,
    out_dir: Path | None = None,
    dump_ir: bool = False,
    max_rounds: int = 3,
) -> dict:
    """从论文生成图表，启用 Critic-Agent 闭环迭代。

    流程：
        extract IR → render → critique → (refine → re-render) × max_rounds
        当 critique 返回 acceptable 或达到最大轮次时终止。

    Args:
        paper_d: 论文目录路径。
        diagram_type: 图表类型。
        fmt: 输出格式。
        cfg: 全局配置。
        out_dir: 输出目录，默认 ``workspace/figures/``。
        dump_ir: 为 ``True`` 时只输出最终 IR（不渲染）。
        max_rounds: Critic 最大迭代轮次（默认 3）。

    Returns:
        结果字典，包含 ``out_path``、``ir``、``critique_log``。
    """
    from scholaraio.loader import load_l4
    from scholaraio.papers import md_path as _md_path

    if out_dir is None:
        out_dir = Path("workspace/figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    md_file = paper_d / "paper.md"
    if not md_file.exists():
        papers_dir = paper_d.parent
        dir_name = paper_d.name
        md_file = _md_path(papers_dir, dir_name)

    md_text = load_l4(md_file)
    ir = extract_diagram_ir(md_text, diagram_type, cfg)

    safe_title = re.sub(r"[^\w\-]", "_", ir.get("title", "diagram"))[:40]
    base_name = f"{paper_d.name}_{diagram_type}_{safe_title}"

    critique_log: list[dict] = []
    out_path: Path | str | None = None

    # Guard: non-positive max_rounds falls back to single render without critique
    if max_rounds <= 0:
        if not dump_ir:
            out_path = out_dir / f"{base_name}.{fmt}"
            render_ir(ir, fmt, out_path=out_path)
            _log.info("Critic 被禁用 (max_rounds=%d)，直接生成: %s", max_rounds, out_path)
        if dump_ir:
            ir_path = out_dir / f"{base_name}.ir.json"
            ir_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            _log.info("已导出 IR: %s", ir_path)
            out_path = ir_path
        return {
            "out_path": out_path,
            "ir": ir,
            "critique_log": critique_log,
        }

    for round_idx in range(1, max_rounds + 1):
        # 每轮重新渲染（闭环）
        if not dump_ir:
            out_path = out_dir / f"{base_name}_r{round_idx}.{fmt}"
            render_ir(ir, fmt, out_path=out_path)
            _log.info("Critic round %d: 已生成 %s", round_idx, out_path)

        critique = critique_diagram_ir(ir, md_text, diagram_type, cfg, round_idx=round_idx)
        critique_log.append(critique)

        _log.info(
            "Critic round %d: verdict=%s, issues=%d",
            round_idx,
            critique["verdict"],
            len(critique.get("issues", [])),
        )

        if critique["verdict"] == "acceptable":
            break

        # 最后一轮若仍 needs_revision，不再 refine，保留当前 IR
        if round_idx < max_rounds:
            ir = refine_diagram_ir(ir, critique, md_text, diagram_type, cfg)

    # 最终产物命名：去掉 _rN 后缀，使用统一最终名称
    if not dump_ir and out_path is not None:
        final_path = out_dir / f"{base_name}.{fmt}"
        # 复制最后一轮产物到最终路径
        import shutil

        shutil.copy(str(out_path), str(final_path))
        for sidecar in _render_sidecar_paths(Path(out_path), fmt):
            if sidecar.exists():
                shutil.copy(str(sidecar), str(final_path.with_suffix(sidecar.suffix)))
        # 清理中间产物
        for r in range(1, max_rounds + 1):
            mid = out_dir / f"{base_name}_r{r}.{fmt}"
            if mid.exists():
                mid.unlink()
            for sidecar in _render_sidecar_paths(mid, fmt):
                if sidecar.exists():
                    sidecar.unlink()
        out_path = final_path
        _log.info("Critic 闭环完成，最终输出: %s", out_path)

    if dump_ir:
        ir_path = out_dir / f"{base_name}.ir.json"
        ir_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _log.info("已导出 IR: %s", ir_path)
        out_path = ir_path

    return {
        "out_path": out_path,
        "ir": ir,
        "critique_log": critique_log,
    }


# ---------------------------------------------------------------------------
# 5. 快捷封装
# ---------------------------------------------------------------------------


def generate_diagram(
    paper_d: Path,
    diagram_type: str,
    fmt: str,
    cfg: Config,
    out_dir: Path | None = None,
    dump_ir: bool = False,
) -> Path | str:
    """从论文生成可编辑图表（提取 + 渲染 快捷流水线，无 Critic）。

    Args:
        paper_d: 论文目录路径（包含 ``meta.json`` 和 ``paper.md``）。
        diagram_type: 图表类型（``model_arch`` / ``tech_route`` / ``exp_setup``）。
        fmt: 输出格式（``dot`` / ``svg`` / ``drawio`` / ``mermaid``）。
        cfg: 全局配置。
        out_dir: 输出目录，默认 ``workspace/figures/``。
        dump_ir: 为 ``True`` 时只输出 JSON IR 文件（不渲染）。

    Returns:
        生成的文件路径，或 ``dump_ir=True`` 时的 IR 文本。
    """
    from scholaraio.loader import load_l4
    from scholaraio.papers import md_path as _md_path

    if out_dir is None:
        out_dir = Path("workspace/figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    md_file = paper_d / "paper.md"
    if not md_file.exists():
        papers_dir = paper_d.parent
        dir_name = paper_d.name
        md_file = _md_path(papers_dir, dir_name)

    md_text = load_l4(md_file)
    ir = extract_diagram_ir(md_text, diagram_type, cfg)

    safe_title = re.sub(r"[^\w\-]", "_", ir.get("title", "diagram"))[:40]
    base_name = f"{paper_d.name}_{diagram_type}_{safe_title}"

    if dump_ir:
        ir_path = out_dir / f"{base_name}.ir.json"
        ir_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _log.info("已导出 IR: %s", ir_path)
        return ir_path

    out_path = out_dir / f"{base_name}.{fmt}"
    result = render_ir(ir, fmt, out_path=out_path)
    _log.info("已生成: %s", result)
    return result


def extract_diagram_ir_from_text(description: str, diagram_type: str, cfg: Config) -> dict:
    """从用户提供的文字描述提取图表 IR（不依赖论文原文）。

    Args:
        description: 用户描述的方法/流程/架构文字。
        diagram_type: 图表类型（``model_arch`` / ``tech_route`` / ``exp_setup``）。
        cfg: 全局配置。

    Returns:
        解析后的 IR 字典。
    """
    if diagram_type not in _DIAGRAM_TYPES:
        raise ValueError(f"不支持的 diagram 类型: {diagram_type}（支持: {', '.join(_DIAGRAM_TYPES)}）")

    prompt = (
        f"你是一位专业的科研可视化专家。请根据以下文字描述，"
        f"提取并结构化一幅 **{_DIAGRAM_TYPES[diagram_type]}** 的图信息。\n\n"
        f"要求：\n"
        f"1. 只提取描述中明确提到的结构，不要过度推断。\n"
        f"2. 节点（nodes）应有清晰的学术标签，避免口语化。\n"
        f"3. 边（edges）表示数据流、控制流或依赖关系，必要时添加 label。\n"
        f"4. layer 字段用于分层布局（数值越小越靠上/左），同层节点可并列。\n"
        f"5. 如果存在多个子模块/子网络，用层次化方式组织。\n\n"
        f"返回严格的 JSON 格式，不要有任何额外说明：\n"
        f"{{\n"
        f'  "title": "<图的学术标题>",\n'
        f'  "nodes": [\n'
        f'    {{"id": "n1", "label": "...", '
        f'"type": "module|data|operation|decision", "layer": 1}}\n'
        f"  ],\n"
        f'  "edges": [\n'
        f'    {{"from": "n1", "to": "n2", "label": "...", '
        f'"style": "solid|dashed|bold"}}\n'
        f"  ],\n"
        f'  "layout_hint": "horizontal|vertical|hierarchical|bipartite"\n'
        f"}}\n\n"
        f"文字描述：\n{description}"
    )

    raw = _call_llm(prompt, cfg, json_mode=True, max_tokens=8000)
    ir = _parse_json(raw)

    if not isinstance(ir.get("nodes"), list) or not isinstance(ir.get("edges"), list):
        raise ValueError("LLM 返回的 IR 格式不正确，缺少 nodes 或 edges 列表")

    return ir


def generate_diagram_from_text(
    description: str,
    diagram_type: str,
    fmt: str,
    cfg: Config,
    out_dir: Path | None = None,
    dump_ir: bool = False,
) -> Path | str:
    """从文字描述生成可编辑图表。

    Args:
        description: 用户描述的方法/流程/架构文字。
        diagram_type: 图表类型（``model_arch`` / ``tech_route`` / ``exp_setup``）。
        fmt: 输出格式（``dot`` / ``svg`` / ``drawio`` / ``mermaid``）。
        cfg: 全局配置。
        out_dir: 输出目录，默认 ``workspace/figures/``。
        dump_ir: 为 ``True`` 时只输出 JSON IR 文件（不渲染）。

    Returns:
        生成的文件路径，或 ``dump_ir=True`` 时的 IR 文本。
    """
    if out_dir is None:
        out_dir = Path("workspace/figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    ir = extract_diagram_ir_from_text(description, diagram_type, cfg)

    safe_title = re.sub(r"[^\w\-]", "_", ir.get("title", "diagram"))[:40]
    base_name = f"from_text_{diagram_type}_{safe_title}"

    if dump_ir:
        ir_path = out_dir / f"{base_name}.ir.json"
        ir_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _log.info("已导出 IR: %s", ir_path)
        return ir_path

    out_path = out_dir / f"{base_name}.{fmt}"
    result = render_ir(ir, fmt, out_path=out_path)
    _log.info("已生成: %s", result)
    return result
