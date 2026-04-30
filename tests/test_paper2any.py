"""Tests for Paper2Any handoff bundle generation."""

from __future__ import annotations

import json
import os
import subprocess
from argparse import Namespace
from pathlib import Path

from scholaraio.core.config import _build_config


def _write_paper(root: Path, *, with_pdf: bool = True) -> Path:
    paper = root / "Sample-2026-Paper2Any"
    paper.mkdir(parents=True)
    (paper / "meta.json").write_text(
        json.dumps(
            {
                "id": "paper-uuid",
                "title": "Paper2Any Integration Smoke",
                "authors": ["Scholar AIO"],
                "year": 2026,
            }
        ),
        encoding="utf-8",
    )
    (paper / "paper.md").write_text("# Paper2Any Integration Smoke\n\nBody text.\n", encoding="utf-8")
    if with_pdf:
        (paper / "paper.pdf").write_bytes(b"%PDF-smoke")
    return paper


def test_prepare_paper2any_bundle_prefers_pdf_and_writes_manifest(tmp_path: Path) -> None:
    from scholaraio.services.paper2any import prepare_paper2any_bundle

    cfg = _build_config({}, tmp_path)
    paper = _write_paper(tmp_path / "data" / "libraries" / "papers")

    result = prepare_paper2any_bundle(
        paper,
        cfg,
        task="figure",
        graph_type="tech_route",
        out_dir=tmp_path / "bundles",
        paper2any_root="/opt/Paper2Any",
    )

    assert result.input_path.name == "paper.pdf"
    assert result.input_path.read_bytes() == b"%PDF-smoke"
    assert result.output_dir == result.bundle_dir / "outputs"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["task"] == "figure"
    assert manifest["graph_type"] == "tech_route"
    assert manifest["paper"]["title"] == "Paper2Any Integration Smoke"
    assert manifest["paper2any_command"][:3] == ["python", "script/run_paper2figure_cli.py", "--input"]
    script = result.script_path.read_text(encoding="utf-8")
    assert 'PAPER2ANY_ROOT="${PAPER2ANY_ROOT:-/opt/Paper2Any}"' in script
    assert "script/run_paper2figure_cli.py" in script
    assert os.access(result.script_path, os.X_OK)


def test_prepare_paper2any_bundle_can_use_markdown_input(tmp_path: Path) -> None:
    from scholaraio.services.paper2any import prepare_paper2any_bundle

    cfg = _build_config({}, tmp_path)
    paper = _write_paper(tmp_path / "data" / "libraries" / "papers", with_pdf=False)

    result = prepare_paper2any_bundle(
        paper,
        cfg,
        task="figure",
        input_preference="markdown",
        out_dir=tmp_path / "bundles",
    )

    assert result.input_path.name == "paper.md"
    assert result.input_path.read_text(encoding="utf-8").startswith("# Paper2Any")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["input"]["kind"] == "markdown"
    assert manifest["input"]["paper2any_input_type"] == "TEXT"
    script = result.script_path.read_text(encoding="utf-8")
    assert 'PAPER2ANY_INPUT="$(cat "$INPUT_PATH")"' not in script
    assert 'Path(os.environ["INPUT_PATH"]).read_text' in script
    assert "runpy.run_module" in script
    assert "    'python'," not in script


def test_markdown_runner_passes_file_contents_inside_python_process(tmp_path: Path) -> None:
    from scholaraio.services.paper2any import prepare_paper2any_bundle

    cfg = _build_config({}, tmp_path)
    paper = _write_paper(tmp_path / "data" / "libraries" / "papers", with_pdf=False)
    markdown = "# Paper2Any Integration Smoke\n\n" + ("Body text.\n" * 2000)
    (paper / "paper.md").write_text(markdown, encoding="utf-8")
    paper2any_root = tmp_path / "Paper2Any"
    script_dir = paper2any_root / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "__init__.py").write_text("", encoding="utf-8")
    (script_dir / "run_paper2figure_cli.py").write_text(
        """
import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--input-type", required=True)
    parser.add_argument("--graph-type", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--api-key")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "received.json").write_text(
        json.dumps(
            {
                "input": args.input,
                "input_type": args.input_type,
                "graph_type": args.graph_type,
                "api_key": args.api_key,
            }
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
""".lstrip(),
        encoding="utf-8",
    )

    result = prepare_paper2any_bundle(
        paper,
        cfg,
        task="figure",
        input_preference="markdown",
        out_dir=tmp_path / "bundles",
        paper2any_root=paper2any_root,
    )

    subprocess.run([str(result.script_path), "--api-key", "fake-key"], check=True)

    received = json.loads((result.output_dir / "received.json").read_text(encoding="utf-8"))
    assert received == {
        "input": markdown,
        "input_type": "TEXT",
        "graph_type": "model_arch",
        "api_key": "fake-key",
    }


def test_cmd_paper2any_prepare_resolves_paper_and_reports_bundle(tmp_path: Path, monkeypatch) -> None:
    from scholaraio.interfaces.cli import compat as cli

    cfg = _build_config({"paths": {"papers_dir": "data/libraries/papers"}}, tmp_path)
    _write_paper(cfg.papers_dir)
    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", messages.append)

    cli.cmd_paper2any(
        Namespace(
            paper2any_action="prepare",
            paper_id="Sample-2026-Paper2Any",
            task="ppt",
            graph_type="model_arch",
            input_preference="auto",
            out_dir=None,
            paper2any_root=None,
            page_count=12,
            language="en",
            style="Academic style",
        ),
        cfg,
    )

    bundle = cfg.workspace_dir / "_system" / "paper2any" / "Sample-2026-Paper2Any" / "ppt"
    assert (bundle / "paper2any.json").exists()
    assert (bundle / "run-paper2any.sh").exists()
    assert any("Paper2Any bundle" in message for message in messages)
