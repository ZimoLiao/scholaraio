from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scholaraio.core.config import _build_config
from scholaraio.services.index import build_index
from scholaraio.services.library_search import (
    MAX_LIBRARY_SEARCH_RESULTS,
    LibrarySearchFilters,
    LibrarySearchRequestError,
    search_main_library,
)


def _write_paper(
    papers_dir: Path,
    dir_name: str,
    *,
    paper_id: str,
    title: str,
    authors: list[str],
    year: int,
    journal: str,
    doi: str,
    paper_type: str = "journal-article",
    abstract: str = "",
) -> None:
    paper_dir = papers_dir / dir_name
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": paper_id,
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "doi": doi,
                "paper_type": paper_type,
                "abstract": abstract,
            }
        ),
        encoding="utf-8",
    )


def test_library_search_filters_compose_before_keyword_retrieval(tmp_path, monkeypatch):
    cfg = _build_config({}, tmp_path)
    _write_paper(
        cfg.papers_dir,
        "Doe-2024-Target",
        paper_id="target-paper",
        title="Turbulence closure for reacting flows",
        authors=["Jane Doe", "Alex Roe"],
        year=2024,
        journal="Journal of Fluid Mechanics",
        doi="10.1000/target",
        paper_type="JournalArticle",
    )
    _write_paper(
        cfg.papers_dir,
        "Doe-2018-Old",
        paper_id="old-paper",
        title="Turbulence closure for reacting flows",
        authors=["Jane Doe"],
        year=2018,
        journal="Journal of Fluid Mechanics",
        doi="10.1000/old",
    )
    _write_paper(
        cfg.papers_dir,
        "Smith-2024-Other",
        paper_id="other-paper",
        title="Turbulence closure for reacting flows",
        authors=["Sam Smith"],
        year=2024,
        journal="Journal of Fluid Mechanics",
        doi="10.1000/other",
    )
    captured: dict[str, object] = {}

    def fake_search(query, db_path, top_k, cfg, **kwargs):
        captured.update(query=query, db_path=db_path, top_k=top_k, cfg=cfg, **kwargs)
        return [
            {
                "paper_id": "target-paper",
                "title": "Turbulence closure for reacting flows",
                "authors": "Jane Doe, Alex Roe",
                "year": "2024",
                "journal": "Journal of Fluid Mechanics",
            }
        ]

    monkeypatch.setattr("scholaraio.services.index.search", fake_search)
    filters = LibrarySearchFilters.from_strings(
        title="reacting",
        author="JANE DOE",
        year_from="2020",
        year_to="2026",
        journal="fluid mechanics",
        paper_type="journal-article",
        doi="10.1000/tar",
    )

    response = search_main_library(cfg, query="closure", mode="keyword", filters=filters, limit=50)

    assert captured["paper_ids"] == {"target-paper"}
    assert captured["year"] == "2020-2026"
    assert captured["journal"] == "fluid mechanics"
    assert captured["paper_type"] == "journal-article"
    assert response["results"] == [
        {
            "paper_id": "target-paper",
            "rank": 1,
            "score": 1.0,
            "match": "keyword",
            "title": "Turbulence closure for reacting flows",
            "authors": "Jane Doe, Alex Roe",
            "year": "2024",
            "journal": "Journal of Fluid Mechanics",
            "dir_name": "Doe-2024-Target",
        }
    ]
    assert response["diagnostics"]["status"] == "ok"


def test_library_search_validates_years_modes_queries_and_limits(tmp_path, monkeypatch):
    cfg = _build_config({}, tmp_path)
    _write_paper(
        cfg.papers_dir,
        "Doe-2024-Target",
        paper_id="target-paper",
        title="Target",
        authors=["Jane Doe"],
        year=2024,
        journal="Journal",
        doi="10.1000/target",
    )

    with pytest.raises(LibrarySearchRequestError, match="year_from") as invalid_year:
        LibrarySearchFilters.from_strings(year_from="twenty")
    assert invalid_year.value.code == "invalid_year"

    with pytest.raises(LibrarySearchRequestError, match="before") as invalid_range:
        LibrarySearchFilters.from_strings(year_from="2026", year_to="2020")
    assert invalid_range.value.code == "invalid_year_range"

    with pytest.raises(LibrarySearchRequestError, match="mode") as invalid_mode:
        search_main_library(cfg, query="target", mode="metadata")
    assert invalid_mode.value.code == "invalid_search_mode"

    with pytest.raises(LibrarySearchRequestError, match="query") as blank_query:
        search_main_library(cfg, query="  ", mode="keyword")
    assert blank_query.value.code == "missing_search_query"

    with pytest.raises(LibrarySearchRequestError, match="positive") as invalid_limit:
        search_main_library(cfg, query="target", mode="keyword", limit=0)
    assert invalid_limit.value.code == "invalid_search_limit"

    captured: dict[str, int] = {}

    def fake_search(_query, _db_path, top_k, cfg, **_kwargs):
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr("scholaraio.services.index.search", fake_search)
    search_main_library(cfg, query="target", mode="keyword", limit=10_000)
    assert captured["top_k"] == MAX_LIBRARY_SEARCH_RESULTS


