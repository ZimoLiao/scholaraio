"""Tests for scholaraio.diagram IR extraction, multi-backend renderers, and CLI cmd_diagram."""

from __future__ import annotations

import json
import shutil
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scholaraio import cli
from scholaraio.config import Config
from scholaraio.diagram import (
    _extract_method_section,
    _parse_json,
    critique_diagram_ir,
    extract_diagram_ir,
    extract_diagram_ir_from_text,
    generate_diagram,
    generate_diagram_from_text,
    generate_diagram_with_critic,
    list_renderers,
    refine_diagram_ir,
    render_ir,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_ir() -> dict:
    return {
        "title": "Test Model",
        "nodes": [
            {"id": "input", "label": "Input Data", "type": "data", "layer": 1},
            {"id": "enc", "label": "Encoder", "type": "module", "layer": 2},
            {"id": "dec", "label": "Decoder", "type": "operation", "layer": 3},
            {"id": "gate", "label": "Gate?", "type": "decision", "layer": 2},
            {"id": "out", "label": "Output", "type": "data", "layer": 3},
        ],
        "edges": [
            {"from": "input", "to": "enc", "label": "x", "style": "solid"},
            {"from": "enc", "to": "gate", "label": "z", "style": "dashed"},
            {"from": "gate", "to": "dec", "label": "yes", "style": "bold"},
            {"from": "dec", "to": "out", "label": "", "style": "solid"},
        ],
        "layout_hint": "horizontal",
    }


@pytest.fixture()
def tmp_paper_dir(tmp_path: Path) -> Path:
    """Create a temporary paper directory with a Method section."""
    paper_dir = tmp_path / "Test-2024-Paper"
    paper_dir.mkdir()
    (paper_dir / "meta.json").write_text(json.dumps({"id": "test-uuid"}), encoding="utf-8")
    md_content = (
        "# Introduction\nThis is intro.\n\n"
        "# Method\nWe propose an encoder-decoder architecture.\n\n"
        "## Encoder\nThe encoder takes input.\n\n"
        "## Decoder\nThe decoder reconstructs output.\n\n"
        "# Experiments\nResults are great.\n"
    )
    (paper_dir / "paper.md").write_text(md_content, encoding="utf-8")
    return paper_dir


@pytest.fixture()
def mock_cfg(tmp_path: Path) -> Config:
    return Config(_root=tmp_path)


# ---------------------------------------------------------------------------
# _extract_method_section
# ---------------------------------------------------------------------------


class TestExtractMethodSection:
    def test_extracts_method_section(self):
        md = "# Introduction\nIntro text.\n\n# Method\nWe propose X.\nDetails.\n\n# Results\nGreat results.\n"
        section = _extract_method_section(md, max_chars=500)
        assert "Method" in section
        assert "We propose X." in section
        assert "Results" not in section

    def test_falls_back_to_full_text_prefix_when_no_method(self):
        md = "# Introduction\n" + "word " * 200
        section = _extract_method_section(md, max_chars=100)
        assert "Introduction" in section
        assert len(section) <= 120  # includes truncation suffix

    def test_truncates_long_section(self):
        md = "# Method\n" + "word " * 10000
        section = _extract_method_section(md, max_chars=500)
        assert "word" in section
        assert "truncated" in section or len(section) <= 520

    def test_matches_architecture_synonyms(self):
        for header in ["# Model Architecture", "# Proposed Framework", "# System Design"]:
            md = f"{header}\nContent here.\n\n# Results\nNope.\n"
            section = _extract_method_section(md, max_chars=500)
            assert "Content here." in section
            assert "Results" not in section


# ---------------------------------------------------------------------------
# _parse_json
# ---------------------------------------------------------------------------


class TestParseJson:
    def test_plain_json(self):
        assert _parse_json('{"a": 1}') == {"a": 1}

    def test_strips_code_fence(self):
        raw = '```json\n{"b": 2}\n```'
        assert _parse_json(raw) == {"b": 2}

    def test_fixes_unescaped_backslash(self):
        raw = r'{"eq": "E=mc^2 \propto \alpha"}'
        result = _parse_json(raw)
        assert result["eq"] == r"E=mc^2 \propto \alpha"


# ---------------------------------------------------------------------------
# extract_diagram_ir
# ---------------------------------------------------------------------------


class TestExtractDiagramIr:
    def test_successful_extraction(self, mock_cfg, monkeypatch):
        expected_ir = {
            "title": "Auto-Encoder",
            "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "vertical",
        }

        def fake_llm(prompt, cfg, *, json_mode=True, max_tokens=8000):
            return json.dumps(expected_ir, ensure_ascii=False)

        monkeypatch.setattr("scholaraio.diagram._call_llm", fake_llm)

        ir = extract_diagram_ir("# Method\nWe use an auto-encoder.", "model_arch", mock_cfg)
        assert ir["title"] == "Auto-Encoder"
        assert ir["nodes"][0]["id"] == "a"

    def test_unsupported_diagram_type(self, mock_cfg):
        with pytest.raises(ValueError, match="不支持的 diagram 类型"):
            extract_diagram_ir("# Method\nX", "unknown_type", mock_cfg)

    def test_invalid_llm_response_raises(self, mock_cfg, monkeypatch):
        def fake_llm(prompt, cfg, *, json_mode=True, max_tokens=8000):
            return json.dumps({"title": "Bad", "nodes": "not-a-list"}, ensure_ascii=False)

        monkeypatch.setattr("scholaraio.diagram._call_llm", fake_llm)
        with pytest.raises(ValueError, match="IR 格式不正确"):
            extract_diagram_ir("# Method\nX", "model_arch", mock_cfg)


# ---------------------------------------------------------------------------
# Renderers — DOT
# ---------------------------------------------------------------------------


class TestRenderDot:
    def test_returns_string_when_no_out_path(self, sample_ir):
        result = render_ir(sample_ir, "dot")
        assert isinstance(result, str)
        assert "digraph G {" in result
        assert "Input Data" in result
        assert "Encoder" in result
        assert "shape=ellipse" in result  # data node
        assert "shape=diamond" in result  # decision node
        assert "style=dashed" in result
        assert "style=bold" in result

    def test_writes_file(self, sample_ir, tmp_path):
        out = tmp_path / "test.dot"
        result = render_ir(sample_ir, "dot", out_path=out)
        assert result == out
        text = out.read_text(encoding="utf-8")
        assert "digraph G {" in text


# ---------------------------------------------------------------------------
# Renderers — SVG
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("dot") is None, reason="graphviz dot not installed")
class TestRenderSvg:
    def test_writes_svg_and_dot(self, sample_ir, tmp_path):
        out = tmp_path / "test.svg"
        result = render_ir(sample_ir, "svg", out_path=out)
        assert result == out
        assert out.exists()
        assert "<svg" in out.read_text(encoding="utf-8")
        # DOT source is also preserved
        assert out.with_suffix(".dot").exists()

    def test_raises_without_out_path(self, sample_ir):
        with pytest.raises(ValueError, match="svg 渲染需要提供 out_path"):
            render_ir(sample_ir, "svg")


