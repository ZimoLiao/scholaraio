"""Paper2Any handoff bundle generation."""

from __future__ import annotations

import json
import shlex
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from scholaraio.services.paper2any_runtime import resolve_paper2any_root
from scholaraio.stores.papers import read_meta

if TYPE_CHECKING:
    from scholaraio.core.config import Config


TASKS = {"figure", "ppt", "ppt-classic", "pdf2ppt", "image2ppt", "ppt2polish", "poster", "video"}
GRAPH_TYPES = {"model_arch", "tech_route", "exp_data"}
INPUT_PREFERENCES = {"auto", "pdf", "markdown"}
SOURCE_FILE_REQUIRED_TASKS = {"image2ppt", "ppt2polish"}
PDF_ONLY_TASKS = {"pdf2ppt", "poster", "video"}
PAGE_COUNT_TASKS = {"ppt", "ppt-classic", "pdf2ppt", "image2ppt"}
LANGUAGE_TASKS = {"figure", "ppt", "ppt-classic", "pdf2ppt", "image2ppt", "ppt2polish", "video"}
STYLE_TASKS = {"figure", "ppt", "ppt-classic", "pdf2ppt", "image2ppt", "ppt2polish"}


@dataclass(frozen=True)
class Paper2AnyBundle:
    """Generated bundle paths for a Paper2Any handoff."""

    bundle_dir: Path
    input_path: Path
    input_kind: str
    output_dir: Path
    manifest_path: Path
    script_path: Path
    paper2any_command: list[str]


def prepare_paper2any_bundle(
    paper_d: Path,
    cfg: Config,
    *,
    task: str = "figure",
    graph_type: str = "model_arch",
    input_preference: str = "auto",
    source_file: Path | str | None = None,
    out_dir: Path | str | None = None,
    paper2any_root: str | Path | None = None,
    page_count: int | None = None,
    language: str | None = None,
    style: str | None = None,
) -> Paper2AnyBundle:
    """Create a portable handoff bundle for running Paper2Any externally."""

    task = _normalize_choice(task, TASKS, "task")
    graph_type = _normalize_choice(graph_type, GRAPH_TYPES, "graph_type")
    input_preference = _normalize_choice(input_preference, INPUT_PREFERENCES, "input_preference")

    source_input, input_kind = _select_input(
        paper_d,
        task=task,
        input_preference=input_preference,
        source_file=source_file,
    )
    resolved_paper2any_root = resolve_paper2any_root(cfg, paper2any_root)
    bundle_dir = _bundle_dir(paper_d, cfg, task=task, out_dir=out_dir)
    output_dir = bundle_dir / "outputs"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_path = bundle_dir / source_input.name
    if source_input.resolve() != input_path.resolve():
        shutil.copy2(source_input, input_path)

    command = _build_command(
        task=task,
        input_kind=input_kind,
        input_value=str(input_path) if input_kind == "pdf" else "<contents of paper.md>",
        output_dir=output_dir,
        graph_type=graph_type,
        page_count=page_count,
        language=language,
        style=style,
    )

    manifest_path = bundle_dir / "paper2any.json"
    script_path = bundle_dir / "run-paper2any.sh"
    meta = read_meta(paper_d)
    manifest = {
        "schema_version": 1,
        "created_by": "scholaraio",
        "task": task,
        "graph_type": graph_type if task == "figure" else None,
        "paper": _paper_manifest(paper_d, meta),
        "input": {
            "kind": input_kind,
            "path": str(input_path),
            "source_path": str(source_input.resolve()),
            "paper2any_input_type": _paper2any_input_type(task, input_kind),
        },
        "output_dir": str(output_dir),
        "paper2any_root": str(resolved_paper2any_root),
        "paper2any_command": command,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    script = _render_runner_script(
        task=task,
        input_path=input_path,
        input_kind=input_kind,
        output_dir=output_dir,
        paper2any_root=resolved_paper2any_root,
        graph_type=graph_type,
        page_count=page_count,
        language=language,
        style=style,
    )
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return Paper2AnyBundle(
        bundle_dir=bundle_dir,
        input_path=input_path,
        input_kind=input_kind,
        output_dir=output_dir,
        manifest_path=manifest_path,
        script_path=script_path,
        paper2any_command=command,
    )


def _normalize_choice(value: str, valid: set[str], field_name: str) -> str:
    value = str(value or "").strip()
    if value not in valid:
        choices = ", ".join(sorted(valid))
        raise ValueError(f"Invalid {field_name}: {value!r}. Expected one of: {choices}")
    return value


def _bundle_dir(paper_d: Path, cfg: Config, *, task: str, out_dir: Path | str | None) -> Path:
    if out_dir is None:
        root = Path(cfg.workspace_dir) / "_system" / "paper2any"
    else:
        root = Path(out_dir)
    return (root / paper_d.name / task).resolve()


def _select_input(
    paper_d: Path,
    *,
    task: str,
    input_preference: str,
    source_file: Path | str | None = None,
) -> tuple[Path, str]:
    if source_file is not None:
        source = Path(source_file).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Paper2Any source file not found: {source}")
        return source, _detect_input_kind(source)

    if task in SOURCE_FILE_REQUIRED_TASKS:
        raise ValueError(f"Paper2Any task {task!r} requires --source-file")

    pdf = paper_d / "paper.pdf"
    markdown = paper_d / "paper.md"

    if task in PDF_ONLY_TASKS:
        if input_preference == "markdown":
            raise ValueError(f"Paper2Any {task} requires a PDF input; use --input pdf")
        if pdf.exists():
            return pdf, "pdf"
        raise FileNotFoundError(f"Paper2Any {task} requires paper.pdf in {paper_d}")

    if input_preference in {"auto", "pdf"} and pdf.exists():
        return pdf, "pdf"
    if input_preference == "pdf":
        raise FileNotFoundError(f"paper.pdf not found in {paper_d}")

    if markdown.exists():
        return markdown, "markdown"
    raise FileNotFoundError(f"No supported Paper2Any input found in {paper_d} (expected paper.pdf or paper.md)")


def _detect_input_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".md", ".markdown", ".txt"}:
        return "markdown"
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    if suffix in {".ppt", ".pptx"}:
        return "pptx"
    return "file"


