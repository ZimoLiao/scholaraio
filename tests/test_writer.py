"""Tests for scholaraio.ingest.metadata._writer — filename generation, sanitization."""

from __future__ import annotations

import json

from scholaraio.ingest.metadata._models import PaperMetadata
from scholaraio.ingest.metadata._writer import (
    _clean_title_for_filename,
    _sanitize_for_filename,
    _strip_diacritics,
    generate_new_stem,
    metadata_to_dict,
    refetch_metadata,
    rename_paper,
)


class TestStripDiacritics:
    def test_spanish(self):
        assert _strip_diacritics("Jiménez") == "Jimenez"

    def test_french(self):
        assert _strip_diacritics("François") == "Francois"

    def test_german(self):
        assert _strip_diacritics("Müller") == "Muller"

    def test_no_diacritics(self):
        assert _strip_diacritics("Smith") == "Smith"

    def test_chinese_preserved(self):
        assert _strip_diacritics("王明") == "王明"


class TestCleanTitleForFilename:
    def test_remove_latex_inline(self):
        assert "$" not in _clean_title_for_filename("The $\\alpha$-test")

    def test_remove_latex_commands(self):
        result = _clean_title_for_filename("Study of \\textit{turbulence}")
        assert "\\" not in result

    def test_empty_title(self):
        assert _clean_title_for_filename("") == "Untitled"

    def test_normal_title(self):
        assert _clean_title_for_filename("A Simple Title") == "A Simple Title"

    def test_html_entities_decoded(self):
        # Zotero may export braces as HTML entities
        result = _clean_title_for_filename("La&#x007B;BH&#x007D;8")
        assert "&#x" not in result
        assert "{" not in result

    def test_nested_latex_braces(self):
        # Issue #32: Zotero APS titles with nested LaTeX
        title = r"$\mathrm{La}{\mathrm{BH}}_8$: Towards high-${T}_c$ low-pressure superconductivity"
        result = _clean_title_for_filename(title)
        assert "$" not in result
        assert "\\" not in result
        assert "{" not in result

    def test_mathml_tags_removed(self):
        result = _clean_title_for_filename(
            '<mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML">x</mml:math> study'
        )
        assert "<" not in result
        assert "mml" not in result


class TestSanitizeForFilename:
    def test_spaces_to_hyphens(self):
        assert _sanitize_for_filename("hello world") == "hello-world"

    def test_special_chars_removed(self):
        result = _sanitize_for_filename("A & B: Test!")
        assert "&" not in result
        assert ":" not in result
        assert "!" not in result

    def test_multiple_hyphens_collapsed(self):
        assert "---" not in _sanitize_for_filename("a---b")

    def test_trailing_hyphens_stripped(self):
        result = _sanitize_for_filename("-hello-")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_chinese_preserved(self):
        result = _sanitize_for_filename("王-2024-标题")
        assert "王" in result
        assert "标题" in result

    def test_truncate_long_filename(self):
        long_text = "A-" * 200  # 400 chars, well over 255 bytes
        result = _sanitize_for_filename(long_text)
        assert len(result.encode("utf-8")) <= 255

    def test_truncate_preserves_chinese(self):
        # Chinese chars are 3 bytes each in UTF-8
        text = "王-2024-" + "测试" * 100
        result = _sanitize_for_filename(text)
        assert len(result.encode("utf-8")) <= 255
        # Should not end with a partial character
        result.encode("utf-8").decode("utf-8")  # should not raise