# ---------------------------------------------------------------------------
# Renderers — drawio
# ---------------------------------------------------------------------------


class TestRenderDrawio:
    def test_returns_string_when_no_out_path(self, sample_ir):
        result = render_ir(sample_ir, "drawio")
        assert isinstance(result, str)
        assert '<?xml version="1.0"' in result
        assert "mxfile" in result
        assert "Input Data" in result
        assert "Encoder" in result

    def test_writes_file(self, sample_ir, tmp_path):
        out = tmp_path / "test.drawio"
        result = render_ir(sample_ir, "drawio", out_path=out)
        assert result == out
        text = out.read_text(encoding="utf-8")
        assert "<mxGraphModel" in text

    def test_edge_with_label(self, sample_ir, tmp_path):
        out = tmp_path / "test.drawio"
        render_ir(sample_ir, "drawio", out_path=out)
        text = out.read_text(encoding="utf-8")
        assert 'value="x"' in text or 'value="z"' in text


# ---------------------------------------------------------------------------
# Renderers — mermaid
# ---------------------------------------------------------------------------


class TestRenderMermaid:
    def test_returns_string_when_no_out_path(self, sample_ir):
        result = render_ir(sample_ir, "mermaid")
        assert isinstance(result, str)
        assert "flowchart LR" in result
        assert 'input(["Input Data"])' in result  # data → ellipse
        assert 'gate{{"Gate?"}}' in result  # decision → diamond
        assert 'enc["Encoder"]' in result

    def test_writes_file(self, sample_ir, tmp_path):
        out = tmp_path / "test.mmd"
        result = render_ir(sample_ir, "mermaid", out_path=out)
        assert result == out
        text = out.read_text(encoding="utf-8")
        assert "flowchart LR" in text

    def test_styles_mapped(self, sample_ir):
        text = render_ir(sample_ir, "mermaid")
        assert "-.->" in text  # dashed
        assert "==" in text  # bold
        assert "-->" in text  # solid

    def test_vertical_layout(self):
        ir = {"title": "V", "nodes": [{"id": "a", "label": "A"}], "edges": [], "layout_hint": "vertical"}
        text = render_ir(ir, "mermaid")
        assert "flowchart TD" in text

    def test_dashed_edges_with_labels_use_renderable_mermaid_syntax(self):
        ir = {
            "title": "Dashed",
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b", "label": "retry", "style": "dashed"}],
            "layout_hint": "horizontal",
        }
        text = render_ir(ir, "mermaid")
        assert 'a -.->|"retry"| b' in text


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestRenderIrDispatcher:
    def test_list_renderers(self):
        fmts = list_renderers()
        assert set(fmts) >= {"dot", "svg", "drawio", "mermaid"}

    def test_unsupported_format(self, sample_ir):
        with pytest.raises(ValueError, match="不支持的渲染格式"):
            render_ir(sample_ir, "png")


