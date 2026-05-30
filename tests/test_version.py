from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 CI
    import tomli as tomllib

from scholaraio import __version__


def test_runtime_version_matches_project_version():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "(?P<version>[^"]+)"$', text)
    assert match is not None
    project_version = match.group("version")

    assert __version__ == project_version


def test_citation_version_matches_project_version():
    root = Path(__file__).resolve().parents[1]
    pyproject_text = (root / "pyproject.toml").read_text(encoding="utf-8")
    project_match = re.search(r'(?m)^version = "(?P<version>[^"]+)"$', pyproject_text)
    assert project_match is not None

    citation_text = (root / "CITATION.cff").read_text(encoding="utf-8")
    citation_match = re.search(r'(?m)^version:\s*"?([^"\n]+)"?\s*$', citation_text)
    assert citation_match is not None

    assert citation_match.group(1).strip() == project_match.group("version")


def test_release_version_is_1_5_0():
    assert __version__ == "1.5.0"


def test_mineru_open_api_dependency_uses_current_cli_floor():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert "mineru-open-api>=0.5.9" in data["project"]["dependencies"]
