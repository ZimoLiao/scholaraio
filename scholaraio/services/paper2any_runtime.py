"""Managed external Paper2Any runtime helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from scholaraio.core.config import Config

PAPER2ANY_SCRIPTS = (
    "script/run_paper2figure_cli.py",
    "script/run_paper2ppt_cli.py",
    "script/run_paper2ppt_frontend_cli.py",
    "script/run_pdf2ppt_cli.py",
    "script/run_image2ppt_cli.py",
    "script/run_ppt2polish_cli.py",
    "script/run_paper2poster_cli.py",
    "script/run_paper2video_cli.py",
)
PAPER2ANY_API_APP = "fastapi_app/main.py"
PAPER2ANY_FRONTEND_DIR = "frontend-workflow"
PAPER2ANY_RUNTIME_PACKAGES = (
    "python-pptx",
    "pymupdf",
    "pdfplumber",
    "PyPDF2",
    "pdf2image",
    "scikit-image",
    "imgkit",
    "seaborn",
    "lmdb",
    "mineru-vl-utils",
    "fastapi",
    "pydantic-settings",
    "requests",
    "pandas",
    "numpy",
    "PyYAML",
    "rich",
    "supabase==2.27.2",
    "python-multipart==0.0.27",
    "termcolor",
    "psutil",
    "pyfiglet",
    "uvicorn",
    "sseclient-py",
    "json_repair",
    "reportlab",
    "svglib",
    "cairosvg",
    "moviepy",
    "scikit-learn",
    "opencv-python",
    "beautifulsoup4",
    "playwright",
    "playwright-stealth",
    "transformers",
)
PAPER2ANY_TORCH_INSTALL_COMMAND = (
    "-m",
    "pip",
    "install",
    "torch",
    "torchvision",
    "--index-url",
    "https://download.pytorch.org/whl/cpu",
)
PAPER2ANY_IMPORT_PROBE = """
import bs4
import cv2
import fastapi
import fitz
import mineru_vl_utils
import pandas
import pdfplumber
import playwright
import playwright_stealth
import pptx
import reportlab
import svglib
import supabase
import torch
import transformers
from fastapi_app.main import app as _paper2any_fastapi_app
from supabase import create_client
"""


@dataclass(frozen=True)
class Paper2AnyStatus:
    """External Paper2Any runtime status."""

    root: Path
    ready: bool
    missing: list[str] = field(default_factory=list)
    venv_python: Path | None = None
    detail: str = ""


@dataclass(frozen=True)
class Paper2AnySetupResult:
    """Result of ``paper2any setup``."""

    root: Path
    repo_url: str
    status: Paper2AnyStatus


@dataclass(frozen=True)
class Paper2AnyServeResult:
    """Result of starting the Paper2Any FastAPI backend."""

    root: Path
    host: str
    port: int
    command: tuple[str, ...]


PAPER2ANY_PREPARE_CAPABILITIES = (
    ("figure", "Scientific figure or technical route diagram", "prepare"),
    ("ppt", "Editable paper-to-PPT frontend deck", "prepare"),
    ("ppt-classic", "Classic upstream paper-to-PPT workflow", "prepare"),
    ("pdf2ppt", "Layout-preserving PDF to editable PPT", "prepare"),
    ("image2ppt", "Image or screenshot to PPT", "prepare"),
    ("ppt2polish", "Polish an existing PPT/PPTX", "prepare"),
    ("poster", "Academic poster from paper PDF", "prepare"),
    ("video", "Video script and narration assets from paper PDF", "prepare"),
)
PAPER2ANY_API_CAPABILITIES = (
    ("paper2drawio", "Paper/text to editable draw.io diagrams", "api"),
    ("image2drawio", "Image or screenshot to draw.io diagrams", "api"),
    ("paper2rebuttal", "Structured rebuttal and revision-response drafting", "api"),
    ("paper2citation", "Citation explorer for authors, papers, and contexts", "api"),
    ("paper2technical", "Technical report and method-summary workflow", "api"),
    ("image-playground", "Managed image model playground", "api"),
    ("mindmap", "Mind-map generation and persistence", "api"),
    ("knowledge-base", "KB upload, search, chat, PPT, podcast, mindmap, and report workflows", "api"),
    ("files", "Generated file upload, history, stream, and access URLs", "api"),
)


def paper2any_capabilities() -> list[dict[str, str]]:
    """Return ScholarAIO's supported Paper2Any integration surface."""
    rows = []
    for name, description, mode in (*PAPER2ANY_PREPARE_CAPABILITIES, *PAPER2ANY_API_CAPABILITIES):
        rows.append({"name": name, "description": description, "mode": mode})
    return rows


def resolve_paper2any_root(cfg: Config, override: str | Path | None = None) -> Path:
    """Resolve Paper2Any root from explicit CLI, env, config, then managed default."""
    if override:
        return Path(override).expanduser().resolve()
    env_root = os.environ.get("PAPER2ANY_ROOT", "")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return cfg.paper2any_root


