"""Contract tests for the audit module.

Verifies: audit detects known data quality issues and returns structured reports.
Does NOT test: specific rule implementations or diagnostic messages.
"""

from __future__ import annotations

import json

from scholaraio.audit import Issue, audit_papers, list_scrub_suspects


class TestAuditDetection:
    """Audit contract: reports issues as structured Issue objects."""

    def test_clean_papers_produce_no_errors(self, tmp_papers):
        issues = audit_papers(tmp_papers)
        errors = [i for i in issues if i.severity == "error"]
        # Well-formed test data should have no errors
        assert len(errors) == 0

    def test_missing_doi_reported_for_non_thesis(self, tmp_papers):
        """Paper B is thesis (no DOI ok), but a journal-article without DOI should warn."""
        # Create a journal article without DOI
        d = tmp_papers / "NoDoi-2023-Test"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "cccc-3333",
                    "title": "Test Paper",
                    "authors": ["Author"],
                    "year": 2023,
                    "doi": "",
                    "paper_type": "journal-article",
                }
            ),
        )
        (d / "paper.md").write_text("# Test Paper\n\nSome content here for testing.")

        issues = audit_papers(tmp_papers)
        doi_issues = [i for i in issues if "doi" in i.rule.lower() or "doi" in i.message.lower()]
        assert len(doi_issues) >= 1

    def test_missing_doi_and_journal_still_reported_when_paper_type_missing(self, tmp_papers):
        d = tmp_papers / "NoType-2024-Test"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "notype-0001",
                    "title": "A paper without explicit type",
                    "authors": ["Alice Example"],
                    "first_author_lastname": "Example",
                    "year": 2024,
                    "doi": "",
                    "journal": "",
                    "abstract": "Test abstract.",
                    "paper_type": "",
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text(
            "# A paper without explicit type\n\nBody content long enough to avoid short-md warnings.\n" * 5,
            encoding="utf-8",
        )

        issues = audit_papers(tmp_papers)
        paper_issues = [i.rule for i in issues if i.paper_id == d.name]

        assert "missing_doi" in paper_issues
        assert "missing_journal" in paper_issues

    def test_thesis_without_doi_or_journal_does_not_warn(self, tmp_papers):
        issues = audit_papers(tmp_papers)

        thesis_issues = [i for i in issues if i.paper_id == "Wang-2024-DeepLearning"]

        assert all(i.rule != "missing_doi" for i in thesis_issues)
        assert all(i.rule != "missing_journal" for i in thesis_issues)

    def test_book_without_serial_metadata_does_not_warn(self, tmp_papers):
        d = tmp_papers / "Doe-2024-Handbook"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "book-4444",
                    "title": "Handbook of Test Data",
                    "authors": ["Jamie Doe"],
                    "first_author_lastname": "Doe",
                    "year": 2024,
                    "doi": "",
                    "journal": "",
                    "abstract": "",
                    "paper_type": "book",
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text("# Handbook of Test Data\n\nBook content.", encoding="utf-8")

        issues = audit_papers(tmp_papers)
        book_issues = [i for i in issues if i.paper_id == d.name]

        assert all(i.rule != "missing_doi" for i in book_issues)
        assert all(i.rule != "missing_journal" for i in book_issues)
        assert all(i.rule != "missing_abstract" for i in book_issues)

    def test_title_mismatch_uses_later_title_heading_after_front_matter(self, tmp_papers):
        d = tmp_papers / "FrontMatter-2024-Flow"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "frontmatter-5555",
                    "title": "Particle response in channel flow",
                    "authors": ["A. Author"],
                    "first_author_lastname": "Author",
                    "year": 2024,
                    "doi": "10.1234/example",
                    "journal": "Test Journal",
                    "abstract": "Test abstract.",
                    "paper_type": "journal-article",
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text(
            "# INFORMATION TO USERS\n\n# Particle response in channel flow\n\nBody content here.",
            encoding="utf-8",
        )

        issues = audit_papers(tmp_papers)

        assert all(not (i.paper_id == d.name and i.rule == "title_mismatch") for i in issues)

    def test_title_mismatch_uses_raw_first_line_when_h1_is_front_matter(self, tmp_papers):
        d = tmp_papers / "RawTitle-1883-Reynolds"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "rawtitle-6666",
                    "title": "An experimental investigation of the motion of water in parallel channels",
                    "authors": ["Osborne Reynolds"],
                    "first_author_lastname": "Reynolds",
                    "year": 1883,
                    "doi": "10.1234/reynolds",
                    "journal": "Philosophical Transactions",
                    "abstract": "Test abstract.",
                    "paper_type": "journal-article",
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text(
            "An experimental investigation of the motion of water in parallel channels\n\n# [PLATES 72-74.]\n\nBody content.",
            encoding="utf-8",
        )

        issues = audit_papers(tmp_papers)

        assert all(not (i.paper_id == d.name and i.rule == "title_mismatch") for i in issues)

    def test_title_mismatch_still_reported_for_wrong_content(self, tmp_papers):
        d = tmp_papers / "Mismatch-2024-Wrong"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "mismatch-7777",
                    "title": "Compressibility effects on turbulence",
                    "authors": ["A. Author"],
                    "first_author_lastname": "Author",
                    "year": 2024,
                    "doi": "10.1234/mismatch",
                    "journal": "Test Journal",
                    "abstract": "Test abstract.",
                    "paper_type": "journal-article",
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text("# Geophysical Research Letters\n\nCompletely unrelated content.", encoding="utf-8")

        issues = audit_papers(tmp_papers)

        assert any(i.paper_id == d.name and i.rule == "title_mismatch" for i in issues)

    def test_title_mismatch_skipped_for_thesis_front_matter(self, tmp_papers):
        d = tmp_papers / "Thesis-2024-FrontMatter"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "thesis-8888",
                    "title": "Direct numerical simulation of viscoelastic turbulence",
                    "authors": ["A. Student"],
                    "first_author_lastname": "Student",
                    "year": 2024,
                    "doi": "",
                    "journal": "",
                    "abstract": "Test abstract.",
                    "paper_type": "thesis",
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text(
            "# University of Example\n\n# Doctoral Dissertation\n\nFront matter only.",
            encoding="utf-8",
        )

        issues = audit_papers(tmp_papers)

        assert all(not (i.paper_id == d.name and i.rule == "title_mismatch") for i in issues)

    def test_title_mismatch_skipped_for_dissertation_front_matter(self, tmp_papers):
        d = tmp_papers / "Dissertation-2024-FrontMatter"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "dissertation-9999",
                    "title": "Direct numerical simulation of viscoelastic turbulence",
                    "authors": ["A. Student"],
                    "first_author_lastname": "Student",
                    "year": 2024,
                    "doi": "",
                    "journal": "",
                    "abstract": "Test abstract.",
                    "paper_type": "dissertation",
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text(
            "# University of Example\n\n# Doctoral Dissertation\n\nFront matter only.\n" * 4,
            encoding="utf-8",
        )

        issues = audit_papers(tmp_papers)

        assert all(not (i.paper_id == d.name and i.rule == "title_mismatch") for i in issues)

    def test_missing_abstract_not_reported_when_markdown_is_missing(self, tmp_papers):
        d = tmp_papers / "MetaOnly-2024-Article"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "metaonly-9999",
                    "title": "A metadata-only article",
                    "authors": ["A. Author"],
                    "first_author_lastname": "Author",
                    "year": 2024,
                    "doi": "10.1234/meta-only",
                    "journal": "Test Journal",
                    "abstract": "",
                    "paper_type": "journal-article",
                }
            ),
            encoding="utf-8",
        )

        issues = audit_papers(tmp_papers)
        paper_issues = [i.rule for i in issues if i.paper_id == d.name]

        assert "missing_md" in paper_issues
        assert "missing_abstract" not in paper_issues

    def test_missing_abstract_skipped_when_explicitly_unavailable(self, tmp_papers):
        d = tmp_papers / "NoAbstract-1994-Review"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "noabstract-1010",
                    "title": "Compressibility Effects on Turbulence",
                    "authors": ["Sanjiva K. Lele"],
                    "first_author_lastname": "Lele",
                    "year": 1994,
                    "doi": "10.1234/no-abstract",
                    "journal": "Annual Review of Fluid Mechanics",
                    "abstract": "",
                    "abstract_unavailable": True,
                    "paper_type": "journal-article",
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text("# Compressibility Effects on Turbulence\n\nReview content.", encoding="utf-8")

        issues = audit_papers(tmp_papers)

        assert all(not (i.paper_id == d.name and i.rule == "missing_abstract") for i in issues)

    def test_missing_abstract_skipped_for_erratum(self, tmp_papers):
        d = tmp_papers / "Erratum-1998-Test"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "erratum-1111",
                    "title": 'Erratum to "A generalized Fokker-Planck equation"',
                    "authors": ["A. Author"],
                    "first_author_lastname": "Author",
                    "year": 1998,
                    "doi": "10.1234/erratum",
                    "journal": "Physica A",
                    "abstract": "",
                    "paper_type": "journal-article",
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text("# Erratum\n\nCorrection only.", encoding="utf-8")

        issues = audit_papers(tmp_papers)

        assert all(not (i.paper_id == d.name and i.rule == "missing_abstract") for i in issues)

    def test_title_mismatch_uses_translated_title_when_available(self, tmp_papers):
        d = tmp_papers / "Einstein-1906-MolecularDimensions"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "translated-title-1212",
                    "title": "Eine neue Bestimmung der Moleküldimensionen",
                    "title_translated": "A New Determination of Molecular Dimensions",
                    "authors": ["A. Einstein"],
                    "first_author_lastname": "Einstein",
                    "year": 1906,
                    "doi": "10.1234/einstein",
                    "journal": "Annalen der Physik",
                    "abstract": "Test abstract.",
                    "paper_type": "journal-article",
                }
            ),
            encoding="utf-8",
        )
        (d / "paper.md").write_text(
            "# PAPER 1\n\n# A New Determination of Molecular Dimensions\n\nTranslated content.",
            encoding="utf-8",
        )

        issues = audit_papers(tmp_papers)

        assert all(not (i.paper_id == d.name and i.rule == "title_mismatch") for i in issues)

    def test_issue_has_required_fields(self, tmp_papers):
        # Create a problematic paper to guarantee at least one issue
        d = tmp_papers / "Bad-0000-Empty"
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"id": "bad"}))
        (d / "paper.md").write_text("")

        issues = audit_papers(tmp_papers)
        assert len(issues) > 0
        for issue in issues:
            assert isinstance(issue, Issue)
            assert issue.paper_id
            assert issue.severity in ("error", "warning", "info")
            assert issue.rule
            assert issue.message