@pytest.mark.parametrize(
    ("mode", "service_name", "service_result", "expected_match"),
    [
        (
            "keyword",
            "scholaraio.services.index.search",
            [{"paper_id": "target-paper", "title": "Target"}],
            "keyword",
        ),
        (
            "semantic",
            "scholaraio.services.vectors.vsearch",
            [{"paper_id": "target-paper", "title": "Target", "score": 0.91}],
            "semantic",
        ),
    ],
)
def test_library_search_calls_requested_service_directly(
    tmp_path,
    monkeypatch,
    mode,
    service_name,
    service_result,
    expected_match,
):
    cfg = _build_config({}, tmp_path)
    _write_paper(
        cfg.papers_dir,
        "Doe-2024-Target",
        paper_id="target-paper",
        title="Target",
        authors=["Jane Doe"],
        year=2024,
        journal="Journal",
        doi="10.1000/target",
    )
    calls: list[dict] = []

    def fake_service(query, db_path, top_k, cfg, **kwargs):
        calls.append({"query": query, "db_path": db_path, "top_k": top_k, "cfg": cfg, **kwargs})
        return service_result

    monkeypatch.setattr(service_name, fake_service)

    response = search_main_library(cfg, query="target", mode=mode)

    assert len(calls) == 1
    assert calls[0]["db_path"] == cfg.index_db
    assert calls[0]["paper_ids"] == {"target-paper"}
    assert response["results"][0]["match"] == expected_match
    assert response["results"][0]["rank"] == 1
    assert isinstance(response["results"][0]["score"], float)


@pytest.mark.parametrize("mode", ["semantic", "unified"])
def test_filtered_vector_modes_use_live_metadata_without_fts_table(tmp_path, monkeypatch, mode):
    cfg = _build_config({}, tmp_path)
    _write_paper(
        cfg.papers_dir,
        "Doe-2024-Target",
        paper_id="target-paper",
        title="Target turbulence model",
        authors=["Jane Doe"],
        year=2024,
        journal="Journal of Fluid Mechanics",
        doi="10.1000/target",
        paper_type="JournalArticle",
    )
    cfg.index_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(cfg.index_db) as conn:
        conn.execute(
            "CREATE TABLE paper_vectors (paper_id TEXT PRIMARY KEY, embedding BLOB NOT NULL, content_hash TEXT)"
        )
        conn.execute(
            "INSERT INTO paper_vectors (paper_id, embedding, content_hash) VALUES (?, ?, ?)",
            ("target-paper", b"\x00\x00\x00\x00", ""),
        )

    class FakeIndex:
        ntotal = 1

        def search(self, _query_vector, fetch_k):
            return (
                [[0.9][:fetch_k]],
                [[0][:fetch_k]],
            )

    monkeypatch.setattr(
        "scholaraio.services.vectors._embed_query_vector",
        lambda _query, _cfg=None: [[1.0, 0.0]],
    )
    monkeypatch.setattr(
        "scholaraio.services.vectors._build_faiss_index",
        lambda _db_path: (FakeIndex(), ["target-paper"]),
    )

    response = search_main_library(
        cfg,
        query="turbulence",
        mode=mode,
        filters=LibrarySearchFilters.from_strings(
            year_from="2020",
            journal="fluid mechanics",
            paper_type="journal-article",
        ),
    )

    assert [result["paper_id"] for result in response["results"]] == ["target-paper"]
    assert response["diagnostics"]["semantic"] == "available"


def test_library_search_unified_reports_vector_degradation(tmp_path, monkeypatch):
    cfg = _build_config({}, tmp_path)
    _write_paper(
        cfg.papers_dir,
        "Doe-2024-Target",
        paper_id="target-paper",
        title="Target",
        authors=["Jane Doe"],
        year=2024,
        journal="Journal",
        doi="10.1000/target",
    )

    monkeypatch.setattr(
        "scholaraio.services.index.unified_search",
        lambda *_args, **_kwargs: (
            [{"paper_id": "target-paper", "title": "Target", "score": 0.03, "match": "fts"}],
            {
                "keyword_degraded": False,
                "vector_degraded": True,
                "keyword_error": "",
                "vector_error": "Vector index does not exist",
            },
        ),
    )

    response = search_main_library(cfg, query="target", mode="unified")

    assert response["results"][0]["match"] == "keyword"
    assert response["diagnostics"]["status"] == "degraded"
    assert response["diagnostics"]["keyword"] == "available"
    assert response["diagnostics"]["semantic"] == "unavailable"
    assert {action["command"] for action in response["diagnostics"]["actions"]} == {"scholaraio embed"}