def paper2any_venv_python(root: Path) -> Path:
    """Return the expected Python executable inside the managed Paper2Any venv."""
    if sys.platform == "win32":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def check_paper2any_status(cfg: Config, root: str | Path | None = None) -> Paper2AnyStatus:
    """Check whether a Paper2Any checkout has the expected files and venv."""
    resolved_root = resolve_paper2any_root(cfg, root)
    missing: list[str] = []
    if not resolved_root.is_dir():
        missing.append("checkout")
    for rel in PAPER2ANY_SCRIPTS:
        if not (resolved_root / rel).is_file():
            missing.append(rel)
    if not (resolved_root / PAPER2ANY_API_APP).is_file():
        missing.append(PAPER2ANY_API_APP)
    venv_python = paper2any_venv_python(resolved_root)
    if not venv_python.is_file():
        missing.append(".venv python")
    elif (resolved_root / "pyproject.toml").is_file():
        try:
            probe = subprocess.run(
                [str(venv_python), "-c", PAPER2ANY_IMPORT_PROBE],
                cwd=resolved_root,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as e:
            missing.append(f"runtime dependencies ({e})")
        else:
            if probe.returncode != 0:
                stderr_line = (probe.stderr or probe.stdout or "").strip().splitlines()
                detail = stderr_line[-1] if stderr_line else "import probe failed"
                missing.append(f"runtime dependencies ({detail})")
    frontend_dir = resolved_root / PAPER2ANY_FRONTEND_DIR
    if (frontend_dir / "package-lock.json").is_file() and not (frontend_dir / "node_modules").is_dir():
        missing.append("frontend dependencies")
    ready = not missing
    detail = "ready" if ready else "missing: " + ", ".join(missing)
    return Paper2AnyStatus(root=resolved_root, ready=ready, missing=missing, venv_python=venv_python, detail=detail)


def setup_paper2any_runtime(
    cfg: Config,
    *,
    root: str | Path | None = None,
    repo_url: str | None = None,
    install: bool = True,
    update: bool = False,
    save_config: bool = True,
) -> Paper2AnySetupResult:
    """Clone/update Paper2Any and install its dependencies in an isolated venv."""
    resolved_root = resolve_paper2any_root(cfg, root)
    resolved_repo_url = repo_url or cfg.paper2any.repo_url
    resolved_root.parent.mkdir(parents=True, exist_ok=True)

    if (resolved_root / ".git").is_dir():
        if update:
            subprocess.run(["git", "-C", str(resolved_root), "pull", "--ff-only"], check=True)
    elif resolved_root.exists() and any(resolved_root.iterdir()):
        raise FileExistsError(f"Paper2Any root exists but is not a git checkout: {resolved_root}")
    else:
        subprocess.run(["git", "clone", "--depth", "1", resolved_repo_url, str(resolved_root)], check=True)

    venv_python = paper2any_venv_python(resolved_root)
    if install:
        if not venv_python.is_file():
            subprocess.run([sys.executable, "-m", "venv", str(resolved_root / ".venv")], check=True)
        install_command = cfg.paper2any.install_command or ["-m", "pip", "install", "-e", "."]
        subprocess.run([str(venv_python), *install_command], cwd=resolved_root, check=True)
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", *PAPER2ANY_RUNTIME_PACKAGES], cwd=resolved_root, check=True
        )
        subprocess.run([str(venv_python), *PAPER2ANY_TORCH_INSTALL_COMMAND], cwd=resolved_root, check=True)
        frontend_dir = resolved_root / PAPER2ANY_FRONTEND_DIR
        if (frontend_dir / "package-lock.json").is_file():
            npm = shutil.which("npm")
            if not npm:
                raise RuntimeError("npm is required to install Paper2Any frontend export dependencies")
            subprocess.run([npm, "ci"], cwd=frontend_dir, check=True)

    if save_config:
        _save_paper2any_local_config(cfg, resolved_root, resolved_repo_url)

    return Paper2AnySetupResult(
        root=resolved_root,
        repo_url=resolved_repo_url,
        status=check_paper2any_status(cfg, resolved_root),
    )


def start_paper2any_api(
    cfg: Config,
    *,
    root: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 9999,
    reload: bool = False,
) -> Paper2AnyServeResult:
    """Start the managed Paper2Any FastAPI backend in the upstream checkout."""
    resolved_root = resolve_paper2any_root(cfg, root)
    venv_python = paper2any_venv_python(resolved_root)
    app_module = resolved_root / "fastapi_app" / "main.py"
    if not resolved_root.is_dir():
        raise FileNotFoundError(f"Paper2Any checkout not found: {resolved_root}")
    if not venv_python.is_file():
        raise FileNotFoundError(f"Paper2Any Python runtime not found: {venv_python}")
    if not app_module.is_file():
        raise FileNotFoundError(f"Paper2Any FastAPI app not found: {app_module}")

    runtime_tmp = resolved_root / "outputs" / "system" / "tmp"
    runtime_tmp.mkdir(parents=True, exist_ok=True)
    command = [
        str(venv_python),
        "-m",
        "uvicorn",
        "fastapi_app.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        command.append("--reload")
    env = os.environ.copy()
    env.setdefault("PAPER2ANY_RUNTIME_TMPDIR", str(runtime_tmp))
    subprocess.run(command, cwd=resolved_root, env=env, check=True)
    return Paper2AnyServeResult(root=resolved_root, host=host, port=port, command=tuple(command))


def _save_paper2any_local_config(cfg: Config, root: Path, repo_url: str) -> None:
    """Persist the managed Paper2Any root in config.local.yaml."""
    local_path = cfg._root / "config.local.yaml"
    local_data: dict = {}
    if local_path.exists():
        raw = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            local_data = raw
    paper2any_data = local_data.get("paper2any")
    if not isinstance(paper2any_data, dict):
        paper2any_data = {}
    paper2any_data["root"] = str(root)
    paper2any_data["repo_url"] = repo_url
    local_data["paper2any"] = paper2any_data
    local_path.write_text(yaml.safe_dump(local_data, allow_unicode=True, sort_keys=False), encoding="utf-8")
