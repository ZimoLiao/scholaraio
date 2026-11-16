"""Approximate host-routing smoke tests for writing skills.

These tests do not emulate Claude/Codex internals. They provide a small,
repeatable proxy for skill discovery by matching sample user prompts against
skill names and descriptions. The goal is to catch regressions where wording
changes make the intended writing skills much harder to discover.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".claude" / "skills"

PRIORITY_TOKENS = {
    "availability",
    "checklist",
    "figure",
    "journal",
    "nature",
    "poster",
    "polishing",
    "report",
    "briefing",
    "rebuttal",
    "slides",
    "ppt",
    "paper2ppt",
    "review",
    "section",
    "submission",
    "guided",
    "reading",
}

PHRASE_BONUSES = {
    "technical report": 4.0,
    "topic report": 4.0,
    "research briefing": 4.0,
    "conference poster": 4.0,
    "poster-style": 4.0,
    "paper section": 4.0,
    "response letter": 4.0,
    "guided reading": 4.0,
    "deep reading": 4.0,
    "single paper": 3.0,
    "nature figure": 4.0,
    "nature style": 4.0,
    "nature-style": 4.0,
    "paper-to-ppt": 4.0,
    "high-impact journal": 4.0,
    "high-impact journal major revision": 4.0,
    "nature communications": 4.0,
    "nature-specific academic-search": 4.0,
}


def _skill_corpus() -> dict[str, list[str]]:
    corpora: dict[str, list[str]] = {}
    for path in SKILLS_DIR.glob("*/SKILL.md"):
        text = path.read_text(encoding="utf-8")
        _, frontmatter, _body = text.split("---\n", 2)
        data = yaml.safe_load(frontmatter)
        name = data["name"]
        description = data.get("description", "")
        corpus = f"{name} {description}".lower()
        corpora[name] = re.findall(r"[a-z][a-z0-9-]+", corpus)
    return corpora


def _score(prompt: str, tokens: list[str]) -> float:
    prompt = prompt.lower()
    prompt_tokens = re.findall(r"[a-z][a-z0-9-]+", prompt)
    score = 0.0

    for token in prompt_tokens:
        if token in tokens:
            score += 2.5 if token in PRIORITY_TOKENS else 1.0
        for known in tokens:
            if token == known:
                continue
            if len(token) >= 4 and (token in known or known in token):
                score += 0.25
                break

    joined = " ".join(tokens)
    for phrase, bonus in PHRASE_BONUSES.items():
        if phrase in prompt and phrase in joined:
            score += bonus

    return score


def _top_skill(prompt: str) -> tuple[str, float]:
    corpora = _skill_corpus()
    ranked = sorted(((name, _score(prompt, tokens)) for name, tokens in corpora.items()), key=lambda x: (-x[1], x[0]))
    return ranked[0]


@pytest.mark.parametrize("skill_names", [("alpha", "omega"), ("omega", "alpha")])
def test_top_skill_breaks_ties_by_name(skill_names: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(globals(), "_skill_corpus", lambda: {name: ["report"] for name in skill_names})

    assert _top_skill("report") == ("alpha", 2.5)


def test_conference_poster_prompt_prefers_poster_skill() -> None:
    top_name, top_score = _top_skill("Help me make a conference poster from this workspace")

    assert top_name == "poster"
    assert top_score > 0


def test_technical_report_prompt_prefers_technical_report_skill() -> None:
    top_name, top_score = _top_skill("I need a technical report for my group meeting about this topic")

    assert top_name == "technical-report"
    assert top_score > 0


def test_workflow_uncertainty_prompt_prefers_academic_writing_router() -> None:
    top_name, top_score = _top_skill("I need a PPT for my advisor but I am not sure which writing workflow to use")

    assert top_name == "academic-writing"
    assert top_score > 0


def test_rebuttal_prompt_prefers_review_response_skill() -> None:
    top_name, top_score = _top_skill("Help me write a rebuttal letter to reviewer 2")

    assert top_name == "review-response"
    assert top_score > 0


def test_related_work_prompt_prefers_paper_writing_skill() -> None:
    top_name, top_score = _top_skill("Draft the related work section for my paper")

    assert top_name == "paper-writing"
    assert top_score > 0


def test_guided_single_paper_prompt_prefers_paper_guided_reading_skill() -> None:
    top_name, top_score = _top_skill("Help me do a guided deep reading of a single paper about turbulence")

    assert top_name == "paper-guided-reading"
    assert top_score > 0


def test_nature_submission_package_prompt_prefers_nature_workflow_router() -> None:
    top_name, top_score = _top_skill(
        "Prepare my Nature Communications submission package: abstract polish, figures, citations, and data availability"
    )

    assert top_name == "nature-workflow"
    assert top_score > 0


def test_high_impact_revision_prompt_prefers_nature_workflow_router() -> None:
    top_name, top_score = _top_skill("Plan a high-impact journal major revision response and submission checklist")

    assert top_name == "nature-workflow"
    assert top_score > 0


def test_data_availability_prompt_prefers_nature_workflow_router() -> None:
    top_name, top_score = _top_skill("Prepare a Data Availability statement for a Nature submission")

    assert top_name == "nature-workflow"
    assert top_score > 0


def test_nature_figure_prompt_prefers_nature_workflow_router() -> None:
    top_name, top_score = _top_skill("Make a Nature figure with Python from this result table")

    assert top_name == "nature-workflow"
    assert top_score > 0


def test_nature_polishing_prompt_prefers_nature_workflow_router() -> None:
    top_name, top_score = _top_skill("Use Nature-style polishing on this abstract")

    assert top_name == "nature-workflow"
    assert top_score > 0


def test_nature_paper2ppt_prompt_prefers_nature_workflow_router() -> None:
    top_name, top_score = _top_skill("Turn this paper into a Chinese journal-club PPT in Nature style")

    assert top_name == "nature-workflow"
    assert top_score > 0


def test_generic_prose_polish_stays_with_writing_polish_skill() -> None:
    top_name, top_score = _top_skill("Polish this manuscript paragraph for clarity without changing the claims")

    assert top_name == "writing-polish"
    assert top_score > 0


def test_generic_academic_search_stays_outside_nature_workflow() -> None:
    top_name, top_score = _top_skill("I need academic search for this literature review")

    assert top_name != "nature-workflow"
    assert top_score > 0


def test_generic_data_availability_stays_outside_nature_workflow() -> None:
    top_name, top_score = _top_skill("Prepare a Data Availability statement for this manuscript")

    assert top_name != "nature-workflow"
    assert top_score > 0


def test_nature_workflow_phrase_bonuses_are_not_unqualified_generic_triggers() -> None:
    for phrase in ("data availability", "academic search", "major revision", "submission package", "journal-club ppt"):
        assert phrase not in PHRASE_BONUSES
