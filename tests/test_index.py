"""Contract tests for the FTS5 search index.

Verifies: build_index creates a searchable database, search returns
matching results with expected structure.
Does NOT test: SQLite internals, exact ranking scores, hash logic.
"""

from __future__ import annotations

import json
import sqlite3

from scholaraio.services.index import build_index, lookup_paper, search, search_author, unified_search


class TestBuildAndSearch:
    """End-to-end index contract: build → search → results."""

    def test_build_then_search_by_title(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        results = search("turbulence", tmp_db)
        assert len(results) >= 1
        titles = [r["title"] for r in results]
        assert any("Turbulence" in t or "turbulence" in t for t in titles)

    def test_search_returns_expected_fields(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        results = search("turbulence", tmp_db)
        assert len(results) >= 1
        r = results[0]
        # Contract: search results contain at minimum these keys
        for key in ("paper_id", "title", "authors", "year", "journal"):
            assert key in r, f"Missing key: {key}"

    def test_search_no_match_returns_empty(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        results = search("xyznonexistent", tmp_db)
        assert results == []

    def test_search_punctuation_only_query_returns_empty(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)

        assert search("+++", tmp_db) == []

    def test_build_index_preserves_legacy_string_authors(self, tmp_path, tmp_db):
        papers_dir = tmp_path / "papers"
        paper_dir = papers_dir / "Doe-2026-LegacyAuthors"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "legacy-authors",
                    "title": "Legacy author metadata",
                    "authors": "Jane Doe",
                    "year": 2026,
                }
            ),
            encoding="utf-8",
        )

        build_index(papers_dir, tmp_db)

        assert [result["paper_id"] for result in search_author("Jane", tmp_db)] == ["legacy-authors"]
        with sqlite3.connect(tmp_db) as conn:
            assert conn.execute("SELECT authors FROM papers").fetchone()[0] == "Jane Doe"

    def test_search_by_abstract_content(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        results = search("novel turbulence model boundary", tmp_db)
        assert len(results) >= 1

    def test_rebuild_is_idempotent(self, tmp_papers, tmp_db):
        """Building twice should not duplicate entries."""
        build_index(tmp_papers, tmp_db)
        build_index(tmp_papers, tmp_db)
        results = search("turbulence", tmp_db)
        # Should still find exactly one match for this query, not duplicates
        turbulence_results = [r for r in results if "Turbulence" in r.get("title", "")]
        assert len(turbulence_results) == 1

    def test_build_index_accepts_reference_dicts(self, tmp_path, tmp_db):
        papers_dir = tmp_path / "papers"
        paper_dir = papers_dir / "Smith-2023-Turbulence"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "aaaa-1111",
                    "title": "Turbulence modeling in boundary layers",
                    "authors": ["Smith, John"],
                    "first_author_lastname": "Smith",
                    "year": 2023,
                    "journal": "Journal of Fluid Mechanics",
                    "doi": "10.1234/jfm.2023.001",
                    "abstract": "We propose a novel turbulence model for boundary layers.",
                    "paper_type": "journal-article",
                    "references": [
                        {"doi": "10.1000/classic"},
                        {"externalIds": {"DOI": "10.1000/second"}},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (paper_dir / "paper.md").write_text("# Turbulence\n\nFull text.", encoding="utf-8")

        build_index(papers_dir, tmp_db)

        with sqlite3.connect(tmp_db) as conn:
            rows = conn.execute(
                "SELECT target_doi FROM citations WHERE source_id = ? ORDER BY target_doi",
                ("aaaa-1111",),
            ).fetchall()
        assert [row[0] for row in rows] == ["10.1000/classic", "10.1000/second"]

    def test_search_applies_paper_ids_before_limit(self, tmp_path, tmp_db):
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()
        for index in range(6):
            paper_dir = papers_dir / f"A-{index:02d}-Decoy"
            paper_dir.mkdir()
            (paper_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "id": f"decoy-{index}",
                        "title": "Needle needle needle needle",
                        "authors": ["Decoy Author"],
                        "year": 2026,
                        "abstract": "needle " * 20,
                    }
                ),
                encoding="utf-8",
            )

        target_dir = papers_dir / "Z-Target"
        target_dir.mkdir()
        (target_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "target-paper",
                    "title": "A distant result",
                    "authors": ["Target Author"],
                    "year": 2026,
                    "abstract": "This record mentions needle once.",
                }
            ),
            encoding="utf-8",
        )

        build_index(papers_dir, tmp_db)
        unfiltered = search("needle", tmp_db, top_k=7)
        assert unfiltered[-1]["paper_id"] == "target-paper"

        results = search("needle", tmp_db, top_k=1, paper_ids={"target-paper"})

        assert [result["paper_id"] for result in results] == ["target-paper"]

    def test_unified_search_degrades_to_fts_when_vector_search_runtime_fails(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)

        def boom(*_args, **_kwargs):
            raise RuntimeError("proxy unavailable")

        monkeypatch.setattr("scholaraio.services.vectors.vsearch", boom)

        results = unified_search("turbulence", tmp_db)

        assert len(results) >= 1
        assert all(r["match"] == "fts" for r in results)

    def test_unified_search_return_diagnostics_reports_vector_degradation(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)

        def boom(*_args, **_kwargs):
            raise RuntimeError("proxy unavailable")

        monkeypatch.setattr("scholaraio.services.vectors.vsearch", boom)

        results, diagnostics = unified_search("turbulence", tmp_db, return_diagnostics=True)

        assert len(results) >= 1
        assert all(r["match"] == "fts" for r in results)
        assert diagnostics["keyword_degraded"] is False
        assert diagnostics["vector_degraded"] is True
        assert diagnostics["keyword_error"] == ""
        assert "proxy unavailable" in diagnostics["vector_error"]

    def test_unified_search_diagnostics_report_keyword_degradation(self, tmp_db, monkeypatch):
        def missing_keyword(*_args, **_kwargs):
            raise FileNotFoundError("keyword index missing")

        monkeypatch.setattr("scholaraio.services.index.search", missing_keyword)
        monkeypatch.setattr(
            "scholaraio.services.vectors.vsearch",
            lambda *_args, **_kwargs: [
                {
                    "paper_id": "vector-paper",
                    "title": "Vector result",
                    "authors": "A. Researcher",
                    "year": "2026",
                    "journal": "",
                    "score": 0.9,
                }
            ],
        )

        results, diagnostics = unified_search("vector", tmp_db, return_diagnostics=True)

        assert [result["paper_id"] for result in results] == ["vector-paper"]
        assert results[0]["match"] == "vec"
        assert diagnostics["keyword_degraded"] is True
        assert diagnostics["vector_degraded"] is False
        assert "keyword index missing" in diagnostics["keyword_error"]
        assert diagnostics["vector_error"] == ""

    def test_unified_search_diagnostics_report_both_legs_unavailable(self, tmp_db, monkeypatch):
        def missing_keyword(*_args, **_kwargs):
            raise FileNotFoundError("keyword index missing")

        def missing_vector(*_args, **_kwargs):
            raise FileNotFoundError("vector index missing")

        monkeypatch.setattr("scholaraio.services.index.search", missing_keyword)
        monkeypatch.setattr("scholaraio.services.vectors.vsearch", missing_vector)

        results, diagnostics = unified_search("missing", tmp_db, return_diagnostics=True)

        assert results == []
        assert diagnostics["keyword_degraded"] is True
        assert diagnostics["vector_degraded"] is True
        assert "keyword index missing" in diagnostics["keyword_error"]
        assert "vector index missing" in diagnostics["vector_error"]