# ---------------------------------------------------------------------------
# generate_diagram
# ---------------------------------------------------------------------------


class TestGenerateDiagram:
    def test_full_pipeline_to_dot(self, tmp_paper_dir, mock_cfg, monkeypatch, tmp_path):
        expected_ir = {
            "title": "Encoder-Decoder",
            "nodes": [{"id": "n1", "label": "N1", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(expected_ir))

        out = generate_diagram(tmp_paper_dir, "model_arch", "dot", mock_cfg, out_dir=tmp_path)
        assert isinstance(out, Path)
        assert out.suffix == ".dot"
        assert "Encoder-Decoder" in out.read_text(encoding="utf-8")

    def test_dump_ir(self, tmp_paper_dir, mock_cfg, monkeypatch, tmp_path):
        expected_ir = {
            "title": "IR-Only",
            "nodes": [],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(expected_ir))

        out = generate_diagram(tmp_paper_dir, "model_arch", "dot", mock_cfg, out_dir=tmp_path, dump_ir=True)
        assert out.suffix == ".json"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["title"] == "IR-Only"

    def test_fallback_md_path(self, tmp_paper_dir, mock_cfg, monkeypatch, tmp_path):
        # Rename paper.md to simulate _md_path resolution path (though default path works here)
        md_file = tmp_paper_dir / "paper.md"
        alt_md = tmp_paper_dir / "alt.md"
        alt_md.write_text(md_file.read_text(encoding="utf-8"), encoding="utf-8")
        md_file.unlink()

        # Since _md_path simply returns paper_dir / paper.md, this will fail unless we monkeypatch it
        monkeypatch.setattr(
            "scholaraio.papers.md_path",
            lambda papers_dir, dir_name: tmp_paper_dir / "alt.md",
        )
        expected_ir = {
            "title": "Fallback",
            "nodes": [],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(expected_ir))

        out = generate_diagram(tmp_paper_dir, "model_arch", "dot", mock_cfg, out_dir=tmp_path)
        assert out.exists()


# ---------------------------------------------------------------------------
# CLI cmd_diagram
# ---------------------------------------------------------------------------


@pytest.fixture()
def capture_ui(monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", messages.append)
    return messages


@pytest.fixture()
def cfg(tmp_path):
    return SimpleNamespace(papers_dir=tmp_path / "papers", index_db=tmp_path / "index.db")


@pytest.fixture()
def paper_dir(cfg):
    d = cfg.papers_dir / "Test-2024-Paper"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": "test-uuid"}), encoding="utf-8")
    (d / "paper.md").write_text("# Method\nWe use X.\n", encoding="utf-8")
    return d


class TestCliDiagram:
    def test_paper_to_svg(self, capture_ui, cfg, paper_dir, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps(
                {
                    "title": "CLI Test",
                    "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
                    "edges": [],
                    "layout_hint": "horizontal",
                }
            ),
        )
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="model_arch",
            format="dot",
            output=None,
            dump_ir=False,
            from_ir=None,
            critic=False,
            critic_rounds=3,
        )
        cli.cmd_diagram(args, cfg)
        assert any("已生成:" in m for m in capture_ui)

    def test_dump_ir(self, capture_ui, cfg, paper_dir, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps({"title": "Dump", "nodes": [], "edges": [], "layout_hint": "horizontal"}),
        )
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="exp_setup",
            format="svg",
            output=str(tmp_path),
            dump_ir=True,
            from_ir=None,
            critic=False,
            critic_rounds=3,
        )
        cli.cmd_diagram(args, cfg)
        assert any("已生成:" in m for m in capture_ui)
        # Hint should NOT be printed for dump_ir
        assert not any("Beamer" in m or "DOT 源码" in m for m in capture_ui)

    def test_from_ir(self, capture_ui, tmp_path):
        ir_path = tmp_path / "test.ir.json"
        ir_path.write_text(
            json.dumps(
                {
                    "title": "From IR",
                    "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
                    "edges": [],
                    "layout_hint": "horizontal",
                }
            ),
            encoding="utf-8",
        )
        args = Namespace(
            paper_id=None,
            type="model_arch",
            format="mermaid",
            output=str(tmp_path),
            dump_ir=False,
            from_ir=str(ir_path),
            critic=False,
            critic_rounds=3,
        )
        cli.cmd_diagram(args, None)
        assert any("已生成:" in m for m in capture_ui)
        out_path = Path(next(m for m in capture_ui if "已生成:" in m).split(": ", 1)[1])
        assert out_path.exists()
        assert "flowchart" in out_path.read_text(encoding="utf-8")

    def test_from_ir_missing_file_exits(self, capture_ui, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "exit", MagicMock(side_effect=SystemExit(1)))
        args = Namespace(
            paper_id=None,
            type="model_arch",
            format="dot",
            output=None,
            dump_ir=False,
            from_ir=str(tmp_path / "missing.json"),
            critic=False,
            critic_rounds=3,
        )
        with pytest.raises(SystemExit):
            cli.cmd_diagram(args, None)

    def test_from_ir_bad_json_exits(self, capture_ui, tmp_path, monkeypatch):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        monkeypatch.setattr(sys, "exit", MagicMock(side_effect=SystemExit(1)))
        args = Namespace(
            paper_id=None,
            type="model_arch",
            format="dot",
            output=None,
            dump_ir=False,
            from_ir=str(bad),
            critic=False,
            critic_rounds=3,
        )
        with pytest.raises(SystemExit):
            cli.cmd_diagram(args, None)

    def test_missing_paper_id_and_from_ir_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "exit", MagicMock(side_effect=SystemExit(1)))
        args = Namespace(
            paper_id=None,
            type="model_arch",
            format="dot",
            output=None,
            dump_ir=False,
            from_ir=None,
            critic=False,
            critic_rounds=3,
        )
        with pytest.raises(SystemExit):
            cli.cmd_diagram(args, None)

    def test_svg_hint_printed(self, capture_ui, cfg, paper_dir, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps(
                {
                    "title": "Hint Test",
                    "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
                    "edges": [],
                    "layout_hint": "horizontal",
                }
            ),
        )
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="model_arch",
            format="svg",
            output=None,
            dump_ir=False,
            from_ir=None,
            critic=False,
            critic_rounds=3,
        )
        # Need dot installed for svg rendering
        if shutil.which("dot") is None:
            pytest.skip("graphviz dot not installed")
        cli.cmd_diagram(args, cfg)
        assert any("Beamer" in m for m in capture_ui)
        assert any("-shell-escape" in m for m in capture_ui)

    def test_drawio_hint_printed(self, capture_ui, cfg, paper_dir, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps(
                {
                    "title": "Hint Test",
                    "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
                    "edges": [],
                    "layout_hint": "horizontal",
                }
            ),
        )
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="model_arch",
            format="drawio",
            output=None,
            dump_ir=False,
            from_ir=None,
            critic=False,
            critic_rounds=3,
        )
        cli.cmd_diagram(args, cfg)
        assert any("diagrams.net" in m for m in capture_ui)

    def test_cli_error_propagation(self, capture_ui, cfg, paper_dir, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr("scholaraio.diagram._call_llm", boom)
        monkeypatch.setattr(sys, "exit", MagicMock(side_effect=SystemExit(1)))
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="model_arch",
            format="dot",
            output=None,
            dump_ir=False,
            from_ir=None,
            critic=False,
            critic_rounds=3,
        )
        with pytest.raises(SystemExit):
            cli.cmd_diagram(args, cfg)

    def test_cli_from_text(self, capture_ui, cfg, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps(
                {
                    "title": "CLI Text",
                    "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
                    "edges": [],
                    "layout_hint": "horizontal",
                }
            ),
        )
        args = Namespace(
            paper_id=None,
            type="model_arch",
            format="dot",
            output=None,
            dump_ir=False,
            from_ir=None,
            from_text="We use a simple module.",
            critic=False,
            critic_rounds=3,
        )
        cli.cmd_diagram(args, cfg)
        assert any("已生成:" in m for m in capture_ui)

    def test_cli_mutually_exclusive_sources_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "exit", MagicMock(side_effect=SystemExit(1)))
        # Both paper_id and from_text provided
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="model_arch",
            format="dot",
            output=None,
            dump_ir=False,
            from_ir=None,
            from_text="desc",
            critic=False,
            critic_rounds=3,
        )
        with pytest.raises(SystemExit):
            cli.cmd_diagram(args, None)