@pytest.mark.parametrize(
    ("mode", "service_name", "error", "command"),
    [
        ("keyword", "scholaraio.services.index.search", "Index file does not exist", "scholaraio index --rebuild"),
        ("semantic", "scholaraio.services.vectors.vsearch", "Vector index is empty", "scholaraio embed"),
    ],
)
def test_library_search_returns_actionable_unavailable_diagnostics(
    tmp_path,
    monkeypatch,
    mode,
    service_name,
    error,
    command,
):
    cfg = _build_config({}, tmp_path)
    _write_paper(
        cfg.papers_dir,
        "Doe-2024-Target",
        paper_id="target-paper",
        title="Target",
        authors=["Jane Doe"],
        year=2024,
        journal="Journal",
        doi="10.1000/target",
    )

    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError(error)

    monkeypatch.setattr(service_name, unavailable)

    response = search_main_library(cfg, query="target", mode=mode)

    assert response["results"] == []
    assert response["diagnostics"]["status"] == "unavailable"
    assert command in {action["command"] for action in response["diagnostics"]["actions"]}
    assert str(tmp_path) not in response["diagnostics"]["message"]


def test_library_search_unified_reports_both_legs_unavailable(tmp_path, monkeypatch):
    cfg = _build_config({}, tmp_path)
    _write_paper(
        cfg.papers_dir,
        "Doe-2024-Target",
        paper_id="target-paper",
        title="Target",
        authors=["Jane Doe"],
        year=2024,
        journal="Journal",
        doi="10.1000/target",
    )
    monkeypatch.setattr(
        "scholaraio.services.index.unified_search",
        lambda *_args, **_kwargs: (
            [],
            {
                "keyword_degraded": True,
                "vector_degraded": True,
                "keyword_error": "index missing",
                "vector_error": "vectors missing",
            },
        ),
    )

    response = search_main_library(cfg, query="target", mode="unified")

    assert response["diagnostics"]["status"] == "unavailable"
    assert {action["command"] for action in response["diagnostics"]["actions"]} == {
        "scholaraio index --rebuild",
        "scholaraio embed",
    }


def test_library_search_real_index_matches_library_stable_id(tmp_path):
    cfg = _build_config({}, tmp_path)
    _write_paper(
        cfg.papers_dir,
        "Doe-2024-Target",
        paper_id="target-paper",
        title="Turbulence closure for reacting flows",
        authors=["Jane Doe"],
        year=2024,
        journal="Journal of Fluid Mechanics",
        doi="10.1000/target",
        paper_type="JournalArticle",
        abstract="A unique flamelet closure marker.",
    )
    _write_paper(
        cfg.papers_dir,
        "Smith-2018-Decoy",
        paper_id="decoy-paper",
        title="Unrelated mechanics",
        authors=["Sam Smith"],
        year=2018,
        journal="Other Journal",
        doi="10.1000/decoy",
        abstract="No matching terminology.",
    )
    cfg.index_db.parent.mkdir(parents=True, exist_ok=True)
    build_index(cfg.papers_dir, cfg.index_db, rebuild=True)

    response = search_main_library(
        cfg,
        query="flamelet",
        mode="keyword",
        filters=LibrarySearchFilters.from_strings(
            author="doe",
            year_from="2020",
            paper_type="journal-article",
        ),
    )

    assert [result["paper_id"] for result in response["results"]] == ["target-paper"]
    assert response["diagnostics"]["status"] == "ok"


def test_semantic_results_describe_current_metadata_even_with_stale_vectors(tmp_path, monkeypatch):
    cfg = _build_config({}, tmp_path)
    _write_paper(
        cfg.papers_dir,
        "renamed",
        paper_id="paper",
        title="Current title",
        authors=["Current author"],
        year=2026,
        journal="",
        doi="",
    )
    monkeypatch.setattr(
        "scholaraio.services.vectors.vsearch",
        lambda *args, **kwargs: [
            {
                "paper_id": "paper",
                "title": "Old title",
                "authors": "Old author",
                "year": 2020,
                "journal": "Removed journal",
                "dir_name": "old-directory",
                "score": 0.91,
            }
        ],
    )
    response = search_main_library(cfg, query="research", mode="semantic")
    result = response["results"][0]
    assert result["title"] == "Current title"
    assert result["authors"] == "Current author"
    assert result["year"] == "2026"
    assert result["journal"] == ""
    assert result["dir_name"] == "renamed"
    assert result["score"] == 0.91
