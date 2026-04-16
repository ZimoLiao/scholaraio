"""Approximate host-routing smoke tests for writing skills.

These tests do not emulate Claude/Codex internals. They provide a small,
repeatable proxy for skill discovery by matching sample user prompts against
skill names and descriptions. The goal is to catch regressions where wording
changes make the intended writing skills much harder to discover.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".claude" / "skills"

PRIORITY_TOKENS = {
    "poster",
    "report",
    "briefing",
    "rebuttal",
    "slides",
    "ppt",
    "review",
    "section",
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
    ranked = sorted(
        ((name, _score(prompt, tokens)) for name, tokens in corpora.items()), key=lambda x: x[1], reverse=True
    )
    return ranked[0]


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
