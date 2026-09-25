"""Contract tests for papers.py — path helpers, scrub markers, and iteration.

Verifies: directory iteration yields only valid paper dirs, path helpers
compose correctly.
Does NOT test: UUID generation randomness, internal sorting.
"""

from __future__ import annotations

from scholaraio.stores.papers import (
    best_citation,
    is_review_only_journal,
    is_scrubbed,
    iter_paper_dirs,
    mark_scrubbed,
    md_path,
    meta_path,
    normalize_paper_type,
    paper_dir,
    read_meta,
    scrub_marker_path,
    write_meta,
)


class TestPathHelpers:
    """Path composition contract."""

    def test_paper_dir_joins_correctly(self, tmp_papers):
        result = paper_dir(tmp_papers, "Smith-2023-Turbulence")
        assert result == tmp_papers / "Smith-2023-Turbulence"

    def test_meta_path(self, tmp_papers):
        result = meta_path(tmp_papers, "Smith-2023-Turbulence")
        assert result.name == "meta.json"
        assert result.exists()

    def test_md_path(self, tmp_papers):
        result = md_path(tmp_papers, "Smith-2023-Turbulence")
        assert result.name == "paper.md"
        assert result.exists()


class TestIterPaperDirs:
    """Iteration contract: yields dirs with meta.json, skips others."""

    def test_yields_valid_paper_dirs(self, tmp_papers):
        dirs = list(iter_paper_dirs(tmp_papers))
        names = [d.name for d in dirs]
        assert "Smith-2023-Turbulence" in names
        assert "Wang-2024-DeepLearning" in names

    def test_skips_dirs_without_meta(self, tmp_papers):
        # Create a directory without meta.json
        (tmp_papers / "orphan-dir").mkdir()
        dirs = list(iter_paper_dirs(tmp_papers))
        names = [d.name for d in dirs]
        assert "orphan-dir" not in names

    def test_nonexistent_dir_yields_nothing(self, tmp_path):
        dirs = list(iter_paper_dirs(tmp_path / "nonexistent"))
        assert dirs == []


class TestCitationHelpers:
    """Citation-count compatibility contract."""

    def test_best_citation_accepts_legacy_scalar_count(self):
        assert best_citation({"citation_count": 7}) == 7

    def test_best_citation_accepts_dict_counts(self):
        assert best_citation({"citation_count": {"crossref": 3, "semantic_scholar": 11}}) == 11


class TestPaperTypeNormalization:
    def test_normalizes_journal_and_book_aliases(self):
        assert normalize_paper_type("jour") == "journal-article"
        assert normalize_paper_type("JournalArticle") == "journal-article"
        assert normalize_paper_type("monograph") == "book"

    def test_review_only_journals_override_generic_article_type(self):
        assert normalize_paper_type("journal-article", "Annual Review of Fluid Mechanics") == "review"
        assert normalize_paper_type("jour", "Nature Reviews Physics") == "review"
        assert normalize_paper_type("journal-article", "Reviews of Modern Physics") == "review"

    def test_review_detection_is_conservative(self):
        assert is_review_only_journal("Reviews of Geophysics") is True
        assert is_review_only_journal("Physical Review Letters") is False
        assert normalize_paper_type("journal-article", "Physical Review Letters") == "journal-article"

    def test_explicit_specialized_type_survives_review_venue_inference(self):
        for paper_type in ("editorial", "correction", "book-chapter", "posted-content"):
            assert normalize_paper_type(paper_type, "Nature Reviews Physics") == paper_type

    def test_missing_type_with_journal_and_doi_is_a_journal_article(self):
        assert normalize_paper_type("", "SIAM Journal on Mathematical Analysis", "10.1137/example") == (
            "journal-article"
        )

    def test_write_meta_persists_canonical_type(self, tmp_path):
        paper_d = tmp_path / "Paper"
        paper_d.mkdir()

        write_meta(
            paper_d,
            {
                "title": "A Review",
                "journal": "Annual Review of Fluid Mechanics",
                "paper_type": "jour",
            },
        )

        assert read_meta(paper_d)["paper_type"] == "review"


class TestScrubMarkers:
    """Scrub marker contract: papers can be marked as reviewed incrementally."""

    def test_is_scrubbed_false_when_marker_missing(self, tmp_path):
        paper_d = tmp_path / "Paper"
        paper_d.mkdir()

        assert is_scrubbed(paper_d) is False

    def test_mark_scrubbed_creates_marker(self, tmp_path):
        paper_d = tmp_path / "Paper"
        paper_d.mkdir()

        mark_scrubbed(paper_d)

        assert scrub_marker_path(paper_d) == paper_d / ".scrubbed"
        assert scrub_marker_path(paper_d).exists()
        assert is_scrubbed(paper_d) is True

    def test_mark_scrubbed_is_idempotent(self, tmp_path):
        paper_d = tmp_path / "Paper"
        paper_d.mkdir()

        mark_scrubbed(paper_d)
        mark_scrubbed(paper_d)

        assert scrub_marker_path(paper_d).exists()
        assert is_scrubbed(paper_d) is True


def test_metadata_array_is_a_repairable_validation_error(tmp_path):
    import pytest

    from scholaraio.stores.papers import read_meta

    (tmp_path / "meta.json").write_text("[]")
    with pytest.raises(ValueError, match="JSON object"):
        read_meta(tmp_path)