class TestGenerateNewStem:
    def test_normal(self):
        meta = PaperMetadata(
            first_author_lastname="Smith",
            year=2023,
            title="Turbulence Modeling",
        )
        stem = generate_new_stem(meta)
        assert stem == "Smith-2023-Turbulence-Modeling"

    def test_no_author(self):
        meta = PaperMetadata(year=2023, title="Test")
        stem = generate_new_stem(meta)
        assert stem.startswith("Unknown-")

    def test_no_year(self):
        meta = PaperMetadata(first_author_lastname="Smith", title="Test")
        stem = generate_new_stem(meta)
        assert "XXXX" in stem

    def test_diacritics_stripped(self):
        meta = PaperMetadata(
            first_author_lastname="Jiménez",
            year=2020,
            title="Flow",
        )
        stem = generate_new_stem(meta)
        assert "Jimenez" in stem
        assert "é" not in stem

    def test_latex_in_title(self):
        meta = PaperMetadata(
            first_author_lastname="Smith",
            year=2023,
            title="The $\\alpha$-$\\beta$ Test",
        )
        stem = generate_new_stem(meta)
        assert "$" not in stem

    def test_issue32_zotero_latex_title(self):
        """Issue #32: Zotero APS title with LaTeX causes filename too long."""
        meta = PaperMetadata(
            first_author_lastname="Song",
            year=2023,
            title=r"$\mathrm{La}{\mathrm{BH}}_8$: Towards high-${T}_c$ low-pressure superconductivity in ternary superhydrides",
        )
        stem = generate_new_stem(meta)
        # 251 bytes for stem + 4 reserved for collision suffix (e.g. "-99")
        assert len(stem.encode("utf-8")) <= 251
        assert "$" not in stem
        assert "\\" not in stem
        assert "{" not in stem

    def test_extreme_long_title(self):
        meta = PaperMetadata(
            first_author_lastname="Smith",
            year=2023,
            title="Word " * 100,
        )
        stem = generate_new_stem(meta)
        assert len(stem.encode("utf-8")) <= 251

    def test_chinese_title(self):
        meta = PaperMetadata(
            first_author_lastname="王",
            year=2024,
            title="流体力学研究",
        )
        stem = generate_new_stem(meta)
        assert "王" in stem
        assert "流体力学研究" in stem


class TestMetadataToDict:
    def test_basic_fields(self):
        meta = PaperMetadata(
            id="test-uuid",
            title="Test Paper",
            authors=["Smith"],
            year=2023,
            doi="10.1234/test",
        )
        d = metadata_to_dict(meta)
        assert d["id"] == "test-uuid"
        assert d["title"] == "Test Paper"
        assert d["authors"] == ["Smith"]
        assert d["year"] == 2023
        assert d["ids"]["doi"] == "10.1234/test"

    def test_citation_counts(self):
        meta = PaperMetadata(
            citation_count_crossref=10,
            citation_count_s2=15,
            citation_count_openalex=12,
        )
        d = metadata_to_dict(meta)
        assert d["citation_count"]["crossref"] == 10
        assert d["citation_count"]["semantic_scholar"] == 15
        assert d["citation_count"]["openalex"] == 12

    def test_no_citation_counts(self):
        meta = PaperMetadata()
        d = metadata_to_dict(meta)
        assert d["citation_count"] == {}

    def test_ids_populated(self):
        meta = PaperMetadata(
            doi="10.1234/test",
            s2_paper_id="abc123",
            openalex_id="https://openalex.org/W123",
        )
        d = metadata_to_dict(meta)
        assert d["ids"]["doi"] == "10.1234/test"
        assert d["ids"]["semantic_scholar"] == "abc123"
        assert "openalex" in d["ids"]

    def test_empty_ids(self):
        meta = PaperMetadata()
        d = metadata_to_dict(meta)
        assert d["ids"] == {}


class TestRenamePaper:
    def test_rename_changes_dir(self, tmp_path):
        papers = tmp_path / "papers"
        old_dir = papers / "old-name"
        old_dir.mkdir(parents=True)
        meta = {
            "id": "test-uuid",
            "title": "New Title",
            "first_author_lastname": "Smith",
            "year": 2023,
        }
        (old_dir / "meta.json").write_text(json.dumps(meta))
        (old_dir / "paper.md").write_text("content")

        result = rename_paper(old_dir / "meta.json")
        assert result is not None
        assert "Smith-2023" in result.parent.name

    def test_rename_no_change(self, tmp_path):
        papers = tmp_path / "papers"
        correct_dir = papers / "Smith-2023-Test"
        correct_dir.mkdir(parents=True)
        meta = {
            "title": "Test",
            "first_author_lastname": "Smith",
            "year": 2023,
        }
        (correct_dir / "meta.json").write_text(json.dumps(meta))
        result = rename_paper(correct_dir / "meta.json")
        assert result is None  # no change needed


