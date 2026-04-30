"""Tests for Paper2Any handoff bundle generation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


def _write_managed_python(root: Path) -> Path:
    venv_bin = "Scripts" if sys.platform == "win32" else "bin"
    python_name = "python.exe" if sys.platform == "win32" else "python"
    venv_python = root / ".venv" / venv_bin / python_name
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        shutil.copy2(sys.executable, venv_python)
    else:
        venv_python.symlink_to(sys.executable)
    venv_python.chmod(0o755)
    return venv_python


def _write_paper2any_scripts(root: Path) -> None:
    script_dir = root / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "run_paper2figure_cli.py",
        "run_paper2ppt_cli.py",
        "run_paper2ppt_frontend_cli.py",
        "run_pdf2ppt_cli.py",
        "run_image2ppt_cli.py",
        "run_ppt2polish_cli.py",
        "run_paper2poster_cli.py",
        "run_paper2video_cli.py",
    ):
        (script_dir / name).write_text("", encoding="utf-8")


def _write_paper2any_api(root: Path) -> None:
    app_dir = root / "fastapi_app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "main.py").write_text("app = object()\n", encoding="utf-8")


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
    assert 'PAPER2ANY_PYTHON="${PAPER2ANY_PYTHON:-$PAPER2ANY_ROOT/.venv/bin/python}"' in script
    assert '"$PAPER2ANY_PYTHON"' in script
    assert "script/run_paper2figure_cli.py" in script
    assert os.access(result.script_path, os.X_OK)


def test_generated_runner_redacts_upstream_api_keys_from_logs(tmp_path: Path) -> None:
    from scholaraio.services.paper2any import prepare_paper2any_bundle

    cfg = _build_config({}, tmp_path)
    paper = _write_paper(tmp_path / "data" / "libraries" / "papers")

    result = prepare_paper2any_bundle(
        paper,
        cfg,
        task="figure",
        out_dir=tmp_path / "bundles",
    )

    script = result.script_path.read_text(encoding="utf-8")
    assert "_redact_paper2any_output" in script
    assert "PIPESTATUS[0]" in script
    assert "API Key:" in script


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
    assert '"$PAPER2ANY_PYTHON" - "$@"' in script
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
    _write_managed_python(paper2any_root)

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


def test_pdf2ppt_bundle_uses_upstream_pdf2ppt_cli_arguments(tmp_path: Path) -> None:
    from scholaraio.services.paper2any import prepare_paper2any_bundle

    cfg = _build_config({}, tmp_path)
    paper = _write_paper(tmp_path / "data" / "libraries" / "papers")

    result = prepare_paper2any_bundle(
        paper,
        cfg,
        task="pdf2ppt",
        out_dir=tmp_path / "bundles",
        page_count=8,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["input"]["kind"] == "pdf"
    assert manifest["input"]["paper2any_input_type"] is None
    assert "--input-type" not in result.paper2any_command
    assert "--input-type" not in result.script_path.read_text(encoding="utf-8")


def test_ppt_bundle_uses_frontend_editable_cli_by_default(tmp_path: Path) -> None:
    from scholaraio.services.paper2any import prepare_paper2any_bundle

    cfg = _build_config({}, tmp_path)
    paper = _write_paper(tmp_path / "data" / "libraries" / "papers", with_pdf=False)

    result = prepare_paper2any_bundle(
        paper,
        cfg,
        task="ppt",
        input_preference="markdown",
        out_dir=tmp_path / "bundles",
        page_count=3,
    )

    assert "script/run_paper2ppt_frontend_cli.py" in result.paper2any_command
    assert "script/run_paper2ppt_cli.py" not in result.paper2any_command
    assert "--export-pptx" in result.paper2any_command
    script = result.script_path.read_text(encoding="utf-8")
    assert "script.run_paper2ppt_frontend_cli" in script
    assert "--export-pptx" in script


def test_prepare_supports_all_standalone_paper2any_cli_tasks(tmp_path: Path) -> None:
    from scholaraio.services.paper2any import prepare_paper2any_bundle
    from scholaraio.services.paper2any_runtime import PAPER2ANY_SCRIPTS

    cfg = _build_config({}, tmp_path)
    paper = _write_paper(tmp_path / "data" / "libraries" / "papers")
    image = tmp_path / "figure.png"
    image.write_bytes(b"png")
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"pptx")

    cases = [
        ("figure", None, "script/run_paper2figure_cli.py"),
        ("ppt", None, "script/run_paper2ppt_frontend_cli.py"),
        ("ppt-classic", None, "script/run_paper2ppt_cli.py"),
        ("pdf2ppt", None, "script/run_pdf2ppt_cli.py"),
        ("image2ppt", image, "script/run_image2ppt_cli.py"),
        ("ppt2polish", deck, "script/run_ppt2polish_cli.py"),
        ("poster", None, "script/run_paper2poster_cli.py"),
        ("video", None, "script/run_paper2video_cli.py"),
    ]

    for task, source_file, script in cases:
        result = prepare_paper2any_bundle(
            paper,
            cfg,
            task=task,
            source_file=source_file,
            out_dir=tmp_path / "bundles",
            page_count=4,
            language="en",
            style="Academic concise",
        )
        assert script in result.paper2any_command
        assert script in PAPER2ANY_SCRIPTS
        assert script in result.script_path.read_text(encoding="utf-8")
        assert result.bundle_dir.name == task


def test_source_file_tasks_copy_explicit_inputs_into_bundle(tmp_path: Path) -> None:
    from scholaraio.services.paper2any import prepare_paper2any_bundle

    cfg = _build_config({}, tmp_path)
    paper = _write_paper(tmp_path / "data" / "libraries" / "papers")
    image = tmp_path / "inputs" / "diagram.png"
    image.parent.mkdir()
    image.write_bytes(b"image bytes")

    result = prepare_paper2any_bundle(
        paper,
        cfg,
        task="image2ppt",
        source_file=image,
        out_dir=tmp_path / "bundles",
    )

    assert result.input_kind == "image"
    assert result.input_path == result.bundle_dir / "diagram.png"
    assert result.input_path.read_bytes() == b"image bytes"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["input"]["source_path"] == str(image.resolve())
    assert manifest["input"]["paper2any_input_type"] is None
    assert "--input-type" not in result.paper2any_command


def test_prepare_requires_source_file_for_image_and_polish_tasks(tmp_path: Path) -> None:
    from scholaraio.services.paper2any import prepare_paper2any_bundle

    cfg = _build_config({}, tmp_path)
    paper = _write_paper(tmp_path / "data" / "libraries" / "papers")

    for task in ("image2ppt", "ppt2polish"):
        try:
            prepare_paper2any_bundle(paper, cfg, task=task, out_dir=tmp_path / "bundles")
        except ValueError as e:
            assert "--source-file" in str(e)
        else:
            raise AssertionError(f"{task} should require --source-file")


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
            source_file=None,
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


def test_prepare_auto_uses_configured_paper2any_root(tmp_path: Path) -> None:
    from scholaraio.services.paper2any import prepare_paper2any_bundle

    paper2any_root = tmp_path / "data" / "runtime" / "extensions" / "paper2any" / "Paper2Any"
    (paper2any_root / "script").mkdir(parents=True)
    (paper2any_root / "script" / "run_paper2figure_cli.py").write_text("", encoding="utf-8")
    cfg = _build_config({"paper2any": {"root": str(paper2any_root)}}, tmp_path)
    paper = _write_paper(tmp_path / "data" / "libraries" / "papers")

    result = prepare_paper2any_bundle(paper, cfg, task="figure", out_dir=tmp_path / "bundles")

    script = result.script_path.read_text(encoding="utf-8")
    assert f'PAPER2ANY_ROOT="${{PAPER2ANY_ROOT:-{paper2any_root}}}"' in script
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["paper2any_root"] == str(paper2any_root)


def test_paper2any_status_reports_ready_managed_runtime(tmp_path: Path) -> None:
    from scholaraio.services.paper2any_runtime import check_paper2any_status

    root = tmp_path / "data" / "runtime" / "extensions" / "paper2any" / "Paper2Any"
    _write_paper2any_scripts(root)
    _write_paper2any_api(root)
    venv_bin = "Scripts" if sys.platform == "win32" else "bin"
    python_name = "python.exe" if sys.platform == "win32" else "python"
    venv_python = root / ".venv" / venv_bin / python_name
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    venv_python.chmod(0o755)

    cfg = _build_config({"paper2any": {"root": str(root)}}, tmp_path)
    status = check_paper2any_status(cfg)

    assert status.ready is True
    assert status.root == root.resolve()
    assert status.venv_python == venv_python
    assert status.missing == []


def test_paper2any_status_reports_missing_upstream_runtime_imports(tmp_path: Path, monkeypatch) -> None:
    from scholaraio.services.paper2any_runtime import check_paper2any_status

    root = tmp_path / "Paper2Any"
    _write_paper2any_scripts(root)
    _write_paper2any_api(root)
    (root / "pyproject.toml").write_text("[project]\nname='paper2any-smoke'\n", encoding="utf-8")
    _write_managed_python(root)
    cfg = _build_config({"paper2any": {"root": str(root)}}, tmp_path)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stderr="ModuleNotFoundError: No module named 'pptx'\n")

    monkeypatch.setattr("scholaraio.services.paper2any_runtime.subprocess.run", fake_run)

    status = check_paper2any_status(cfg)

    assert status.ready is False
    assert any("runtime dependencies" in item for item in status.missing)
    assert "pptx" in status.detail


def test_setup_paper2any_runtime_clones_installs_and_saves_config(tmp_path: Path, monkeypatch) -> None:
    from scholaraio.services.paper2any_runtime import setup_paper2any_runtime

    cfg = _build_config({}, tmp_path)
    calls: list[tuple[str, ...]] = []

    def fake_run(cmd, **kwargs):
        calls.append(tuple(str(part) for part in cmd))
        if cmd[:3] == ["git", "clone", "--depth"]:
            root = Path(cmd[-1])
            _write_paper2any_scripts(root)
            _write_paper2any_api(root)
            (root / "frontend-workflow").mkdir()
            (root / "frontend-workflow" / "package-lock.json").write_text("{}", encoding="utf-8")
        elif cmd[:3] == [sys.executable, "-m", "venv"]:
            root = Path(cmd[-1]).parent
            venv_bin = "Scripts" if sys.platform == "win32" else "bin"
            python_name = "python.exe" if sys.platform == "win32" else "python"
            venv_python = root / ".venv" / venv_bin / python_name
            venv_python.parent.mkdir(parents=True)
            venv_python.write_text("", encoding="utf-8")
            venv_python.chmod(0o755)
        elif len(cmd) >= 2 and cmd[1] == "ci":
            frontend_dir = Path(kwargs["cwd"])
            (frontend_dir / "node_modules").mkdir()
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("scholaraio.services.paper2any_runtime.subprocess.run", fake_run)

    result = setup_paper2any_runtime(cfg, install=True, save_config=True)

    assert result.status.ready is True
    assert ("git", "clone", "--depth", "1", result.repo_url, str(result.root)) in calls
    assert any(call[1:4] == ("-m", "pip", "install") and call[-2:] == ("-e", ".") for call in calls)
    assert any(call[1:4] == ("-m", "pip", "install") and "python-pptx" in call for call in calls)
    assert any(
        call[1:4] == ("-m", "pip", "install") and any(part.startswith("supabase") for part in call) for call in calls
    )
    assert any(
        call[1:4] == ("-m", "pip", "install") and any(part.startswith("python-multipart") for part in call)
        for call in calls
    )
    assert any(call[1:4] == ("-m", "pip", "install") and "torch" in call for call in calls)
    assert any(call[-1] == "ci" and "npm" in Path(call[0]).name for call in calls)
    local_config = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "paper2any:" in local_config
    assert f"root: {result.root}" in local_config


def test_paper2any_capabilities_include_cli_and_api_surface() -> None:
    from scholaraio.services.paper2any_runtime import paper2any_capabilities

    capabilities = paper2any_capabilities()
    names = {capability["name"] for capability in capabilities}
    modes = {capability["name"]: capability["mode"] for capability in capabilities}

    assert "figure" in names
    assert "paper2drawio" in names
    assert "paper2rebuttal" in names
    assert "paper2citation" in names
    assert "knowledge-base" in names
    assert modes["figure"] == "prepare"
    assert modes["paper2citation"] == "api"


def test_start_paper2any_api_uses_managed_venv_and_uvicorn(tmp_path: Path, monkeypatch) -> None:
    from scholaraio.services.paper2any_runtime import start_paper2any_api

    root = tmp_path / "data" / "runtime" / "extensions" / "paper2any" / "Paper2Any"
    _write_paper2any_api(root)
    venv_python = _write_managed_python(root)
    cfg = _build_config({"paper2any": {"root": str(root)}}, tmp_path)
    calls: list[dict] = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": tuple(str(part) for part in cmd), **kwargs})
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("scholaraio.services.paper2any_runtime.subprocess.run", fake_run)

    result = start_paper2any_api(cfg, host="127.0.0.1", port=8777, reload=True)

    assert result.root == root
    assert calls[0]["cmd"] == (
        str(venv_python),
        "-m",
        "uvicorn",
        "fastapi_app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8777",
        "--reload",
    )
    assert calls[0]["cwd"] == root
    assert calls[0]["check"] is True
    assert calls[0]["env"]["PAPER2ANY_RUNTIME_TMPDIR"] == str(root / "outputs" / "system" / "tmp")
