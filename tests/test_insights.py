"""Tests for scholaraio.services.insights and the insights CLI surface."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import scholaraio.core.log as target_log
from scholaraio.interfaces.cli import compat as cli
from scholaraio.services import insights, metrics


def test_extract_hot_keywords_filters_stopwords_and_punctuation():
    events = [
        {"detail": json.dumps({"query": "Heat transfer in turbulent flow"})},
        {"detail": json.dumps({"query": "heat transfer via wall motion"})},
        {"detail": json.dumps({"query": "the heat, and transfer"})},
    ]

    hot = insights.extract_hot_keywords(events, top_k=3)

    assert hot[0] == ("heat", 3)
    assert hot[1] == ("transfer", 3)
    assert all(word not in {"the", "in", "via", "and"} for word, _ in hot)


def test_aggregate_most_read_titles_deduplicates_title_variants(tmp_path: Path):
    papers_dir = tmp_path / "papers"
    canonical = papers_dir / "Smith-2024-Heat-Transfer"
    canonical.mkdir(parents=True)
    (canonical / "meta.json").write_text(
        json.dumps({"title": "Heat Transfer in Turbulent Flow"}),
        encoding="utf-8",
    )

    events = [
        {"name": "Smith-2024-Heat-Transfer", "detail": ""},
        {"name": "paper-uuid-1", "detail": json.dumps({"title": "Heat Transfer in Turbulent Flow"})},
        {"name": "paper-uuid-1", "detail": json.dumps({"title": "Heat Transfer in Turbulent Flow"})},
    ]

    most_read = insights.aggregate_most_read_titles(events, papers_dir, top_k=5)

    assert most_read == [("Heat Transfer in Turbulent Flow", 3)]


def test_aggregate_most_read_titles_resolves_all_names_before_top_k(tmp_path: Path):
    papers_dir = tmp_path / "papers"
    for name, title in [
        ("variant-a", "Merged Title"),
        ("variant-b", "Merged Title"),
        ("variant-c", "Merged Title"),
        ("single-a", "Single A"),
        ("single-b", "Single B"),
    ]:
        paper_dir = papers_dir / name
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(json.dumps({"title": title}), encoding="utf-8")

    events = [
        {"name": "variant-a", "detail": ""},
        {"name": "variant-b", "detail": ""},
        {"name": "variant-c", "detail": ""},
        {"name": "single-a", "detail": ""},
        {"name": "single-a", "detail": ""},
        {"name": "single-b", "detail": ""},
        {"name": "single-b", "detail": ""},
    ]

    most_read = insights.aggregate_most_read_titles(events, papers_dir, top_k=2)

    assert most_read == [("Merged Title", 3), ("Single A", 2)]


def test_build_weekly_read_trend_groups_by_week():
    events = [
        {"timestamp": "2026-03-02T10:00:00+00:00"},
        {"timestamp": "2026-03-03T10:00:00+00:00"},
        {"timestamp": "2026-03-11T10:00:00+00:00"},
    ]

    trend = insights.build_weekly_read_trend(events)

    assert trend == [("2026-W10", 2), ("2026-W11", 1)]


def test_build_weekly_read_trend_uses_iso_week_year_at_boundary():
    events = [
        {"timestamp": "2021-01-01T10:00:00+00:00"},
        {"timestamp": "2021-01-04T10:00:00+00:00"},
    ]

    trend = insights.build_weekly_read_trend(events)

    assert trend == [("2020-W53", 1), ("2021-W01", 1)]


def test_cmd_insights_smoke_with_metrics_store(tmp_path: Path, monkeypatch):
    papers_dir = tmp_path / "papers"
    for name, title, abstract in [
        ("Paper-A", "Heat Transfer in Turbulent Flow", "wall motion and convection"),
        ("Paper-B", "Compliant Walls for Cooling", "heat transfer enhancement"),
        ("Paper-C", "Boundary-Layer Control", "adjacent turbulent structures"),
    ]:
        paper_dir = papers_dir / name
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(
            json.dumps({"title": title, "abstract": abstract}),
            encoding="utf-8",
        )

    ws_dir = tmp_path / "workspace" / "cooling-study"
    (ws_dir / "refs").mkdir(parents=True)
    (ws_dir / "refs" / "papers.json").write_text(json.dumps(["Paper-A", "Paper-B"]), encoding="utf-8")

    store = metrics.init(tmp_path / "metrics.db", "test-session")
    store.record("search", "usearch", detail={"query": "heat transfer wall motion"})
    store.record("search", "usearch", detail={"query": "turbulent heat transfer"})
    store.record("read", "Paper-A", detail={"title": "Heat Transfer in Turbulent Flow"})
    store.record("read", "Paper-A", detail={"title": "Heat Transfer in Turbulent Flow"})

    messages: list[str] = []
    monkeypatch.setattr(target_log, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(
        "scholaraio.services.vectors.vsearch",
        lambda query, db_path, top_k, cfg: [
            {"dir_name": "Paper-B", "score": 0.93},
            {"dir_name": "Paper-C", "score": 0.81},
            {"dir_name": "Paper-A", "score": 0.99},
        ],
    )

    cfg = SimpleNamespace(_root=tmp_path, papers_dir=papers_dir, index_db=tmp_path / "index.db")

    try:
        cli.cmd_insights(Namespace(days=30), cfg)
    finally:
        metrics.reset()

    joined = "\n".join(messages)
    assert "Research behavior analytics (last 30 days)" in joined
    assert "【Top 10 search terms】" in joined
    assert "【Top 10 most-read papers】" in joined
    assert "Heat Transfer in Turbulent Flow" in joined
    assert "Compliant Walls for Cooling" in joined
    assert "【Active workspaces】" in joined
    assert "cooling-study" in joined


def test_cmd_insights_uses_configured_workspace_dir(tmp_path: Path, monkeypatch):
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "Paper-A"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(
        json.dumps({"title": "Heat Transfer in Turbulent Flow", "abstract": "wall motion and convection"}),
        encoding="utf-8",
    )

    custom_ws = tmp_path / "projects" / "cooling-study"
    (custom_ws / "refs").mkdir(parents=True)
    (custom_ws / "refs" / "papers.json").write_text(json.dumps(["Paper-A"]), encoding="utf-8")

    legacy_ws = tmp_path / "workspace" / "legacy-study"
    (legacy_ws / "refs").mkdir(parents=True)
    (legacy_ws / "refs" / "papers.json").write_text(json.dumps(["Paper-A", "Paper-A"]), encoding="utf-8")

    store = metrics.init(tmp_path / "metrics.db", "test-session")
    store.record("search", "usearch", detail={"query": "heat transfer"})
    store.record("read", "Paper-A", detail={"title": "Heat Transfer in Turbulent Flow"})

    messages: list[str] = []
    monkeypatch.setattr(target_log, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr("scholaraio.services.vectors.vsearch", lambda query, db_path, top_k, cfg: [])

    cfg = SimpleNamespace(
        _root=tmp_path,
        papers_dir=papers_dir,
        index_db=tmp_path / "index.db",
        workspace_dir=tmp_path / "projects",
    )

    try:
        cli.cmd_insights(Namespace(days=30), cfg)
    finally:
        metrics.reset()

    joined = "\n".join(messages)
    assert "cooling-study" in joined
    assert "legacy-study" not in joined


def test_cmd_insights_supports_future_workspace_refs_layout(tmp_path: Path, monkeypatch):
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "Paper-A"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(
        json.dumps({"title": "Heat Transfer in Turbulent Flow", "abstract": "wall motion and convection"}),
        encoding="utf-8",
    )

    future_ws = tmp_path / "projects" / "future-study" / "refs"
    future_ws.mkdir(parents=True)
    (future_ws / "papers.json").write_text(json.dumps(["Paper-A"]), encoding="utf-8")

    store = metrics.init(tmp_path / "metrics.db", "test-session")
    store.record("search", "usearch", detail={"query": "heat transfer"})
    store.record("read", "Paper-A", detail={"title": "Heat Transfer in Turbulent Flow"})

    messages: list[str] = []
    monkeypatch.setattr(target_log, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr("scholaraio.services.vectors.vsearch", lambda query, db_path, top_k, cfg: [])

    cfg = SimpleNamespace(
        _root=tmp_path,
        papers_dir=papers_dir,
        index_db=tmp_path / "index.db",
        workspace_dir=tmp_path / "projects",
    )

    try:
        cli.cmd_insights(Namespace(days=30), cfg)
    finally:
        metrics.reset()

    joined = "\n".join(messages)
    assert "future-study" in joined
