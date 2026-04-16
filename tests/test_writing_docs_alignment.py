"""Multi-surface alignment checks for writing-skill documentation.

This file intentionally contains a broad set of explicit checks so changes to
writing-skill names or discovery paths have to stay aligned across docs.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_round_1_router_skill_exists_on_disk() -> None:
    assert (ROOT / ".claude" / "skills" / "academic-writing" / "SKILL.md").exists()


def test_round_2_poster_skill_exists_on_disk() -> None:
    assert (ROOT / ".claude" / "skills" / "poster" / "SKILL.md").exists()


def test_round_3_paper_guided_reading_skill_exists_on_disk() -> None:
    assert (ROOT / ".claude" / "skills" / "paper-guided-reading" / "SKILL.md").exists()


def test_round_3_technical_report_skill_exists_on_disk() -> None:
    assert (ROOT / ".claude" / "skills" / "technical-report" / "SKILL.md").exists()


def test_round_4_writing_guide_mentions_all_new_writing_skills() -> None:
    content = _read("docs/guide/writing.md")
    for token in ("/academic-writing", "/paper-guided-reading", "/poster", "/technical-report"):
        assert token in content


def test_round_5_agents_md_mentions_all_new_writing_skills() -> None:
    content = _read("AGENTS.md")
    for token in ("academic-writing", "paper-guided-reading", "poster", "technical-report"):
        assert token in content


def test_round_6_claude_md_mentions_all_new_writing_skills() -> None:
    content = _read("CLAUDE.md")
    for token in ("academic-writing", "paper-guided-reading", "poster", "technical-report"):
        assert token in content


def test_round_7_agents_cn_mentions_all_new_writing_skills() -> None:
    content = _read("AGENTS_CN.md")
    for token in ("academic-writing", "paper-guided-reading", "poster", "technical-report"):
        assert token in content


def test_round_8_clawhub_registers_all_new_writing_skills() -> None:
    content = _read("clawhub.yaml")
    for token in (
        "scholaraio/academic-writing",
        "scholaraio/paper-guided-reading",
        "scholaraio/poster",
        "scholaraio/technical-report",
    ):
        assert token in content


def test_round_9_readme_mentions_router_first_writing_stack() -> None:
    content = _read("README.md")
    assert "academic-writing" in content
    assert "paper-guided-reading" in content
    assert "poster" in content
    assert "technical-report" in content


def test_round_10_readme_cn_mentions_router_first_writing_stack() -> None:
    content = _read("README_CN.md")
    assert "academic-writing" in content
    assert "paper-guided-reading" in content
    assert "poster" in content
    assert "technical-report" in content


def test_round_11_docs_index_mentions_writing_router() -> None:
    content = _read("docs/index.md")
    assert "academic-writing" in content
    assert "guided deep reading" in content.lower()
    assert "posters" in content
    assert "technical reports" in content
