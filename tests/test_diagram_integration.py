"""Integration tests for the diagram pipeline.

End-to-end validation of extraction, rendering, Critic loop, and cross-backend
consistency using realistic mock LLM responses.
"""

from __future__ import annotations

import json
import shutil
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scholaraio import cli
from scholaraio.config import Config
from scholaraio.diagram import (
    generate_diagram,
    generate_diagram_with_critic,
    render_ir,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg(tmp_path: Path) -> Config:
    return Config(_root=tmp_path)


@pytest.fixture()
def encoder_decoder_paper(tmp_path: Path) -> Path:
    """A realistic paper directory with encoder-decoder content."""
    paper_dir = tmp_path / "Smith-2024-AutoEncoder"
    paper_dir.mkdir()
    (paper_dir / "meta.json").write_text(
        json.dumps({"id": "uuid-1234", "title": "AutoEncoder for Images", "year": 2024}),
        encoding="utf-8",
    )
    md = (
        "# Introduction\n"
        "Image compression is important.\n\n"
        "# Method\n"
        "We propose a convolutional auto-encoder.\n\n"
        "## Encoder\n"
        "The encoder consists of three convolutional layers followed by batch normalization "
        "and ReLU activation. The output is a latent vector $z$.\n\n"
        "## Decoder\n"
        "The decoder mirrors the encoder with three transposed convolutional layers.\n\n"
        "## Loss Function\n"
        "We minimize the MSE between input and reconstructed output.\n\n"
        "# Experiments\n"
        "We evaluate on CIFAR-10.\n"
    )
    (paper_dir / "paper.md").write_text(md, encoding="utf-8")
    return paper_dir


@pytest.fixture()
def realistic_ir() -> dict:
    return {
        "title": "Convolutional Auto-Encoder Architecture",
        "nodes": [
            {"id": "input", "label": "Input Image", "type": "data", "layer": 1},
            {"id": "conv1", "label": "Conv Layer 1", "type": "module", "layer": 2},
            {"id": "bn1", "label": "Batch Norm", "type": "operation", "layer": 2},
            {"id": "relu1", "label": "ReLU", "type": "operation", "layer": 2},
            {"id": "conv2", "label": "Conv Layer 2", "type": "module", "layer": 2},
            {"id": "bn2", "label": "Batch Norm", "type": "operation", "layer": 2},
            {"id": "relu2", "label": "ReLU", "type": "operation", "layer": 2},
            {"id": "conv3", "label": "Conv Layer 3", "type": "module", "layer": 2},
            {"id": "latent", "label": "Latent Vector z", "type": "data", "layer": 3},
            {"id": "tconv3", "label": "Transposed Conv 3", "type": "module", "layer": 4},
            {"id": "tconv2", "label": "Transposed Conv 2", "type": "module", "layer": 4},
            {"id": "tconv1", "label": "Transposed Conv 1", "type": "module", "layer": 4},
            {"id": "output", "label": "Reconstructed Image", "type": "data", "layer": 5},
            {"id": "loss", "label": "MSE Loss", "type": "operation", "layer": 5},
        ],
        "edges": [
            {"from": "input", "to": "conv1", "label": "", "style": "solid"},
            {"from": "conv1", "to": "bn1", "label": "", "style": "solid"},
            {"from": "bn1", "to": "relu1", "label": "", "style": "solid"},
            {"from": "relu1", "to": "conv2", "label": "", "style": "solid"},
            {"from": "conv2", "to": "bn2", "label": "", "style": "solid"},
            {"from": "bn2", "to": "relu2", "label": "", "style": "solid"},
            {"from": "relu2", "to": "conv3", "label": "", "style": "solid"},
            {"from": "conv3", "to": "latent", "label": "z", "style": "dashed"},
            {"from": "latent", "to": "tconv3", "label": "", "style": "solid"},
            {"from": "tconv3", "to": "tconv2", "label": "", "style": "solid"},
            {"from": "tconv2", "to": "tconv1", "label": "", "style": "solid"},
            {"from": "tconv1", "to": "output", "label": "", "style": "solid"},
            {"from": "output", "to": "loss", "label": "", "style": "dashed"},
        ],
        "layout_hint": "vertical",
    }


# ---------------------------------------------------------------------------
# End-to-end pipeline integration
# ---------------------------------------------------------------------------


class TestEndToEndPipeline:
    def test_generate_diagram_all_formats(self, encoder_decoder_paper, cfg, monkeypatch, tmp_path):
        ir = {
            "title": "AE",
            "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir))

        for fmt in ["dot", "mermaid", "drawio"]:
            out = generate_diagram(encoder_decoder_paper, "model_arch", fmt, cfg, out_dir=tmp_path / fmt)
            assert isinstance(out, Path)
            assert out.exists()
            assert out.suffix == f".{fmt}"
            assert out.stat().st_size > 0

        # SVG requires graphviz dot
        if shutil.which("dot"):
            out = generate_diagram(encoder_decoder_paper, "model_arch", "svg", cfg, out_dir=tmp_path / "svg")
            assert out.exists()
            assert out.suffix == ".svg"
            # DOT source is also preserved
            assert out.with_suffix(".dot").exists()

    def test_generate_diagram_with_critic_produces_final_only(self, encoder_decoder_paper, cfg, monkeypatch, tmp_path):
        ir = {
            "title": "AE",
            "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        critique = {"round": 1, "verdict": "acceptable", "issues": [], "suggestions": []}
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps(ir if "可视化专家" in p or "提取并结构化" in p else critique),
        )
        result = generate_diagram_with_critic(
            encoder_decoder_paper, "model_arch", "dot", cfg, out_dir=tmp_path, max_rounds=3
        )
        final = result["out_path"]
        assert final.exists()
        # No intermediate _rN files should remain
        assert not any("_r" in f.name for f in tmp_path.iterdir())

    def test_dump_ir_then_from_ir_roundtrip(self, encoder_decoder_paper, cfg, monkeypatch, tmp_path):
        ir = {
            "title": "RoundTrip",
            "nodes": [{"id": "n1", "label": "N1", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir))

        ir_path = generate_diagram(encoder_decoder_paper, "model_arch", "dot", cfg, out_dir=tmp_path, dump_ir=True)
        assert ir_path.suffix == ".json"
        loaded = json.loads(ir_path.read_text(encoding="utf-8"))
        assert loaded["title"] == "RoundTrip"

        # Render from IR to mermaid
        out = render_ir(loaded, "mermaid", out_path=tmp_path / "roundtrip.mmd")
        text = out.read_text(encoding="utf-8")
        assert "flowchart" in text
        assert "N1" in text

    def test_critic_loop_with_realistic_multi_round(self, encoder_decoder_paper, cfg, monkeypatch, tmp_path):
        ir_v1 = {
            "title": "AE",
            "nodes": [
                {"id": "enc", "label": "Encoder", "type": "module", "layer": 1},
                {"id": "latent", "label": "Latent", "type": "data", "layer": 2},
            ],
            "edges": [{"from": "enc", "to": "latent", "label": "z", "style": "solid"}],
            "layout_hint": "horizontal",
        }
        ir_v2 = {
            "title": "AE",
            "nodes": [
                {"id": "input", "label": "Input", "type": "data", "layer": 1},
                {"id": "enc", "label": "Encoder", "type": "module", "layer": 2},
                {"id": "latent", "label": "Latent", "type": "data", "layer": 3},
                {"id": "dec", "label": "Decoder", "type": "module", "layer": 4},
                {"id": "out", "label": "Output", "type": "data", "layer": 5},
            ],
            "edges": [
                {"from": "input", "to": "enc", "label": "", "style": "solid"},
                {"from": "enc", "to": "latent", "label": "z", "style": "solid"},
                {"from": "latent", "to": "dec", "label": "", "style": "solid"},
                {"from": "dec", "to": "out", "label": "", "style": "solid"},
            ],
            "layout_hint": "horizontal",
        }
        critique_r1 = {
            "round": 1,
            "verdict": "needs_revision",
            "issues": [
                {
                    "aspect": "completeness",
                    "description": "Missing input, decoder and output nodes",
                    "severity": "major",
                }
            ],
            "suggestions": ["Add full pipeline nodes"],
        }
        critique_r2 = {"round": 2, "verdict": "acceptable", "issues": [], "suggestions": []}

        def fake_llm(prompt, c, **kw):
            if "根据审稿反馈，修正" in prompt:
                return json.dumps(ir_v2)
            if "第 1 轮审查" in prompt:
                return json.dumps(critique_r1)
            if "第 2 轮审查" in prompt:
                return json.dumps(critique_r2)
            return json.dumps(ir_v1)

        monkeypatch.setattr("scholaraio.diagram._call_llm", fake_llm)
        result = generate_diagram_with_critic(
            encoder_decoder_paper, "model_arch", "dot", cfg, out_dir=tmp_path, max_rounds=3
        )

        assert len(result["critique_log"]) == 2
        assert result["ir"]["nodes"][0]["id"] == "input"
        assert len(result["ir"]["nodes"]) == 5
        assert result["out_path"].exists()


# ---------------------------------------------------------------------------
# Cross-backend consistency
# ---------------------------------------------------------------------------


class TestCrossBackendConsistency:
    def test_all_backends_preserve_node_and_edge_count(self, realistic_ir, tmp_path):
        formats = ["dot", "mermaid", "drawio"]
        if shutil.which("dot"):
            formats.append("svg")

        for fmt in formats:
            out = render_ir(realistic_ir, fmt, out_path=tmp_path / f"cross.{fmt}")
            assert out.exists()

        # DOT: count node declarations and edge arrows
        dot_text = (tmp_path / "cross.dot").read_text(encoding="utf-8")
        node_lines = [l for l in dot_text.splitlines() if " [label=" in l and "->" not in l]
        edge_lines = [l for l in dot_text.splitlines() if "->" in l]
        assert len(node_lines) == len(realistic_ir["nodes"])
        assert len(edge_lines) == len(realistic_ir["edges"])

        # Mermaid: count node declarations and arrows
        mmd_text = (tmp_path / "cross.mermaid").read_text(encoding="utf-8")
        mermaid_edge_tokens = ("-->", "-.->", "==>")
        mermaid_nodes = [
            l
            for l in mmd_text.splitlines()
            if not l.startswith("flowchart") and not any(token in l for token in mermaid_edge_tokens) and l.strip()
        ]
        mermaid_edges = [l for l in mmd_text.splitlines() if any(token in l for token in mermaid_edge_tokens)]
        assert len(mermaid_nodes) == len(realistic_ir["nodes"])
        assert len(mermaid_edges) == len(realistic_ir["edges"])

        # drawio: count mxCell vertex and edge entries
        drawio_text = (tmp_path / "cross.drawio").read_text(encoding="utf-8")
        vertex_cells = drawio_text.count('vertex="1"')
        edge_cells = drawio_text.count('edge="1"')
        assert vertex_cells == len(realistic_ir["nodes"])
        assert edge_cells == len(realistic_ir["edges"])

    def test_layout_hint_respected_across_backends(self, tmp_path):
        ir_lr = {"title": "LR", "nodes": [{"id": "a", "label": "A"}], "edges": [], "layout_hint": "horizontal"}
        ir_tb = {"title": "TB", "nodes": [{"id": "a", "label": "A"}], "edges": [], "layout_hint": "vertical"}

        dot_lr = render_ir(ir_lr, "dot", out_path=tmp_path / "lr.dot").read_text(encoding="utf-8")
        dot_tb = render_ir(ir_tb, "dot", out_path=tmp_path / "tb.dot").read_text(encoding="utf-8")
        assert "rankdir=LR" in dot_lr
        assert "rankdir=TB" in dot_tb

        mmd_lr = render_ir(ir_lr, "mermaid", out_path=tmp_path / "lr.mmd").read_text(encoding="utf-8")
        mmd_tb = render_ir(ir_tb, "mermaid", out_path=tmp_path / "tb.mmd").read_text(encoding="utf-8")
        assert "flowchart LR" in mmd_lr
        assert "flowchart TD" in mmd_tb


# ---------------------------------------------------------------------------
# CLI integration
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
    (d / "paper.md").write_text("# Method\nWe use an auto-encoder.\n", encoding="utf-8")
    return d


class TestCliIntegration:
    def test_cli_critic_with_all_formats(self, capture_ui, cli_cfg, cli_paper_dir, monkeypatch):
        ir = {
            "title": "AE",
            "nodes": [{"id": "a", "label": "A", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        critique = {"round": 1, "verdict": "acceptable", "issues": [], "suggestions": []}
        monkeypatch.setattr(
            "scholaraio.diagram._call_llm",
            lambda p, c, **kw: json.dumps(ir if "可视化专家" in p or "提取并结构化" in p else critique),
        )
        for fmt in ["dot", "mermaid", "drawio"]:
            capture_ui.clear()
            args = Namespace(
                paper_id="Test-2024-Paper",
                type="model_arch",
                format=fmt,
                output=None,
                dump_ir=False,
                from_ir=None,
                critic=True,
                critic_rounds=2,
            )
            cli.cmd_diagram(args, cli_cfg)
            assert any("已生成:" in m for m in capture_ui)
            assert any("Critic 闭环完成" in m for m in capture_ui)

    def test_cli_dump_ir_then_from_ir(self, capture_ui, cli_cfg, cli_paper_dir, monkeypatch, tmp_path):
        ir = {
            "title": "CLI RoundTrip",
            "nodes": [{"id": "x", "label": "X", "type": "data", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir))

        # Step 1: dump IR
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="model_arch",
            format="dot",
            output=str(tmp_path),
            dump_ir=True,
            from_ir=None,
            critic=False,
            critic_rounds=3,
        )
        cli.cmd_diagram(args, cli_cfg)
        ir_path = tmp_path / "Test-2024-Paper_model_arch_CLI_RoundTrip.ir.json"
        assert ir_path.exists()

        # Step 2: render from IR to drawio
        capture_ui.clear()
        args2 = Namespace(
            paper_id=None,
            type="model_arch",
            format="drawio",
            output=str(tmp_path),
            dump_ir=False,
            from_ir=str(ir_path),
            critic=False,
            critic_rounds=3,
        )
        cli.cmd_diagram(args2, None)
        assert any("已生成:" in m for m in capture_ui)
        drawio_path = tmp_path / "diagram_CLI_RoundTrip.drawio"
        assert drawio_path.exists()
        assert "mxGraphModel" in drawio_path.read_text(encoding="utf-8")

    def test_cli_with_type_tech_route(self, capture_ui, cli_cfg, cli_paper_dir, monkeypatch):
        ir = {
            "title": "Flow",
            "nodes": [{"id": "s1", "label": "Step 1", "type": "module", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir))
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="tech_route",
            format="mermaid",
            output=None,
            dump_ir=False,
            from_ir=None,
            critic=False,
            critic_rounds=3,
        )
        cli.cmd_diagram(args, cli_cfg)
        assert any("已生成:" in m for m in capture_ui)

    def test_cli_with_type_exp_setup(self, capture_ui, cli_cfg, cli_paper_dir, monkeypatch):
        ir = {
            "title": "Setup",
            "nodes": [{"id": "ds", "label": "Dataset", "type": "data", "layer": 1}],
            "edges": [],
            "layout_hint": "horizontal",
        }
        monkeypatch.setattr("scholaraio.diagram._call_llm", lambda p, c, **kw: json.dumps(ir))
        args = Namespace(
            paper_id="Test-2024-Paper",
            type="exp_setup",
            format="dot",
            output=None,
            dump_ir=False,
            from_ir=None,
            critic=False,
            critic_rounds=3,
        )
        cli.cmd_diagram(args, cli_cfg)
        assert any("已生成:" in m for m in capture_ui)