def _paper_manifest(paper_d: Path, meta: dict) -> dict:
    return {
        "dir_name": paper_d.name,
        "id": meta.get("id"),
        "title": meta.get("title") or meta.get("name") or paper_d.name,
        "authors": meta.get("authors") or [],
        "year": meta.get("year"),
        "doi": meta.get("doi"),
    }


def _paper2any_input_type(task: str, input_kind: str) -> str | None:
    if task in {"pdf2ppt", "image2ppt", "ppt2polish", "poster", "video"}:
        return None
    if input_kind == "pdf":
        return "PDF"
    if input_kind == "pptx" and task in {"ppt", "ppt-classic"}:
        return "PPTX"
    if input_kind == "image" and task == "figure":
        return "FIGURE"
    if task in {"figure", "ppt", "ppt-classic"} and input_kind == "markdown":
        return "TEXT"
    return None


def _build_command(
    *,
    task: str,
    input_kind: str,
    input_value: str,
    output_dir: Path,
    graph_type: str,
    page_count: int | None,
    language: str | None,
    style: str | None,
) -> list[str]:
    script = _paper2any_script(task)
    command = ["python", script, "--input", input_value]
    input_type = _paper2any_input_type(task, input_kind)
    if input_type:
        command.extend(["--input-type", input_type])
    if task == "figure":
        command.extend(["--graph-type", graph_type])
    if page_count is not None and task in PAGE_COUNT_TASKS:
        command.extend(["--page-count", str(page_count)])
    if language and task in LANGUAGE_TASKS:
        command.extend(["--language", language])
    if style and task in STYLE_TASKS:
        command.extend(["--style", style])
    if task == "ppt":
        command.append("--export-pptx")
    command.extend(["--output-dir", str(output_dir)])
    return command


def _paper2any_script(task: str) -> str:
    return {
        "figure": "script/run_paper2figure_cli.py",
        "ppt-classic": "script/run_paper2ppt_cli.py",
        "ppt": "script/run_paper2ppt_frontend_cli.py",
        "pdf2ppt": "script/run_pdf2ppt_cli.py",
        "image2ppt": "script/run_image2ppt_cli.py",
        "ppt2polish": "script/run_ppt2polish_cli.py",
        "poster": "script/run_paper2poster_cli.py",
        "video": "script/run_paper2video_cli.py",
    }[task]


def _paper2any_module(task: str) -> str:
    return _paper2any_script(task).removesuffix(".py").replace("/", ".")