class TestRefetchMetadata:
    def test_refetch_persists_year_only_change(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Zhang-2021-Test"
        paper_dir.mkdir(parents=True)
        json_path = paper_dir / "meta.json"
        json_path.write_text(
            json.dumps(
                {
                    "id": "paper-1",
                    "title": "Test Paper",
                    "authors": ["Alice Smith"],
                    "first_author": "Alice Smith",
                    "first_author_lastname": "Smith",
                    "year": 2021,
                    "doi": "",
                    "journal": "",
                    "abstract": "Old abstract",
                    "paper_type": "preprint",
                    "citation_count": {"semantic_scholar": 0},
                    "ids": {"arxiv": "2603.25200"},
                    "api_sources": ["semantic_scholar"],
                    "references": [],
                }
            ),
            encoding="utf-8",
        )

        def fake_enrich(meta):
            meta.year = 2026
            return meta

        monkeypatch.setattr("scholaraio.ingest.metadata._api.enrich_metadata", fake_enrich)

        changed = refetch_metadata(json_path)

        assert changed is True
        meta_files = list((tmp_path / "papers").glob("*/meta.json"))
        assert len(meta_files) == 1
        data = json.loads(meta_files[0].read_text(encoding="utf-8"))
        assert data["year"] == 2026

    def test_refetch_keeps_existing_api_state_when_all_lookups_fail(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2024-Test-Paper"
        paper_dir.mkdir(parents=True)
        json_path = paper_dir / "meta.json"
        original = {
            "id": "paper-1",
            "title": "Test Paper",
            "authors": ["Alice Smith"],
            "first_author": "Alice Smith",
            "first_author_lastname": "Smith",
            "year": 2024,
            "doi": "10.1234/test",
            "journal": "JFM",
            "abstract": "Old abstract",
            "paper_type": "article",
            "citation_count": {"crossref": 5, "semantic_scholar": 7},
            "ids": {"doi": "10.1234/test", "semantic_scholar": "s2-1"},
            "api_sources": ["crossref", "semantic_scholar"],
            "references": ["10.9999/ref"],
        }
        json_path.write_text(json.dumps(original), encoding="utf-8")

        def fake_enrich(meta):
            meta.extraction_method = "local_only"
            return meta

        monkeypatch.setattr("scholaraio.ingest.metadata._api.enrich_metadata", fake_enrich)

        changed = refetch_metadata(json_path)

        assert changed is False
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["citation_count"] == original["citation_count"]
        assert data["api_sources"] == original["api_sources"]

    def test_refetch_keeps_existing_citation_state_when_only_arxiv_metadata_survives(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2024-Test-Paper"
        paper_dir.mkdir(parents=True)
        json_path = paper_dir / "meta.json"
        original = {
            "id": "paper-1",
            "title": "Test Paper",
            "authors": ["Alice Smith"],
            "first_author": "Alice Smith",
            "first_author_lastname": "Smith",
            "year": 2024,
            "doi": "",
            "arxiv_id": "hep-th/9901001",
            "journal": "arXiv",
            "abstract": "Old abstract",
            "paper_type": "article",
            "citation_count": {"crossref": 5, "semantic_scholar": 7},
            "ids": {"arxiv": "hep-th/9901001", "semantic_scholar": "s2-1"},
            "api_sources": ["arxiv", "semantic_scholar"],
            "references": ["10.9999/ref"],
        }
        json_path.write_text(json.dumps(original), encoding="utf-8")

        def fake_enrich(meta):
            meta.api_sources = ["arxiv"]
            meta.extraction_method = "arxiv_lookup"
            return meta

        monkeypatch.setattr("scholaraio.ingest.metadata._api.enrich_metadata", fake_enrich)

        changed = refetch_metadata(json_path)

        assert changed is False
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["citation_count"] == original["citation_count"]
        assert data["api_sources"] == original["api_sources"]

    def test_refetch_references_only_updates_references_without_touching_other_metadata(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2024-Test-Paper"
        paper_dir.mkdir(parents=True)
        json_path = paper_dir / "meta.json"
        original = {
            "id": "paper-1",
            "title": "Test Paper",
            "authors": ["Alice Smith"],
            "first_author": "Alice Smith",
            "first_author_lastname": "Smith",
            "year": 2024,
            "doi": "10.1234/test",
            "journal": "JFM",
            "abstract": "Old abstract",
            "paper_type": "article",
            "citation_count": {"crossref": 5, "semantic_scholar": 7},
            "ids": {"doi": "10.1234/test", "semantic_scholar": "s2-1"},
            "api_sources": ["crossref", "semantic_scholar"],
            "references": [],
        }
        json_path.write_text(json.dumps(original), encoding="utf-8")

        monkeypatch.setattr(
            "scholaraio.ingest.metadata._api.query_semantic_scholar",
            lambda **kwargs: {"references": [{"externalIds": {"DOI": "10.9999/ref-a"}}]},
        )
        monkeypatch.setattr(
            "scholaraio.ingest.metadata._api.query_crossref",
            lambda **kwargs: {
                "reference": [{"DOI": "10.9999/ref-b"}],
            },
        )

        changed = refetch_metadata(json_path, references_only=True)

        assert changed is True
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["references"] == ["10.9999/ref-a"]
        assert data["title"] == original["title"]
        assert data["abstract"] == original["abstract"]
        assert data["citation_count"] == original["citation_count"]
        assert data["api_sources"] == original["api_sources"]

    def test_rename_collision_avoidance(self, tmp_path):
        papers = tmp_path / "papers"
        old_dir = papers / "wrong-name"
        old_dir.mkdir(parents=True)
        # Pre-create the target directory to force collision
        (papers / "Smith-2023-Test").mkdir(parents=True)
        meta = {
            "title": "Test",
            "first_author_lastname": "Smith",
            "year": 2023,
        }
        (old_dir / "meta.json").write_text(json.dumps(meta))

        result = rename_paper(old_dir / "meta.json")
        assert result is not None
        assert "-2" in result.parent.name

    def test_dry_run(self, tmp_path):
        papers = tmp_path / "papers"
        old_dir = papers / "old-name"
        old_dir.mkdir(parents=True)
        meta = {
            "title": "Test",
            "first_author_lastname": "Smith",
            "year": 2023,
        }
        (old_dir / "meta.json").write_text(json.dumps(meta))

        result = rename_paper(old_dir / "meta.json", dry_run=True)
        assert result is not None
        assert old_dir.exists()  # original not moved

    def test_collision_suffix_name_is_idempotent(self, tmp_path):
        papers = tmp_path / "papers"
        (papers / "Smith-2023-Test").mkdir(parents=True)
        suffixed_dir = papers / "Smith-2023-Test-2"
        suffixed_dir.mkdir(parents=True)
        (suffixed_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "test-uuid",
                    "title": "Test",
                    "first_author_lastname": "Smith",
                    "year": 2023,
                }
            ),
            encoding="utf-8",
        )

        result = rename_paper(suffixed_dir / "meta.json")

        assert result is None
        assert suffixed_dir.exists()

    def test_collision_suffix_reclaims_canonical_name_when_available(self, tmp_path):
        papers = tmp_path / "papers"
        suffixed_dir = papers / "Smith-2023-Test-2"
        suffixed_dir.mkdir(parents=True)
        (suffixed_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "test-uuid",
                    "title": "Test",
                    "first_author_lastname": "Smith",
                    "year": 2023,
                }
            ),
            encoding="utf-8",
        )

        result = rename_paper(suffixed_dir / "meta.json")

        assert result is not None
        assert result.parent.name == "Smith-2023-Test"
        assert result.parent.exists()
        assert not suffixed_dir.exists()

    def test_numeric_old_name_is_re_normalized_to_smallest_collision_suffix(self, tmp_path):
        papers = tmp_path / "papers"
        (papers / "Smith-2023-Test").mkdir(parents=True)
        numeric_dir = papers / "Smith-2023-Test-2024"
        numeric_dir.mkdir(parents=True)
        (numeric_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "test-uuid",
                    "title": "Test",
                    "first_author_lastname": "Smith",
                    "year": 2023,
                }
            ),
            encoding="utf-8",
        )

        result = rename_paper(numeric_dir / "meta.json")

        assert result is not None
        assert result.parent.name == "Smith-2023-Test-2"
        assert result.parent.exists()
        assert not numeric_dir.exists()


class TestMetadataToDictWebFields:
    def test_preserves_web_source_fields(self):
        meta = PaperMetadata(
            title="Example Domain",
            paper_type="document",
            source_url="https://example.com/docs",
            source_type="web",
            extracted_at="2026-04-14T12:00:00",
            extraction_method="qt-web-extractor",
        )

        data = metadata_to_dict(meta)

        assert data["source_url"] == "https://example.com/docs"
        assert data["source_type"] == "web"
        assert data["extracted_at"] == "2026-04-14T12:00:00"
        assert data["extraction_method"] == "qt-web-extractor"
