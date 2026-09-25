"""Tests for static published-paper site generation."""

from __future__ import annotations

import json
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest

import scholaraio.core.log as target_log
from scholaraio.core.config import _build_config


def _write_published_paper(root: Path, folder: str = "2026-04-29-Test") -> Path:
    paper = root / folder
    paper.mkdir(parents=True)
    (paper / "paper.pdf").write_bytes(b"pdf")
    (paper / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
    (paper / "images").mkdir()
    (paper / "images" / "fig.png").write_bytes(b"png")
    (paper / "misc").mkdir()
    (paper / "misc" / "notes.txt").write_text("notes", encoding="utf-8")
    (paper / "metadata.json").write_text(
        json.dumps(
            {
                "title": "A <Safe> Static Site",
                "date": "2026-04-29",
                "keywords": ["ScholarAIO", "<script>alert(1)</script>"],
                "subject": "Research Tools",
                "pdf_filename": "paper.pdf",
                "tex_files": ["main.tex", "../outside.tex"],
                "images_dir": "images",
                "misc_dir": "misc",
                "authors": ["Zimo", "Claude (AI Assistant)"],
                "note": "Final audited deliverable.",
            }
        ),
        encoding="utf-8",
    )
    return paper


def test_generate_site_copy_mode_escapes_html_and_copies_assets(tmp_path: Path) -> None:
    from scholaraio.services.publish_site import generate_site

    published = tmp_path / "published"
    paper = _write_published_paper(published)
    out = tmp_path / "site"

    result = generate_site(published_dir=published, out_dir=out, copy_assets=True)

    assert result.paper_count == 1
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "A &lt;Safe&gt; Static Site" in html
    assert "<script>alert(1)</script>" not in html
    assert (out / "assets" / "papers" / "2026-04-29-test" / "paper.pdf").read_bytes() == b"pdf"
    assert (paper / "2026-04-29-test-source.zip").exists()
    assert (out / "assets" / "papers" / "2026-04-29-test" / "2026-04-29-test-source.zip").exists()

    with zipfile.ZipFile(paper / "2026-04-29-test-source.zip") as zf:
        names = set(zf.namelist())
    assert "main.tex" in names
    assert "images/fig.png" in names
    assert "misc/notes.txt" in names
    assert "../outside.tex" not in names


def test_generate_site_symlink_mode_links_published_paper_directory(tmp_path: Path) -> None:
    from scholaraio.services.publish_site import generate_site

    published = tmp_path / "published"
    _write_published_paper(published)
    out = tmp_path / "site"

    generate_site(published_dir=published, out_dir=out, copy_assets=False)

    linked = out / "assets" / "papers" / "2026-04-29-test"
    assert linked.is_symlink()
    assert (linked / "paper.pdf").read_bytes() == b"pdf"


def test_publish_config_resolves_original_design_paths(tmp_path: Path) -> None:
    cfg = _build_config({"publish": {"site_output_dir": "site-out"}}, tmp_path)

    assert cfg.published_dir == (tmp_path / "published").resolve()
    assert cfg.site_output_dir == (tmp_path / "site-out").resolve()
    assert cfg.publish_site_output_dir == (tmp_path / "site-out").resolve()


def test_cmd_publish_site_uses_configured_output_dir(tmp_path: Path, monkeypatch) -> None:
    from scholaraio.interfaces.cli import compat as cli

    cfg = _build_config({"publish": {"site_output_dir": "site-out"}}, tmp_path)
    messages: list[str] = []
    seen: dict[str, object] = {}

    def fake_generate_site(*, published_dir, out_dir, copy_assets):
        seen["published_dir"] = published_dir
        seen["out_dir"] = out_dir
        seen["copy_assets"] = copy_assets
        return Namespace(paper_count=2)

    monkeypatch.setattr(target_log, "ui", messages.append)
    monkeypatch.setattr("scholaraio.services.publish_site.generate_site", fake_generate_site)

    cli.cmd_publish_site(Namespace(out_dir=None, symlink=False), cfg)

    assert seen == {
        "published_dir": (tmp_path / "published").resolve(),
        "out_dir": (tmp_path / "site-out").resolve(),
        "copy_assets": True,
    }
    assert any("Generated site for 2 published papers" in message for message in messages)


def test_cmd_publish_site_requires_output_dir_when_not_configured(tmp_path: Path) -> None:
    from scholaraio.interfaces.cli import compat as cli

    cfg = _build_config({}, tmp_path)

    with pytest.raises(SystemExit):
        cli.cmd_publish_site(Namespace(out_dir=None, symlink=False), cfg)
