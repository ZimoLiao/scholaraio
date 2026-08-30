"""Regression tests for academic-writing skill discovery and routing docs."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".claude" / "skills"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _split_frontmatter(path: Path) -> tuple[dict, str]:
    text = _read(path)
    assert text.startswith("---\n"), f"{path} must start with YAML frontmatter"
    _, fm, body = text.split("---\n", 2)
    data = yaml.safe_load(fm)
    assert isinstance(data, dict), f"{path} frontmatter must parse to a mapping"
    return data, body


def _extract_skill_routes(text: str) -> set[str]:
    return set(re.findall(r"`/([a-z0-9-]+)`", text))


def test_router_and_deliverable_skills_have_valid_frontmatter() -> None:
    for skill_name in ("academic-writing", "paper-guided-reading", "poster", "technical-report"):
        skill_path = SKILLS_DIR / skill_name / "SKILL.md"
        frontmatter, body = _split_frontmatter(skill_path)

        assert frontmatter["name"] == skill_name
        assert frontmatter["description"].startswith("Use when ")
        assert body.strip().startswith("# ")


def test_academic_writing_router_only_points_to_existing_skills() -> None:
    router_path = SKILLS_DIR / "academic-writing" / "SKILL.md"
    routes = _extract_skill_routes(_read(router_path))

    assert "paper-guided-reading" in routes
    assert "poster" in routes
    assert "technical-report" in routes
    for route in routes:
        assert (SKILLS_DIR / route / "SKILL.md").exists(), f"Missing routed skill: {route}"


def test_new_deliverable_skills_only_reference_existing_skills() -> None:
    for skill_name in ("poster", "technical-report"):
        skill_path = SKILLS_DIR / skill_name / "SKILL.md"
        routes = _extract_skill_routes(_read(skill_path))

        assert routes, f"{skill_name} should route to at least one downstream skill"
        for route in routes:
            assert (SKILLS_DIR / route / "SKILL.md").exists(), f"{skill_name} references missing skill {route}"


def test_writing_guide_mentions_router_and_new_deliverable_skills() -> None:
    content = _read(ROOT / "docs" / "guide" / "writing.md")

    assert "/academic-writing" in content
    assert "/paper-guided-reading" in content
    assert "/poster" in content
    assert "/technical-report" in content
    assert "Choose By Deliverable" in content
    assert "Choose By Writing Stage" in content


def test_agent_instructions_list_router_and_new_deliverable_skills() -> None:
    for rel_path in ("AGENTS.md", "CLAUDE.md", "AGENTS_CN.md"):
        content = _read(ROOT / rel_path)

        assert "academic-writing" in content
        assert "paper-guided-reading" in content
        assert "poster" in content
        assert "technical-report" in content


def test_clawhub_registers_new_writing_skills() -> None:
    data = yaml.safe_load(_read(ROOT / "clawhub.yaml"))
    skills = {item["name"]: item for item in data["skills"]}

    for skill_name in ("academic-writing", "paper-guided-reading", "poster", "technical-report"):
        fq_name = f"scholaraio/{skill_name}"
        assert fq_name in skills
        assert skills[fq_name]["path"] == f".claude/skills/{skill_name}"


def test_common_agent_workflows_use_current_agent_native_capabilities() -> None:
    native_first_skills = ("academic-writing", "paper-guided-reading", "draw", "document")
    shared_skills = (*native_first_skills, "paper2any")

    for skill_name in native_first_skills:
        content = _read(SKILLS_DIR / skill_name / "SKILL.md")

        assert "当前 Agent 原生能力优先" in content, f"{skill_name} must declare the native-first contract"
        assert "实际" in content and "能力" in content, f"{skill_name} must gate routing on available capabilities"
        assert "不按 Agent 品牌路由" in content, f"{skill_name} must route by capability, not host identity"

    for skill_name in shared_skills:
        content = _read(SKILLS_DIR / skill_name / "SKILL.md")

        for host_name in ("Codex", "Claude Code", "OpenClaw"):
            assert host_name not in content, f"{skill_name} must not default-route through {host_name}"


def test_paper2any_stays_an_isolated_benchmark_gated_extension() -> None:
    content = _read(SKILLS_DIR / "paper2any" / "SKILL.md")

    assert "isolated extension" in content
    assert "fixed-corpus" in content


def test_document_skill_uses_progressive_disclosure_for_format_details() -> None:
    skill_dir = SKILLS_DIR / "document"
    content = _read(skill_dir / "SKILL.md")

    assert len(content.splitlines()) < 200
    for name in ("docx.md", "pptx.md", "xlsx.md"):
        reference = skill_dir / "references" / name
        assert reference.exists()
        assert f"references/{name}" in content