class TestLookupPaper:
    """lookup_paper contract: find by UUID, dir_name, DOI, or publication_number."""

    def test_lookup_by_uuid(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        result = lookup_paper(tmp_db, "aaaa-1111")
        assert result is not None
        assert result["id"] == "aaaa-1111"

    def test_lookup_by_doi(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        result = lookup_paper(tmp_db, "10.1234/jfm.2023.001")
        assert result is not None
        assert result["doi"] == "10.1234/jfm.2023.001"

    def test_lookup_by_doi_is_backward_compatible_with_legacy_uppercase_registry(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            conn.execute("UPDATE papers_registry SET doi = UPPER(doi) WHERE doi != ''")
            conn.commit()

        result = lookup_paper(tmp_db, "10.1234/jfm.2023.001")
        assert result is not None
        assert result["id"] == "aaaa-1111"

    def test_lookup_by_publication_number(self, tmp_path, tmp_db):
        """Patent lookup normalizes to uppercase for matching."""
        papers_dir = tmp_path / "papers"
        pa = papers_dir / "Inventor-2023-Patent"
        pa.mkdir(parents=True)
        (pa / "meta.json").write_text(
            json.dumps(
                {
                    "id": "patent-001",
                    "title": "A patent invention",
                    "authors": ["Inventor"],
                    "first_author_lastname": "Inventor",
                    "year": 2023,
                    "journal": "",
                    "doi": "",
                    "abstract": "Patent abstract.",
                    "paper_type": "patent",
                    "ids": {"patent_publication_number": "CN112345678A"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (pa / "paper.md").write_text("# Patent\n\nContent.", encoding="utf-8")
        build_index(papers_dir, tmp_db)
        # Lookup with lowercase should still match (normalization)
        result = lookup_paper(tmp_db, "cn112345678a")
        assert result is not None
        assert result["id"] == "patent-001"

    def test_lookup_nonexistent_returns_none(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        assert lookup_paper(tmp_db, "nonexistent-id") is None


class TestIncrementalMutationContract:
    def test_external_rename_delete_and_reference_clear(self, tmp_path):
        import shutil

        root = tmp_path / "papers"
        root.mkdir()
        db = tmp_path / "index.db"
        for name, meta in {
            "source": {"id": "source", "title": "Source", "references": ["10.1234/target"]},
            "target": {"id": "target", "title": "Target", "doi": "10.1234/target"},
        }.items():
            (root / name).mkdir()
            (root / name / "meta.json").write_text(json.dumps(meta))
        build_index(root, db)
        (root / "source").rename(root / "renamed")
        build_index(root, db)
        assert lookup_paper(db, "source")["dir_name"] == "renamed"
        shutil.rmtree(root / "target")
        build_index(root, db)
        assert lookup_paper(db, "target") is None
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT target_id FROM citations").fetchone() == (None,)
        (root / "renamed" / "meta.json").write_text(json.dumps({"id": "source", "title": "Source"}))
        build_index(root, db)
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0] == 0

    def test_unreadable_record_preserves_last_good_index(self, tmp_path):
        root = tmp_path / "papers"
        paper = root / "record"
        paper.mkdir(parents=True)
        db = tmp_path / "index.db"
        (paper / "meta.json").write_text(json.dumps({"id": "p", "title": "Evidence"}))
        build_index(root, db)
        (paper / "meta.json").write_text("{broken")
        build_index(root, db)
        assert lookup_paper(db, "p")["title"] == "Evidence"


def test_failed_rebuild_preserves_previous_projection(tmp_path):
    import pytest

    root = tmp_path / "papers"
    (root / "one").mkdir(parents=True)
    db = tmp_path / "index.db"
    meta = json.dumps({"id": "one", "title": "Original"})
    (root / "one" / "meta.json").write_text(meta)
    build_index(root, db)
    (root / "duplicate").mkdir()
    (root / "duplicate" / "meta.json").write_text(meta)
    with pytest.raises(ValueError, match="Duplicate paper ID"):
        build_index(root, db, rebuild=True)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT title FROM papers").fetchall() == [("Original",)]
        assert conn.execute("SELECT id FROM papers_registry").fetchall() == [("one",)]


def test_application_write_refreshes_keyword_search_without_manual_index(tmp_path):
    from scholaraio.stores.papers import update_meta

    root = tmp_path / "papers"
    (root / "one").mkdir(parents=True)
    db = tmp_path / "index.db"
    (root / "one" / "meta.json").write_text(json.dumps({"id": "one", "title": "Original"}))
    build_index(root, db)
    update_meta(root / "one", title="Replacement")
    assert search("Replacement", db)[0]["paper_id"] == "one"
    assert search("Original", db) == []


def test_duplicate_doi_rebuild_rolls_back_every_projection(tmp_path):
    import pytest

    root = tmp_path / "papers"
    for name in ("a", "b"):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "meta.json").write_text(json.dumps({"id": name, "title": name, "doi": f"10.1234/{name}"}))
    db = tmp_path / "index.db"
    build_index(root, db)
    with sqlite3.connect(db) as conn:
        before = {
            table: conn.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("papers", "papers_registry", "papers_hash", "index_source")
        }
    (root / "a" / "meta.json").write_text(json.dumps({"id": "a", "title": "Changed", "doi": "10.1234/b"}))
    with pytest.raises(sqlite3.IntegrityError):
        build_index(root, db)
    with sqlite3.connect(db) as conn:
        for table, rows in before.items():
            assert conn.execute(f"SELECT * FROM {table}").fetchall() == rows


def test_pdf_and_markdown_saves_do_not_rebuild_metadata_index(tmp_path, monkeypatch):
    from scholaraio.services import index
    from scholaraio.stores.library_state import library_manifest

    directory = tmp_path / "papers" / "one"
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(json.dumps({"id": "one", "title": "Evidence"}))
    pdf, markdown = directory / "paper.pdf", directory / "paper.md"
    pdf.write_bytes(b"pdf before")
    markdown.write_text("before")
    db = tmp_path / "index.db"
    build_index(directory.parent, db)
    builds = []
    original = index.build_index

    def rebuild(*args, **kwargs):
        builds.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(index, "build_index", rebuild)
    pdf.write_bytes(b"annotation save")
    markdown.write_text("rewritten full text")
    library_manifest(directory.parent, force=True)
    assert search("Evidence", db)
    assert builds == []
    markdown.unlink()
    library_manifest(directory.parent, force=True)
    assert search("Evidence", db)
    assert builds == [True]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT md_path FROM papers").fetchone() == ("",)


def test_keyword_refresh_tolerates_nonfinite_citation_counts(tmp_path):
    from scholaraio.stores.papers import update_meta

    directory = tmp_path / "papers" / "one"
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(json.dumps({"id": "one", "title": "Evidence"}))
    db = tmp_path / "index.db"
    build_index(directory.parent, db)
    for value in (float("inf"), float("nan"), {"bad": float("inf"), "good": 12}):
        update_meta(directory, citation_count=value)
        assert search("Evidence", db)[0]["paper_id"] == "one"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT citation_count FROM papers").fetchone() == ("12",)