class TestScrubSuspects:
    """Scrub suspect detection should flag obvious metadata problems conservatively."""

    def test_flags_placeholder_title(self, tmp_path):
        d = tmp_path / "Unknown-2024-Introduction"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "placeholder-title",
                    "title": "Introduction",
                    "authors": ["Alice Example"],
                    "first_author_lastname": "Example",
                    "year": 2024,
                }
            )
        )

        issues = list_scrub_suspects(tmp_path)

        assert any(i.paper_id == d.name and i.rule == "placeholder_title" for i in issues)

    def test_flags_garbled_title(self, tmp_path):
        d = tmp_path / "Example-2024-Trainium"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "garbled-title",
                    "title": "Trainium�/� Architecture",
                    "authors": ["Alice Example"],
                    "first_author_lastname": "Example",
                    "year": 2024,
                }
            )
        )

        issues = list_scrub_suspects(tmp_path)

        assert any(i.paper_id == d.name and i.rule == "garbled_title" for i in issues)

    def test_flags_unknown_author(self, tmp_path):
        d = tmp_path / "Unknown-2024-Network"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "unknown-author",
                    "title": "Network Scheduling for Training",
                    "authors": ["Unknown"],
                    "first_author_lastname": "Unknown",
                    "year": 2024,
                }
            )
        )

        issues = list_scrub_suspects(tmp_path)

        assert any(i.paper_id == d.name and i.rule == "suspicious_author" for i in issues)

    def test_flags_scalar_author_metadata_without_crashing(self, tmp_path):
        d = tmp_path / "Malformed-2024-Network"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "scalar-author",
                    "title": "Network Scheduling for Training",
                    "authors": 123,
                    "first_author_lastname": "",
                    "year": 2024,
                }
            )
        )

        issues = list_scrub_suspects(tmp_path)

        assert any(i.paper_id == d.name and i.rule == "suspicious_author" for i in issues)

    def test_flags_missing_year(self, tmp_path):
        d = tmp_path / "Contributor-XXXX-Distributed-Systems"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                {
                    "id": "missing-year",
                    "title": "Distributed Systems for Large-Scale Training",
                    "authors": ["Alice Example"],
                    "first_author_lastname": "Example",
                    "year": None,
                }
            )
        )

        issues = list_scrub_suspects(tmp_path)

        assert any(i.paper_id == d.name and i.rule == "suspicious_year" for i in issues)

    def test_skips_healthy_record(self, tmp_papers):
        issues = list_scrub_suspects(tmp_papers)

        assert all(i.paper_id != "Smith-2023-Turbulence" for i in issues)

    def test_includes_dirs_without_meta_json_when_paper_md_exists(self, tmp_path):
        d = tmp_path / "Broken-2024-OnlyMarkdown"
        d.mkdir()
        (d / "paper.md").write_text("# Broken metadata\n\nOnly markdown remains.", encoding="utf-8")

        issues = list_scrub_suspects(tmp_path)

        assert any(i.paper_id == d.name and i.rule == "invalid_metadata" for i in issues)