# ---------------------------------------------------------------------------
# Critic-Agent 闭环
# ---------------------------------------------------------------------------


class TestCritiqueDiagramIr:
    def test_returns_structured_critique(self, mock_cfg, monkeypatch):
        expected = {
            "round": 1,
            "verdict": "acceptable",
            "issues": [],
            "suggestions": ["Keep up the good work."],
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(expected))

        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        result = critique_diagram_ir(ir, "# Method\nX", "model_arch", mock_cfg)
        assert result["verdict"] == "acceptable"
        assert result["round"] == 1

    def test_defensive_fallback_for_bad_verdict(self, mock_cfg, monkeypatch):
        bad = {"round": 1, "verdict": "weird", "issues": "not-a-list", "suggestions": None}
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(bad))

        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        result = critique_diagram_ir(ir, "# Method\nX", "model_arch", mock_cfg)
        assert result["verdict"] == "acceptable"
        assert result["issues"] == []
        assert result["suggestions"] == []


class TestRefineDiagramIr:
    def test_returns_refined_ir(self, mock_cfg, monkeypatch):
        refined = {
            "title": "Better",
            "nodes": [{"id": "n1", "label": "N1", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "vertical",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(refined))

        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        critique = {
            "verdict": "needs_revision",
            "issues": [{"aspect": "completeness", "description": "Missing node", "severity": "major"}],
        }
        result = refine_diagram_ir(ir, critique, "# Method\nX", "model_arch", mock_cfg)
        assert result["title"] == "Better"
        assert len(result["nodes"]) == 1

    def test_raises_on_invalid_refined_ir(self, mock_cfg, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps({"title": "Bad", "nodes": "oops"})
        )

        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        critique = {"verdict": "needs_revision", "issues": []}
        with pytest.raises(ValueError, match="IR 格式不正确"):
            refine_diagram_ir(ir, critique, "# Method\nX", "model_arch", mock_cfg)


class TestGenerateDiagramWithCritic:
    def test_single_round_acceptable(self, tmp_paper_dir, mock_cfg, monkeypatch, tmp_path):
        ir = {
            "title": "EncDec",
            "nodes": [{"id": "n1", "label": "N1", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        critique = {"round": 1, "verdict": "acceptable", "issues": [], "suggestions": []}

        monkeypatch.setattr(
            "scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir if "可视化专家" in p else critique)
        )

        result = generate_diagram_with_critic(
            tmp_paper_dir, "model_arch", "dot", mock_cfg, out_dir=tmp_path, max_rounds=3
        )
        assert result["out_path"].suffix == ".dot"
        assert len(result["critique_log"]) == 1
        assert result["critique_log"][0]["verdict"] == "acceptable"

    def test_multi_round_then_acceptable(self, tmp_paper_dir, mock_cfg, monkeypatch, tmp_path):
        ir_v1 = {
            "title": "EncDec",
            "nodes": [{"id": "n1", "label": "N1", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        ir_v2 = {
            "title": "EncDecV2",
            "nodes": [
                {"id": "n1", "label": "N1", "type": "module", "layer": 1},
                {"id": "n2", "label": "N2", "type": "module", "layer": 2},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
            "layout_hint": "horizontal",
        }
        critique_revise = {
            "round": 1,
            "verdict": "needs_revision",
            "issues": [{"aspect": "completeness", "description": "Missing n2", "severity": "major"}],
            "suggestions": ["Add n2"],
        }
        critique_ok = {"round": 2, "verdict": "acceptable", "issues": [], "suggestions": []}

        calls = []

        def fake_llm(prompt, cfg, **kw):
            calls.append(prompt)
            if "根据审稿反馈，修正" in prompt:
                return json.dumps(ir_v2)
            if "第 1 轮审查" in prompt:
                return json.dumps(critique_revise)
            if "第 2 轮审查" in prompt:
                return json.dumps(critique_ok)
            return json.dumps(ir_v1)

        monkeypatch.setattr("scholaraio.diagram._call_llm", fake_llm)

        result = generate_diagram_with_critic(
            tmp_paper_dir, "model_arch", "dot", mock_cfg, out_dir=tmp_path, max_rounds=3
        )
        assert result["out_path"].exists()
        assert len(result["critique_log"]) == 2
        assert result["critique_log"][0]["verdict"] == "needs_revision"
        assert result["critique_log"][1]["verdict"] == "acceptable"
        assert len(result["ir"]["nodes"]) == 2

    def test_dump_ir_with_critic(self, tmp_paper_dir, mock_cfg, monkeypatch, tmp_path):
        ir = {"title": "DumpCritic", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        critique = {"round": 1, "verdict": "acceptable", "issues": [], "suggestions": []}
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps(ir if "可视化专家" in p or "根据审稿反馈" in p else critique),
        )

        result = generate_diagram_with_critic(
            tmp_paper_dir, "model_arch", "dot", mock_cfg, out_dir=tmp_path, dump_ir=True, max_rounds=3
        )
        assert result["out_path"].suffix == ".json"
        data = json.loads(result["out_path"].read_text(encoding="utf-8"))
        assert data["title"] == "DumpCritic"


class TestCliDiagramCritic:
    def test_cli_with_critic_flag(self, capture_ui, cfg, paper_dir, monkeypatch):
        ir = {
            "title": "CLI Critic",
            "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        critique = {"round": 1, "verdict": "acceptable", "issues": [], "suggestions": []}
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps(ir if "可视化专家" in p or "提取并结构化" in p else critique),
        )
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="model_arch",
            format="dot",
            output=None,
            dump_ir=False,
            from_ir=None,
            critic=True,
            critic_rounds=2,
        )
        cli.cmd_diagram(args, cfg)
        assert any("已生成:" in m for m in capture_ui)
        assert any("Critic 闭环完成" in m for m in capture_ui)


# ---------------------------------------------------------------------------
# 边界情况补充
# ---------------------------------------------------------------------------


class TestExtractDiagramIrFromText:
    def test_successful_extraction_from_text(self, mock_cfg, monkeypatch):
        expected_ir = {
            "title": "Pipeline",
            "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(expected_ir))

        ir = extract_diagram_ir_from_text("We use a simple pipeline.", "tech_route", mock_cfg)
        assert ir["title"] == "Pipeline"
        assert ir["nodes"][0]["id"] == "a"

    def test_unsupported_diagram_type_from_text(self, mock_cfg):
        with pytest.raises(ValueError, match="不支持的 diagram 类型"):
            extract_diagram_ir_from_text("X", "unknown_type", mock_cfg)

    def test_invalid_llm_response_raises_from_text(self, mock_cfg, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps({"title": "Bad", "nodes": "oops"})
        )
        with pytest.raises(ValueError, match="IR 格式不正确"):
            extract_diagram_ir_from_text("X", "model_arch", mock_cfg)


class TestGenerateDiagramFromText:
    def test_full_pipeline_to_dot(self, mock_cfg, monkeypatch, tmp_path):
        expected_ir = {
            "title": "TextDiagram",
            "nodes": [{"id": "n1", "label": "N1", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(expected_ir))

        out = generate_diagram_from_text("We use a module.", "model_arch", "dot", mock_cfg, out_dir=tmp_path)
        assert isinstance(out, Path)
        assert out.suffix == ".dot"
        assert "TextDiagram" in out.read_text(encoding="utf-8")
        assert "from_text" in out.name

    def test_dump_ir_from_text(self, mock_cfg, monkeypatch, tmp_path):
        expected_ir = {
            "title": "IR-Only",
            "nodes": [],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(expected_ir))

        out = generate_diagram_from_text("Empty.", "model_arch", "dot", mock_cfg, out_dir=tmp_path, dump_ir=True)
        assert out.suffix == ".json"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["title"] == "IR-Only"


class TestExtractMethodSectionEdgeCases:
    def test_empty_markdown(self):
        assert _extract_method_section("", max_chars=100) == ""

    def test_multiple_matching_headers_uses_first(self):
        md = "# Method\nFirst.\n\n# Methodology\nSecond.\n\n# Results\nNope."
        section = _extract_method_section(md, max_chars=500)
        assert "First." in section
        assert "Second." not in section

    def test_header_with_no_content(self):
        md = "# Method\n# Results\nSome results."
        section = _extract_method_section(md, max_chars=500)
        assert "Method" in section
        assert "Results" not in section

    def test_case_insensitive_match(self):
        for header in ["# METHOD", "# mEtHoD", "# Architecture"]:
            md = f"{header}\nContent.\n\n# Results\nNope."
            section = _extract_method_section(md, max_chars=500)
            assert "Content." in section


class TestRenderIrEdgeCases:
    def test_empty_ir_all_backends(self, tmp_path):
        empty_ir = {"title": "Empty", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        for fmt in ["dot", "mermaid", "drawio"]:
            out = render_ir(empty_ir, fmt, out_path=tmp_path / f"empty.{fmt}")
            assert out.exists()
            text = out.read_text(encoding="utf-8")
            assert text  # non-empty output

    def test_unicode_labels(self, tmp_path):
        ir = {
            "title": "中文标题",
            "nodes": [{"id": "a", "label": "输入数据", "type": "data", "layer": 1}],
            "edges": [{"from": "a", "to": "a", "label": "特征向量", "style": "solid"}],
            "layout_hint": "horizontal",
        }
        for fmt in ["dot", "mermaid", "drawio"]:
            out = render_ir(ir, fmt, out_path=tmp_path / f"unicode.{fmt}")
            text = out.read_text(encoding="utf-8")
            assert "输入数据" in text
            assert "特征向量" in text

    def test_unknown_layout_hint_defaults_to_vertical(self, tmp_path):
        ir = {
            "title": "T",
            "nodes": [{"id": "a", "label": "A"}],
            "edges": [],
            "layout_hint": "unknown",
        }
        dot_text = render_ir(ir, "dot", out_path=tmp_path / "x.dot").read_text(encoding="utf-8")
        assert "rankdir=TB" in dot_text
        mmd_text = render_ir(ir, "mermaid", out_path=tmp_path / "x.mmd").read_text(encoding="utf-8")
        assert "flowchart TD" in mmd_text


class TestGenerateDiagramEdgeCases:
    def test_nested_out_dir_auto_created(self, tmp_paper_dir, mock_cfg, monkeypatch, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps({"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}),
        )
        out = generate_diagram(tmp_paper_dir, "model_arch", "dot", mock_cfg, out_dir=nested)
        assert nested.exists()
        assert out.parent == nested

    def test_long_title_truncated_to_40(self, tmp_paper_dir, mock_cfg, monkeypatch, tmp_path):
        long_title = "A" * 100
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps({"title": long_title, "nodes": [], "edges": [], "layout_hint": "horizontal"}),
        )
        out = generate_diagram(tmp_paper_dir, "model_arch", "dot", mock_cfg, out_dir=tmp_path)
        safe_part = out.stem.split("_")[-1]
        assert len(safe_part) <= 40
