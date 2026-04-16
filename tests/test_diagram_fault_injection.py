"""Fault-injection tests for the diagram pipeline.

Covers LLM failures, malformed JSON, rendering errors, Critic-loop edge cases,
IO failures, and orphan-edge handling.
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scholaraio import cli
from scholaraio.config import Config
from scholaraio.diagram import (
    _call_llm,
    _extract_method_section,
    _parse_json,
    critique_diagram_ir,
    extract_diagram_ir,
    generate_diagram,
    generate_diagram_with_critic,
    refine_diagram_ir,
    render_ir,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg(tmp_path: Path) -> Config:
    return Config(_root=tmp_path)


@pytest.fixture()
def tmp_paper_dir(tmp_path: Path) -> Path:
    paper_dir = tmp_path / "Test-2024-Paper"
    paper_dir.mkdir()
    (paper_dir / "meta.json").write_text(json.dumps({"id": "test-uuid"}), encoding="utf-8")
    (paper_dir / "paper.md").write_text(
        "# Method\nWe propose an encoder-decoder architecture.\n\n"
        "## Encoder\nThe encoder takes input.\n\n"
        "## Decoder\nThe decoder reconstructs output.\n",
        encoding="utf-8",
    )
    return paper_dir


@pytest.fixture()
def complex_ir() -> dict:
    return {
        "title": 'Test "Special" <Model>',
        "nodes": [
            {"id": "input", "label": "Input Data", "type": "data", "layer": 1},
            {"id": "enc", "label": "Encoder Module", "type": "module", "layer": 2},
            {"id": "op", "label": "Pre-process", "type": "operation", "layer": 2},
            {"id": "gate", "label": "Gate?", "type": "decision", "layer": 3},
            {"id": "out", "label": "Output", "type": "data", "layer": 3},
        ],
        "edges": [
            {"from": "input", "to": "enc", "label": "x", "style": "solid"},
            {"from": "input", "to": "op", "label": "x'", "style": "dashed"},
            {"from": "enc", "to": "gate", "label": "z", "style": "dashed"},
            {"from": "op", "to": "gate", "label": "z'", "style": "bold"},
            {"from": "gate", "to": "out", "label": "yes", "style": "bold"},
        ],
        "layout_hint": "horizontal",
    }


# ---------------------------------------------------------------------------
# _extract_method_section fault injection
# ---------------------------------------------------------------------------


class TestExtractMethodSectionFaults:
    def test_empty_markdown(self):
        assert _extract_method_section("", max_chars=100) == ""

    def test_multiple_matching_headers_uses_first(self):
        md = "# Method\nFirst.\n\n# Methodology\nSecond.\n\n# Results\nNope."
        section = _extract_method_section(md, max_chars=500)
        assert "First." in section
        assert "Second." not in section
        assert "Results" not in section

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


# ---------------------------------------------------------------------------
# _parse_json fault injection
# ---------------------------------------------------------------------------


class TestParseJsonFaults:
    def test_completely_non_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json("this is not json at all")

    def test_nested_code_fence(self):
        # Inner code fence is left as literal text after outer stripping,
        # so the parser sees the inner fence markers and fails.
        raw = '```json\n```json\n{"a": 1}\n```\n```'
        with pytest.raises(json.JSONDecodeError):
            _parse_json(raw)

    def test_trailing_garbage_after_json(self):
        raw = '{"a": 1}\n\nSome extra text'
        with pytest.raises(json.JSONDecodeError):
            _parse_json(raw)

    def test_unicode_and_escaped_quotes(self):
        raw = '{"title": "\\"引用\\" \\u4e2d\\u6587"}'
        result = _parse_json(raw)
        assert result["title"] == '"引用" 中文'


# ---------------------------------------------------------------------------
# LLM-layer fault injection
# ---------------------------------------------------------------------------


class TestLlmLayerFaults:
    def test_call_llm_exception_propagates(self, cfg, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("LLM service down")

        monkeypatch.setattr("scholaraio.metrics.call_llm", boom)
        with pytest.raises(RuntimeError, match="LLM service down"):
            _call_llm("prompt", cfg)

    def test_extract_diagram_ir_raises_on_llm_exception(self, cfg, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm", lambda p, c, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with pytest.raises(RuntimeError, match="boom"):
            extract_diagram_ir("# Method\nX", "model_arch", cfg)

    def test_extract_diagram_ir_raises_on_non_json_llm_output(self, cfg, monkeypatch):
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: "not json")
        with pytest.raises(json.JSONDecodeError):
            extract_diagram_ir("# Method\nX", "model_arch", cfg)

    def test_extract_diagram_ir_raises_when_nodes_is_not_list(self, cfg, monkeypatch):
        bad = {"title": "T", "nodes": "oops", "edges": []}
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(bad))
        with pytest.raises(ValueError, match="IR 格式不正确"):
            extract_diagram_ir("# Method\nX", "model_arch", cfg)

    def test_extract_diagram_ir_raises_when_edges_is_not_list(self, cfg, monkeypatch):
        bad = {"title": "T", "nodes": [], "edges": {"a": "b"}}
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(bad))
        with pytest.raises(ValueError, match="IR 格式不正确"):
            extract_diagram_ir("# Method\nX", "model_arch", cfg)

    def test_critique_diagram_ir_raises_on_llm_exception(self, cfg, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm", lambda p, c, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        with pytest.raises(RuntimeError, match="boom"):
            critique_diagram_ir(ir, "# Method\nX", "model_arch", cfg)

    def test_refine_diagram_ir_raises_on_llm_exception(self, cfg, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm", lambda p, c, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        critique = {"verdict": "needs_revision", "issues": []}
        with pytest.raises(RuntimeError, match="boom"):
            refine_diagram_ir(ir, critique, "# Method\nX", "model_arch", cfg)


# ---------------------------------------------------------------------------
# Renderer fault injection
# ---------------------------------------------------------------------------


class TestRendererFaults:
    def test_dot_with_empty_ir(self, tmp_path):
        empty_ir = {"title": "Empty", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        out = tmp_path / "empty.dot"
        result = render_ir(empty_ir, "dot", out_path=out)
        text = result.read_text(encoding="utf-8")
        assert "digraph G {" in text
        assert "}" in text

    def test_svg_without_dot_command(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram.subprocess.run",
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("dot not found")),
        )
        ir = {"title": "T", "nodes": [{"id": "a", "label": "A"}], "edges": [], "layout_hint": "horizontal"}
        out = tmp_path / "x.svg"
        with pytest.raises(RuntimeError, match="未找到 graphviz"):
            render_ir(ir, "svg", out_path=out)

    def test_svg_with_dot_compile_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram.subprocess.run",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("dot compile failed")),
        )
        ir = {"title": "T", "nodes": [{"id": "a", "label": "A"}], "edges": [], "layout_hint": "horizontal"}
        out = tmp_path / "x.svg"
        with pytest.raises(RuntimeError, match="dot compile failed"):
            render_ir(ir, "svg", out_path=out)

    def test_drawio_escapes_xml_entities(self, tmp_path, complex_ir):
        complex_ir["nodes"][0]["label"] = 'A & B <C> "D"'
        out = tmp_path / "x.drawio"
        result = render_ir(complex_ir, "drawio", out_path=out)
        text = result.read_text(encoding="utf-8")
        assert "A &amp; B &lt;C&gt; &quot;D&quot;" in text
        assert "<mxCell" in text

    def test_drawio_skips_orphan_edges(self, tmp_path):
        ir = {
            "title": "Orphan",
            "nodes": [{"id": "a", "label": "A"}],
            "edges": [
                {"from": "a", "to": "b", "label": "orphan"},
                {"from": "b", "to": "a", "label": "orphan2"},
            ],
            "layout_hint": "horizontal",
        }
        out = tmp_path / "x.drawio"
        render_ir(ir, "drawio", out_path=out)
        text = out.read_text(encoding="utf-8")
        # No edge cells should be present because both reference missing nodes
        assert text.count('edge="1"') == 0

    def test_mermaid_with_special_chars_in_label(self, tmp_path):
        ir = {
            "title": "Special",
            "nodes": [{"id": "a", "label": "Line 1\nLine 2"}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        out = tmp_path / "x.mmd"
        result = render_ir(ir, "mermaid", out_path=out)
        text = result.read_text(encoding="utf-8")
        assert 'a["Line 1\nLine 2"]' in text

    def test_mermaid_escapes_quotes_in_label(self, tmp_path):
        ir = {
            "title": "Quoted",
            "nodes": [{"id": "a", "label": 'Module "A"'}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        out = tmp_path / "quoted.mmd"
        text = render_ir(ir, "mermaid", out_path=out).read_text(encoding="utf-8")
        assert 'Module "A"' not in text
        assert '\\"A\\"' in text

    def test_mermaid_sanitizes_unsafe_node_ids(self, tmp_path):
        ir = {
            "title": "Unsafe IDs",
            "nodes": [
                {"id": "encoder-1", "label": "Encoder"},
                {"id": "decoder 2", "label": "Decoder"},
            ],
            "edges": [{"from": "encoder-1", "to": "decoder 2", "label": "x", "style": "solid"}],
            "layout_hint": "horizontal",
        }
        out = tmp_path / "unsafe.mmd"
        text = render_ir(ir, "mermaid", out_path=out).read_text(encoding="utf-8")
        assert "encoder-1" not in text
        assert "decoder 2" not in text
        assert "encoder_1" in text
        assert "decoder_2" in text

    def test_dot_with_quotes_in_title_and_labels(self, tmp_path):
        ir = {
            "title": 'Say "Hello"',
            "nodes": [{"id": "a", "label": 'A "quoted" node'}],
            "edges": [{"from": "a", "to": "a", "label": 'an "edge"'}],
            "layout_hint": "horizontal",
        }
        out = tmp_path / "x.dot"
        text = render_ir(ir, "dot", out_path=out).read_text(encoding="utf-8")
        assert 'label="Say \\"Hello\\""' in text
        assert 'label="A \\"quoted\\" node"' in text
        assert 'label="an \\"edge\\""' in text

    def test_dot_quotes_unsafe_node_ids(self, tmp_path):
        ir = {
            "title": "Unsafe IDs",
            "nodes": [
                {"id": "encoder-1", "label": "Encoder"},
                {"id": "decoder 2", "label": "Decoder"},
            ],
            "edges": [{"from": "encoder-1", "to": "decoder 2", "label": "x", "style": "solid"}],
            "layout_hint": "horizontal",
        }
        out = tmp_path / "unsafe.dot"
        text = render_ir(ir, "dot", out_path=out).read_text(encoding="utf-8")
        assert '"encoder-1"' in text
        assert '"decoder 2"' in text
        assert '"encoder-1" -> "decoder 2"' in text


# ---------------------------------------------------------------------------
# Critic-loop fault injection
# ---------------------------------------------------------------------------


class TestCriticLoopFaults:
    def test_generate_diagram_with_critic_all_rounds_need_revision(self, tmp_paper_dir, cfg, monkeypatch, tmp_path):
        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        critique = {
            "round": 1,
            "verdict": "needs_revision",
            "issues": [{"aspect": "completeness", "description": "Missing", "severity": "major"}],
            "suggestions": [],
        }

        def fake_llm(prompt, c, **kw):
            if "提取并结构化" in prompt or "根据审稿反馈，修正" in prompt:
                return json.dumps(ir)
            return json.dumps(critique)

        monkeypatch.setattr("scholaraio.diagram._call_llm", fake_llm)
        result = generate_diagram_with_critic(tmp_paper_dir, "model_arch", "dot", cfg, out_dir=tmp_path, max_rounds=2)
        assert len(result["critique_log"]) == 2
        assert result["critique_log"][0]["verdict"] == "needs_revision"
        assert result["critique_log"][1]["verdict"] == "needs_revision"
        assert result["out_path"].exists()

    def test_generate_diagram_with_critic_refine_raises_keeps_last_valid(
        self, tmp_paper_dir, cfg, monkeypatch, tmp_path
    ):
        ir = {"title": "T", "nodes": [{"id": "a", "label": "A"}], "edges": [], "layout_hint": "horizontal"}
        critique = {"verdict": "needs_revision", "issues": [], "suggestions": []}
        calls = []

        def fake_llm(prompt, c, **kw):
            calls.append(prompt)
            if "根据审稿反馈，修正" in prompt:
                raise RuntimeError("refine failed")
            if "审查" in prompt:
                return json.dumps(critique)
            return json.dumps(ir)

        monkeypatch.setattr("scholaraio.diagram._call_llm", fake_llm)
        # round 1: extract -> render -> critique(needs_revision) -> refine(fails)
        # This should propagate the RuntimeError because refine_diagram_ir is not caught
        with pytest.raises(RuntimeError, match="refine failed"):
            generate_diagram_with_critic(tmp_paper_dir, "model_arch", "dot", cfg, out_dir=tmp_path, max_rounds=3)

    def test_critique_defensive_on_completely_malformed_response(self, cfg, monkeypatch):
        # Even though _parse_json would fail on "not json", we monkeypatch _call_llm
        # to return a string that _parse_json can handle but has wrong structure
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: '{"verdict": "weird", "issues": 123, "suggestions": null}',
        )
        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        result = critique_diagram_ir(ir, "# Method\nX", "model_arch", cfg)
        assert result["verdict"] == "acceptable"
        assert result["issues"] == []
        assert result["suggestions"] == []

    def test_generate_diagram_with_critic_zero_rounds(self, tmp_paper_dir, cfg, monkeypatch, tmp_path):
        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir))
        # max_rounds=0 falls back to a single render without critique
        result = generate_diagram_with_critic(tmp_paper_dir, "model_arch", "dot", cfg, out_dir=tmp_path, max_rounds=0)
        assert len(result["critique_log"]) == 0
        assert result["out_path"] is not None
        assert result["out_path"].exists()

    def test_generate_diagram_with_critic_svg_keeps_final_dot_and_cleans_round_dots(
        self, tmp_paper_dir, cfg, monkeypatch, tmp_path
    ):
        ir = {
            "title": "Critic SVG",
            "nodes": [{"id": "n1", "label": "A", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        critique = {"round": 1, "verdict": "acceptable", "issues": [], "suggestions": []}

        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps(ir if "可视化专家" in p or "提取并结构化" in p else critique),
        )
        monkeypatch.setattr(
            "scholaraio.diagram._dot_to_svg",
            lambda dot_text, svg_path: svg_path.write_text("<svg/>", encoding="utf-8"),
        )

        result = generate_diagram_with_critic(tmp_paper_dir, "model_arch", "svg", cfg, out_dir=tmp_path, max_rounds=1)
        final_svg = result["out_path"]
        final_dot = final_svg.with_suffix(".dot")

        assert final_svg.exists()
        assert final_dot.exists()
        assert not any("_r" in p.name and p.suffix == ".dot" for p in tmp_path.iterdir())


# ---------------------------------------------------------------------------
# generate_diagram / generate_diagram_with_critic IO faults
# ---------------------------------------------------------------------------


class TestIoFaults:
    def test_generate_diagram_missing_paper_md(self, cfg, monkeypatch, tmp_path):
        paper_d = tmp_path / "Missing-Paper"
        paper_d.mkdir()
        (paper_d / "meta.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")
        # Neither paper.md exists nor fallback
        monkeypatch.setattr(
            "scholaraio.papers.md_path",
            lambda papers_dir, dir_name: paper_d / "nonexistent.md",
        )
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps({"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}),
        )
        with pytest.raises(FileNotFoundError):
            generate_diagram(paper_d, "model_arch", "dot", cfg, out_dir=tmp_path)

    def test_generate_diagram_nested_out_dir_created(self, tmp_paper_dir, cfg, monkeypatch, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps({"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}),
        )
        out = generate_diagram(tmp_paper_dir, "model_arch", "dot", cfg, out_dir=nested)
        assert nested.exists()
        assert out.parent == nested

    def test_generate_diagram_long_title_truncated(self, tmp_paper_dir, cfg, monkeypatch, tmp_path):
        long_title = "A" * 100
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps({"title": long_title, "nodes": [], "edges": [], "layout_hint": "horizontal"}),
        )
        out = generate_diagram(tmp_paper_dir, "model_arch", "dot", cfg, out_dir=tmp_path)
        # Safe title is truncated to 40 chars
        assert len(out.stem.split("_")[-1]) <= 40

    def test_generate_diagram_with_critic_readonly_out_dir(self, tmp_paper_dir, cfg, monkeypatch, tmp_path):
        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir))

        def raise_permission(*args, **kwargs):
            raise PermissionError("read-only")

        monkeypatch.setattr(Path, "mkdir", raise_permission)
        with pytest.raises(PermissionError, match="read-only"):
            generate_diagram(tmp_paper_dir, "model_arch", "dot", cfg, out_dir=tmp_path / "nested")


# ---------------------------------------------------------------------------
# CLI fault injection
# ---------------------------------------------------------------------------


@pytest.fixture()
def capture_ui(monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", messages.append)
    return messages


@pytest.fixture()
def cli_cfg(tmp_path):
    return SimpleNamespace(papers_dir=tmp_path / "papers", index_db=tmp_path / "index.db")


@pytest.fixture()
def cli_paper_dir(cli_cfg):
    d = cli_cfg.papers_dir / "Test-2024-Paper"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": "test-uuid"}), encoding="utf-8")
    (d / "paper.md").write_text("# Method\nWe use X.\n", encoding="utf-8")
    return d


class TestCliFaults:
    def test_critic_with_dump_ir(self, capture_ui, cli_cfg, cli_paper_dir, monkeypatch):
        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        critique = {"round": 1, "verdict": "acceptable", "issues": [], "suggestions": []}
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps(ir if "可视化专家" in p or "提取并结构化" in p else critique),
        )
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="model_arch",
            format="svg",
            output=None,
            dump_ir=True,
            from_ir=None,
            critic=True,
            critic_rounds=2,
        )
        cli.cmd_diagram(args, cli_cfg)
        assert any("已生成:" in m for m in capture_ui)
        assert any("Critic 闭环完成" in m for m in capture_ui)
        out_msg = next(m for m in capture_ui if "已生成:" in m)
        assert out_msg.endswith(".ir.json")

    def test_from_ir_ignores_critic_flag(self, capture_ui, tmp_path):
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
            critic=True,
            critic_rounds=5,
        )
        cli.cmd_diagram(args, None)
        assert any("已生成:" in m for m in capture_ui)
        # Critic log should NOT be printed because from-ir bypasses critic
        assert not any("Critic 闭环完成" in m for m in capture_ui)

    def test_all_format_type_combinations(self, cli_cfg, cli_paper_dir, monkeypatch):
        ir = {
            "title": "Combo",
            "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir))
        for fmt in ["dot", "mermaid", "drawio"]:
            for dtype in ["model_arch", "tech_route", "exp_setup"]:
                args = Namespace(
                    paper_id="Test-2024-Paper",
                    type=dtype,
                    format=fmt,
                    output=None,
                    dump_ir=False,
                    from_ir=None,
                    critic=False,
                    critic_rounds=3,
                )
                cli.cmd_diagram(args, cli_cfg)

    def test_cli_critic_rounds_negative(self, capture_ui, cli_cfg, cli_paper_dir, monkeypatch):
        ir = {"title": "T", "nodes": [], "edges": [], "layout_hint": "horizontal"}
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir))
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="model_arch",
            format="dot",
            output=None,
            dump_ir=False,
            from_ir=None,
            critic=True,
            critic_rounds=-1,
        )
        cli.cmd_diagram(args, cli_cfg)
        # With max_rounds<=0, critic is bypassed; no critique log is printed
        assert not any("Critic 闭环完成" in m for m in capture_ui)
        assert any("已生成:" in m for m in capture_ui)

    def test_cli_svg_format_without_graphviz(self, cli_cfg, cli_paper_dir, monkeypatch):
        monkeypatch.setattr(
            "scholaraio.diagram.subprocess.run",
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("dot not found")),
        )
        ir = {
            "title": "T",
            "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir))
        monkeypatch.setattr(sys, "exit", MagicMock(side_effect=SystemExit(1)))
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
        with pytest.raises(SystemExit):
            cli.cmd_diagram(args, cli_cfg)