def _render_runner_script(
    *,
    task: str,
    input_path: Path,
    input_kind: str,
    output_dir: Path,
    paper2any_root: str | Path | None,
    graph_type: str,
    page_count: int | None,
    language: str | None,
    style: str | None,
) -> str:
    command = _build_command(
        task=task,
        input_kind=input_kind,
        input_value="$PAPER2ANY_INPUT",
        output_dir=output_dir,
        graph_type=graph_type,
        page_count=page_count,
        language=language,
        style=style,
    )
    default_root = _bash_default(str(Path(paper2any_root).expanduser())) if paper2any_root else ""
    input_type = {
        "markdown": "markdown text",
        "pdf": "PDF file",
        "image": "image file",
        "pptx": "PPT/PPTX file",
    }.get(input_kind, "file")

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'PAPER2ANY_ROOT="${{PAPER2ANY_ROOT:-{default_root}}}"',
        'PAPER2ANY_PYTHON="${PAPER2ANY_PYTHON:-$PAPER2ANY_ROOT/.venv/bin/python}"',
        "",
        'if [[ -z "$PAPER2ANY_ROOT" ]]; then',
        '  echo "Set PAPER2ANY_ROOT to a Paper2Any checkout, or regenerate this bundle with --paper2any-root." >&2',
        "  exit 2",
        "fi",
        'if [[ ! -d "$PAPER2ANY_ROOT" ]]; then',
        '  echo "Paper2Any root does not exist: $PAPER2ANY_ROOT" >&2',
        "  exit 2",
        "fi",
        'if [[ ! -x "$PAPER2ANY_PYTHON" ]]; then',
        '  echo "Paper2Any Python runtime does not exist: $PAPER2ANY_PYTHON" >&2',
        '  echo "Run: scholaraio paper2any setup" >&2',
        "  exit 2",
        "fi",
        "",
        f'INPUT_PATH="$SCRIPT_DIR/{input_path.name}"',
        'OUTPUT_DIR="$SCRIPT_DIR/outputs"',
        'BUNDLE_PARENT="$(basename "$(dirname "$SCRIPT_DIR")")"',
        'BUNDLE_TASK="$(basename "$SCRIPT_DIR")"',
        'RUNTIME_OUTPUT_DIR="${PAPER2ANY_OUTPUT_DIR:-$PAPER2ANY_ROOT/outputs/scholaraio/$BUNDLE_PARENT/$BUNDLE_TASK}"',
        'rm -rf "$RUNTIME_OUTPUT_DIR"',
        'mkdir -p "$OUTPUT_DIR" "$RUNTIME_OUTPUT_DIR"',
        "_redact_paper2any_output() {",
        "  sed -E 's/(sk-[A-Za-z0-9_-]{8})[A-Za-z0-9_-]+/\\1***REDACTED/g; s/(API Key: )[[:graph:]]+/\\1<redacted>/g'",
        "}",
        f'echo "Paper2Any input: {input_type} ($INPUT_PATH)"',
    ]
    if input_kind == "markdown":
        lines.extend(
            [
                "export INPUT_PATH OUTPUT_DIR RUNTIME_OUTPUT_DIR",
                "",
                'cd "$PAPER2ANY_ROOT"',
                "set +e",
                '"$PAPER2ANY_PYTHON" - "$@" <<\'PY\' 2>&1 | _redact_paper2any_output',
                "import os",
                "import runpy",
                "import sys",
                "from pathlib import Path",
                "",
                'input_text = Path(os.environ["INPUT_PATH"]).read_text(encoding="utf-8")',
                "passthrough_args = sys.argv[1:]",
                "sys.argv = [",
            ]
        )
        for token in command[1:]:
            if token == "$PAPER2ANY_INPUT":
                lines.append("    input_text,")
            elif token == str(output_dir):
                lines.append('    os.environ["RUNTIME_OUTPUT_DIR"],')
            else:
                lines.append(f"    {token!r},")
        lines.extend(
            [
                "] + passthrough_args",
                f'runpy.run_module("{_paper2any_module(task)}", run_name="__main__")',
                "PY",
                "paper2any_status=${PIPESTATUS[0]}",
                "set -e",
                'if [[ "$paper2any_status" -ne 0 ]]; then',
                '  exit "$paper2any_status"',
                "fi",
                'if compgen -G "$RUNTIME_OUTPUT_DIR/*" > /dev/null; then',
                '  cp -a "$RUNTIME_OUTPUT_DIR"/. "$OUTPUT_DIR"/',
                "fi",
                "",
            ]
        )
        return "\n".join(lines)

    lines.append('PAPER2ANY_INPUT="$INPUT_PATH"')
    lines.extend(
        [
            "",
            'cd "$PAPER2ANY_ROOT"',
            "cmd=(",
        ]
    )
    for token in command:
        if token == "$PAPER2ANY_INPUT":
            lines.append('  "$PAPER2ANY_INPUT"')
        elif token == str(output_dir):
            lines.append('  "$RUNTIME_OUTPUT_DIR"')
        else:
            lines.append(f"  {shlex.quote(token)}")
    lines.extend(
        [
            ")",
            "set +e",
            '"$PAPER2ANY_PYTHON" "${cmd[@]:1}" "$@" 2>&1 | _redact_paper2any_output',
            "paper2any_status=${PIPESTATUS[0]}",
            "set -e",
            'if [[ "$paper2any_status" -ne 0 ]]; then',
            '  exit "$paper2any_status"',
            "fi",
            'if compgen -G "$RUNTIME_OUTPUT_DIR/*" > /dev/null; then',
            '  cp -a "$RUNTIME_OUTPUT_DIR"/. "$OUTPUT_DIR"/',
            "fi",
            "",
        ]
    )
    return "\n".join(lines)


def _bash_default(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
