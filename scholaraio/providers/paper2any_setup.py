"""Setup helpers for the external Paper2Any runtime extension."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PAPER2ANY_REPO_URL = "https://github.com/OpenDCAI/Paper2Any.git"
DEFAULT_PAPER2ANY_REF = "main"


@dataclass
class Paper2AnySetupResult:
    """Result of preparing the external Paper2Any runtime."""

    root: Path
    venv_python: Path
    actions: list[str] = field(default_factory=list)
    dry_run: bool = False


class Paper2AnySetupError(RuntimeError):
    """Raised when Paper2Any setup cannot complete."""


def setup_paper2any_runtime(
    root: str | Path,
    *,
    repo_url: str = DEFAULT_PAPER2ANY_REPO_URL,
    ref: str = DEFAULT_PAPER2ANY_REF,
    update: bool = False,
    install_runtime: bool = False,
    python: str = sys.executable,
    dry_run: bool = False,
) -> Paper2AnySetupResult:
    """Clone/update Paper2Any and optionally prepare its isolated Python runtime."""
    root_path = Path(root).expanduser().resolve()
    venv_dir = root_path.parent / ".venv"
    venv_python = venv_dir / "bin" / "python"
    result = Paper2AnySetupResult(root=root_path, venv_python=venv_python, dry_run=dry_run)

    if not root_path.exists():
        result.actions.append(f"clone {repo_url} -> {root_path}")
        if not dry_run:
            root_path.parent.mkdir(parents=True, exist_ok=True)
            _run(["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(root_path)])
    elif (root_path / ".git").is_dir():
        if update:
            result.actions.append(f"update existing checkout at {root_path}")
            if not dry_run:
                _run(["git", "-C", str(root_path), "fetch", "--depth", "1", "origin", ref])
                _run(["git", "-C", str(root_path), "checkout", "FETCH_HEAD"])
        else:
            result.actions.append(f"checkout already exists at {root_path}")
    else:
        raise Paper2AnySetupError(f"Paper2Any root exists but is not a git checkout: {root_path}")

    if install_runtime:
        result.actions.append(f"prepare isolated Python runtime at {venv_dir}")
        if not dry_run:
            if not (venv_dir / "pyvenv.cfg").exists():
                _run([python, "-m", "venv", str(venv_dir)])
            _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
            _install_requirements(root_path, venv_python)
    else:
        result.actions.append("skip upstream dependency install")

    return result


def serve_paper2any_backend(
    root: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    python: str = "",
    backend_api_key: str = "",
) -> None:
    """Run the real upstream Paper2Any FastAPI backend from its checkout."""
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise Paper2AnySetupError(f"Paper2Any root does not exist: {root_path}")
    if not (root_path / "fastapi_app" / "main.py").is_file():
        raise Paper2AnySetupError(f"Paper2Any FastAPI app not found under: {root_path}")

    resolved_backend_api_key = (backend_api_key or os.environ.get("PAPER2ANY_BACKEND_API_KEY", "")).strip()
    env = os.environ.copy()
    if resolved_backend_api_key:
        env["BACKEND_API_KEY"] = resolved_backend_api_key

    _run(
        [
            _resolve_runtime_python(root_path, python),
            "-m",
            "uvicorn",
            "fastapi_app.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=root_path,
        env=env,
    )


def _install_requirements(root: Path, venv_python: Path) -> None:
    requirements = [root / "requirements-base.txt", root / "requirements-paper.txt"]
    for path in requirements:
        if path.exists():
            _run([str(venv_python), "-m", "pip", "install", "-r", str(path)])


def _resolve_runtime_python(root: Path, requested_python: str = "") -> str:
    requested = requested_python.strip()
    if requested:
        return requested
    runtime_python = root.parent / ".venv" / "bin" / "python"
    if runtime_python.exists():
        return str(runtime_python)
    return sys.executable


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    try:
        if cwd is None and env is None:
            subprocess.run(cmd, check=True)
        elif cwd is None:
            subprocess.run(cmd, check=True, env=env)
        elif env is None:
            subprocess.run(cmd, check=True, cwd=str(cwd))
        else:
            subprocess.run(cmd, check=True, cwd=str(cwd), env=env)
    except FileNotFoundError as exc:
        raise Paper2AnySetupError(f"Missing executable: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise Paper2AnySetupError(f"Command failed with exit code {exc.returncode}: {' '.join(cmd)}") from exc
