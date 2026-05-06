"""Regression tests for localized CLI/setup messaging."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sqlite3
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scholaraio.core.config import _build_config
from scholaraio.interfaces.cli import compat as cli
from scholaraio.providers.mineru import ConvertResult, PDFValidationResult
from scholaraio.services.index import build_index
from scholaraio.services.migration_control import (
    ensure_instance_metadata,
    ensure_migration_journal,
    run_migration_store,
    run_migration_verification,
    write_migration_lock,
)
from scholaraio.services.setup import _S
from scholaraio.services.translate import TranslateResult
from scholaraio.stores.toolref.constants import TOOL_REGISTRY


def _write_toolref_fixture(toolref_root):
    tool_name = next(iter(TOOL_REGISTRY))
    tool_version_dir = toolref_root / tool_name / "v1"
    tool_version_dir.mkdir(parents=True, exist_ok=True)
    (tool_version_dir / "meta.json").write_text(json.dumps({"source_type": "git"}), encoding="utf-8")
    (toolref_root / tool_name / "current").symlink_to("v1")

    conn = sqlite3.connect(toolref_root / tool_name / "toolref.db")
    try:
        conn.execute(
            """
            CREATE TABLE toolref_pages (
                id INTEGER PRIMARY KEY,
                tool TEXT NOT NULL,
                version TEXT NOT NULL,
                program TEXT,
                section TEXT,
                page_name TEXT NOT NULL,
                title TEXT,
                category TEXT,
                var_type TEXT,
                default_val TEXT,
                synopsis TEXT,
                content TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO toolref_pages
                (tool, version, program, section, page_name, title, synopsis, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tool_name, "v1", "pw", "input", "pw/scf", "scf", "pw scf", "Self-consistent field"),
        )
        conn.commit()
    finally:
        conn.close()
    return tool_name


def _write_explore_fixture(explore_root):
    explore_dir = explore_root / "demo-explore"
    explore_dir.mkdir(parents=True, exist_ok=True)
    (explore_dir / "papers.jsonl").write_text(
        json.dumps(
            {
                "openalex_id": "W1",
                "title": "Explore turbulence library",
                "abstract": "Exploration token for verify search.",
                "authors": ["Explore Author"],
                "year": 2026,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    sqlite3.connect(explore_dir / "explore.db").close()
    return explore_dir.name


def _write_proceedings_fixture(proceedings_root):
    from scholaraio.services.index import build_proceedings_index

    proceeding_dir = proceedings_root / "Proc-2026-Test"
    child_dir = proceeding_dir / "papers" / "Wave-2026-Test"
    child_dir.mkdir(parents=True, exist_ok=True)
    (proceeding_dir / "meta.json").write_text(
        json.dumps({"id": "proc-1", "title": "Proceedings of Verification 2026"}),
        encoding="utf-8",
    )
    (child_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "proc-paper-1",
                "title": "Granular proceedings verification",
                "abstract": "Granular proceedings verification token.",
                "authors": ["Pat Chen"],
                "year": 2026,
                "paper_type": "conference-paper",
                "proceeding_title": "Proceedings of Verification 2026",
            }
        ),
        encoding="utf-8",
    )
    (child_dir / "paper.md").write_text("# Granular proceedings verification\n", encoding="utf-8")
    build_proceedings_index(proceedings_root, proceedings_root / "proceedings.db", rebuild=True)
    return proceeding_dir.name


def _write_spool_fixture(data_root):
    fixtures = {
        "inbox": ("paper.md", "# Paper queued for ingest\n"),
        "inbox-thesis": ("thesis.md", "# Thesis queued for ingest\n"),
        "inbox-patent": ("patent.md", "# Patent queued for ingest\n"),
        "inbox-doc": ("report.md", "# Document queued for ingest\n"),
        "inbox-proceedings": ("volume.md", "# Proceedings queued for ingest\n"),
        "pending/Needs-Review": ("pending.json", json.dumps({"issue": "no_doi", "title": "Needs Review"})),
    }
    for rel_dir, (filename, content) in fixtures.items():
        path = data_root / rel_dir
        path.mkdir(parents=True, exist_ok=True)
        (path / filename).write_text(content, encoding="utf-8")


def _write_papers_fixture(papers_root):
    paper_dir = papers_root / "Doe-2026-Paper-Migration"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "paper-1",
                "title": "Paper migration verification",
                "authors": ["Jane Doe"],
                "year": 2026,
                "journal": "Migration Journal",
                "doi": "10.1234/paper.migration",
                "abstract": "Durable paper migration keyword.",
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "paper.md").write_text("# Paper migration verification\n", encoding="utf-8")
    return paper_dir.name


def _allow_pdf_validation(monkeypatch):
    import scholaraio.providers.mineru as mineru

    monkeypatch.setattr(
        mineru,
        "validate_pdf_for_mineru",
        lambda _path: PDFValidationResult(ok=True, page_count=1, deep_checked=True),
    )


class TestSetupImportHints:
    def test_zh_import_hint_is_fully_localized(self):
        zh_hint = _S["import_hint"]["zh"]

        assert zh_hint.startswith("\n提示：")

    def test_zotero_examples_use_distinct_placeholders_and_optional_local_collection(self):
        en_hint = _S["import_hint"]["en"]
        zh_hint = _S["import_hint"]["zh"]

        assert "--api-key <API_KEY>" in en_hint
        assert "--collection <COLLECTION_KEY>" in en_hint
        assert "scholaraio import-zotero --local /path/to/zotero.sqlite\n" in en_hint
        assert "--api-key <API_KEY>" in zh_hint
        assert "--collection <COLLECTION_KEY>" in zh_hint
        assert "scholaraio import-zotero --local /path/to/zotero.sqlite\n" in zh_hint


class TestSetupPromptTransparency:
    def test_setup_prompts_explain_paid_vs_free_items(self):
        zh_llm = _S["llm_key_prompt"]["zh"]
        zh_mineru = _S["mineru_key_prompt"]["zh"]
        zh_email = _S["email_prompt"]["zh"]

        assert "单独计费" in zh_llm
        assert "免费" in zh_mineru
        assert "免费" in zh_email


class TestCliHelpLocalization:
    def test_root_help_uses_research_terminal_positioning(self):
        parser = cli._build_parser()
        root_help = parser.format_help()

        assert "Research terminal for AI coding agents" in root_help
        assert "local academic literature search tool" not in root_help

    def test_setup_help_is_fully_localized(self):
        parser = cli._build_parser()
        setup_parser = parser._subparsers._group_actions[0].choices["setup"]
        setup_help = setup_parser.format_help()
        setup_check = setup_parser._subparsers._group_actions[0].choices["check"].format_help()

        assert "Start the interactive setup wizard by default" in setup_help
        assert "Check environment status" in setup_help
        assert "Output language (en or zh; default: en)" in setup_check
        assert "默认进入交互式安装向导" not in setup_help
        assert "检查环境状态" not in setup_help
        assert "输出语言" not in setup_check

    def test_toolref_fetch_help_uses_prefix_free_version_example(self):
        parser = cli._build_parser()
        toolref_parser = parser._subparsers._group_actions[0].choices["toolref"]
        toolref_fetch = toolref_parser._subparsers._group_actions[0].choices["fetch"].format_help()

        assert "Version, for example 7.5 or 22Jul2025_update3" in toolref_fetch
        assert "stable_22Jul2025_update3" not in toolref_fetch

    def test_fsearch_help_mentions_proceedings_scope(self):
        parser = cli._build_parser()
        fsearch_help = parser._subparsers._group_actions[0].choices["fsearch"].format_help()

        assert "proceedings" in fsearch_help

    def test_publish_site_help_is_english(self):
        parser = cli._build_parser()
        publish_help = parser._subparsers._group_actions[0].choices["publish-site"].format_help()

        assert "Generate a static published-paper site" in publish_help
        assert "--out-dir" in publish_help
        assert "--symlink" in publish_help

    def test_style_list_descriptions_are_english(self, capsys):
        cli.cmd_style(Namespace(style_sub="list"), _build_config({}, Path.cwd()))

        out = capsys.readouterr().out
        assert "APA 7th edition" in out
        assert re.search(r"[\u4e00-\u9fff]", out) is None

    def test_explore_help_mentions_multidimensional_exploration(self):
        parser = cli._build_parser()
        root_help = parser.format_help()

        assert "Multi-dimensional literature exploration" in root_help
        assert "full-journal exploration" not in root_help

    def test_refetch_help_accepts_uuid_and_doi_identifiers(self):
        parser = cli._build_parser()
        refetch_help = parser._subparsers._group_actions[0].choices["refetch"].format_help()

        assert "directory name / UUID / DOI" in refetch_help

    def test_backup_help_exposes_list_and_run_subcommands(self):
        parser = cli._build_parser()
        backup_parser = parser._subparsers._group_actions[0].choices["backup"]
        backup_help = backup_parser.format_help()
        run_help = backup_parser._subparsers._group_actions[0].choices["run"].format_help()

        assert "Incremental backup with rsync" in backup_help
        assert "List configured backup targets" in backup_help
        assert "Preview rsync actions without transferring files" in run_help

    def test_patent_fetch_help_uses_configured_inbox_label(self):
        parser = cli._build_parser()
        patent_fetch_help = parser._subparsers._group_actions[0].choices["patent-fetch"].format_help()
        patent_search_help = parser._subparsers._group_actions[0].choices["patent-search"].format_help()

        assert "<patent inbox>" in patent_fetch_help
        assert "data/inbox-patent/" not in patent_fetch_help
        assert "<patent inbox>" in patent_search_help
        assert "data/inbox-patent/" not in patent_search_help

    def test_workspace_system_output_help_uses_current_defaults(self):
        parser = cli._build_parser()
        choices = parser._subparsers._group_actions[0].choices
        export_parser = choices["export"]
        export_docx_help = export_parser._subparsers._group_actions[0].choices["docx"].format_help()
        diagram_help = choices["diagram"].format_help()
        translate_help = choices["translate"].format_help()

        assert "<workspace>/_system/output/output.docx" in export_docx_help
        assert "<workspace>/output.docx" not in export_docx_help
        assert "<workspace>/_system/figures/" in diagram_help
        assert "<workspace>/figures/" not in diagram_help
        assert "workspace/_system/translation-bundles/" in translate_help
        assert "workspace/translation-ws/" not in translate_help

    def test_paper2any_help_exposes_lightweight_mcp_sidecar(self):
        parser = cli._build_parser()
        paper2any_parser = parser._subparsers._group_actions[0].choices["paper2any"]
        actions = paper2any_parser._subparsers._group_actions[0].choices

        serve_help = actions["mcp-serve"].format_help()
        backend_help = actions["backend-serve"].format_help()
        setup_help = actions["setup"].format_help()
        call_help = actions["call"].format_help()

        assert "Prepare the external Paper2Any runtime extension" in setup_help
        assert "--install-runtime" in setup_help
        assert "Start the lightweight Paper2Any MCP sidecar" in serve_help
        assert "--paper2any-root" in serve_help
        assert "--backend-url" in serve_help
        assert "Start the real upstream Paper2Any FastAPI backend" in backend_help
        assert "--backend-api-key" in backend_help
        assert "Call a Paper2Any MCP tool" in call_help
        assert "setup" in actions
        assert "mcp-serve" in actions
        assert "backend-serve" in actions
        assert "status" in actions
        assert "tools" in actions


class TestWebsearchCli:
    def test_cmd_websearch_exits_on_service_unavailable(self, monkeypatch):
        import scholaraio.providers.webtools as webtools

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        def fake_search_and_display(*args, **kwargs):
            raise webtools.ServiceUnavailableError("service down")

        monkeypatch.setattr(webtools, "search_and_display", fake_search_and_display)

        args = Namespace(query=["test"], count=3)

        with pytest.raises(SystemExit) as exc:
            cli.cmd_websearch(args, SimpleNamespace())

        assert exc.value.code == 1
        assert any("Error: service down" in message for message in messages)
        assert any("GUILessBingSearch" in message for message in messages)

    def test_cmd_websearch_does_not_repeat_success_summary(self, monkeypatch):
        import scholaraio.providers.webtools as webtools

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        monkeypatch.setattr(
            webtools,
            "search_and_display",
            lambda *args, **kwargs: [
                webtools.WebSearchResult(title="OpenAI", link="https://openai.com", snippet="AI research")
            ],
        )

        args = Namespace(query=["openai"], count=1)
        cli.cmd_websearch(args, SimpleNamespace())

        assert messages == []


class TestWebextractCli:
    def test_cmd_webextract_exits_when_result_contains_error_without_text(self, monkeypatch):
        import scholaraio.providers.webtools as webtools

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(
            webtools,
            "extract_web",
            lambda *args, **kwargs: {"title": "", "text": "", "error": "partial extraction failed"},
        )

        args = Namespace(url="https://example.com", pdf=False, full=False, max_chars=10)

        with pytest.raises(SystemExit) as exc:
            cli.cmd_webextract(args, SimpleNamespace())

        assert exc.value.code == 1
        assert any("Extraction failed: partial extraction failed" in message for message in messages)
        assert all("Extraction succeeded" not in message for message in messages)

    def test_cmd_webextract_truncates_long_text_by_default(self, monkeypatch, capsys):
        import scholaraio.providers.webtools as webtools

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(
            webtools,
            "extract_web",
            lambda *args, **kwargs: {"title": "Page", "text": "abcdefghijklmnopqrstuvwxyz"},
        )

        args = Namespace(url="https://example.com", pdf=False, full=False, max_chars=10)
        cli.cmd_webextract(args, SimpleNamespace())

        captured = capsys.readouterr()

        assert any("Extraction succeeded: Page" in message for message in messages)
        assert any("Content is long" in message for message in messages)
        assert "abcdefghij" in captured.out
        assert "klmnopqrstuvwxyz" not in captured.out

    def test_cmd_webextract_full_prints_complete_text(self, monkeypatch, capsys):
        import scholaraio.providers.webtools as webtools

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(
            webtools,
            "extract_web",
            lambda *args, **kwargs: {"title": "Page", "text": "abcdefghijklmnopqrstuvwxyz"},
        )

        args = Namespace(url="https://example.com", pdf=False, full=True, max_chars=10)
        cli.cmd_webextract(args, SimpleNamespace())

        captured = capsys.readouterr()

        assert any("Extraction succeeded: Page" in message for message in messages)
        assert all("Truncated" not in message for message in messages)
        assert "abcdefghijklmnopqrstuvwxyz" in captured.out


class TestShowLayer4Headings:
    def test_translated_full_text_heading_uses_consistent_spacing(self, tmp_papers, monkeypatch):
        paper_dir = tmp_papers / "Smith-2023-Turbulence"
        (paper_dir / "paper_zh.md").write_text("中文全文。", encoding="utf-8")

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_print_header", lambda _: None)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(paper_id="Smith-2023-Turbulence", layer=4, lang="zh")

        cli.cmd_show(args, cfg)

        assert "\n--- Full text (zh) ---\n" in messages

    def test_missing_translation_heading_uses_consistent_spacing(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_print_header", lambda _: None)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(paper_id="Smith-2023-Turbulence", layer=4, lang="fr")

        cli.cmd_show(args, cfg)

        assert "\n--- Full text (source, paper_fr.md does not exist) ---\n" in messages


class TestRefetchIdentifierResolution:
    def test_refetch_resolves_uuid_via_registry(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)

        seen: list[Path] = []
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("scholaraio.services.ingest_metadata.refetch_metadata", lambda jp: seen.append(jp) or True)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(paper_id="aaaa-1111", all=False, force=False, jobs=5)

        cli.cmd_refetch(args, cfg)

        assert seen == [tmp_papers / "Smith-2023-Turbulence" / "meta.json"]
        assert any("Concurrent refetch (1 workers, total 1 papers)" in m for m in messages)
        assert any("Smith-2023-Turbulence" in m for m in messages)

    def test_refetch_resolves_mixed_case_doi_without_registry(self, tmp_papers, tmp_path, monkeypatch):
        seen: list[Path] = []
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("scholaraio.services.ingest_metadata.refetch_metadata", lambda jp: seen.append(jp) or True)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_path / "missing-index.db")
        args = Namespace(paper_id="10.1234/JFM.2023.001", all=False, force=False, jobs=5)

        cli.cmd_refetch(args, cfg)

        assert seen == [tmp_papers / "Smith-2023-Turbulence" / "meta.json"]
        assert any("Concurrent refetch (1 workers, total 1 papers)" in m for m in messages)
        assert any("Smith-2023-Turbulence" in m for m in messages)

    def test_refetch_all_references_only_targets_doi_papers_with_empty_references(
        self, tmp_papers, tmp_path, monkeypatch
    ):
        seeded = tmp_papers / "Doe-2022-Seeded-References"
        seeded.mkdir()
        (seeded / "meta.json").write_text(
            json.dumps(
                {
                    "id": "cccc-3333",
                    "title": "Seeded references paper",
                    "authors": ["Jane Doe"],
                    "first_author_lastname": "Doe",
                    "year": 2022,
                    "journal": "Physics of Fluids",
                    "doi": "10.9999/pof.2022.001",
                    "abstract": "Has references already.",
                    "paper_type": "journal-article",
                    "citation_count": {"crossref": 1},
                    "references": ["10.9999/ref-1"],
                }
            ),
            encoding="utf-8",
        )
        (seeded / "paper.md").write_text("# Seeded references paper\n\nBody.", encoding="utf-8")

        seen: list[tuple[Path, bool]] = []
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(
            "scholaraio.services.ingest_metadata.refetch_metadata",
            lambda jp, references_only=False: seen.append((jp, references_only)) or True,
        )

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_path / "missing-index.db")
        args = Namespace(
            paper_id=None,
            all=True,
            force=False,
            jobs=5,
            references_only=True,
        )

        cli.cmd_refetch(args, cfg)

        assert seen == [(tmp_papers / "Smith-2023-Turbulence" / "meta.json", True)]
        assert any("1 papers need reference backfill" in m for m in messages)
        assert any("Concurrent refetch (1 workers, total 1 papers)" in m for m in messages)


class TestRepairIdentifierResolution:
    def test_repair_help_accepts_uuid_and_doi_identifiers(self):
        parser = cli._build_parser()
        repair_help = parser._subparsers._group_actions[0].choices["repair"].format_help()

        assert "directory name / UUID / DOI" in repair_help

    def test_repair_resolves_uuid_via_registry(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(
            paper_id="aaaa-1111",
            title="Updated Turbulence Title",
            doi="",
            author="John Smith",
            year=2023,
            no_api=True,
            dry_run=False,
        )

        cli.cmd_repair(args, cfg)

        repaired_dir = tmp_papers / "Smith-2023-Updated-Turbulence-Title"
        assert repaired_dir.exists()
        repaired_meta = json.loads((repaired_dir / "meta.json").read_text(encoding="utf-8"))
        assert repaired_meta["id"] == "aaaa-1111"
        assert repaired_meta["title"] == "Updated Turbulence Title"

    def test_repair_preserves_registry_uuid_when_meta_json_lost_id(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)

        paper_dir = tmp_papers / "Smith-2023-Turbulence"
        meta_path = paper_dir / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data.pop("id", None)
        meta_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(
            paper_id="10.1234/jfm.2023.001",
            title="Recovered Turbulence Title",
            doi="10.1234/jfm.2023.001",
            author="John Smith",
            year=2023,
            no_api=True,
            dry_run=False,
        )

        cli.cmd_repair(args, cfg)

        repaired_dir = tmp_papers / "Smith-2023-Recovered-Turbulence-Title"
        assert repaired_dir.exists()
        repaired_meta = json.loads((repaired_dir / "meta.json").read_text(encoding="utf-8"))
        assert repaired_meta["id"] == "aaaa-1111"

    def test_repair_preserves_registry_uuid_when_registry_dir_name_is_stale(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)

        original_dir = tmp_papers / "Smith-2023-Turbulence"
        renamed_dir = tmp_papers / "Smith-2023-Turbulence-Renamed"
        original_dir.rename(renamed_dir)

        meta_path = renamed_dir / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data.pop("id", None)
        meta_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(
            paper_id="10.1234/jfm.2023.001",
            title="Recovered Turbulence Title",
            doi="10.1234/jfm.2023.001",
            author="John Smith",
            year=2023,
            no_api=True,
            dry_run=False,
        )

        cli.cmd_repair(args, cfg)

        repaired_dir = tmp_papers / "Smith-2023-Recovered-Turbulence-Title"
        assert repaired_dir.exists()
        repaired_meta = json.loads((repaired_dir / "meta.json").read_text(encoding="utf-8"))
        assert repaired_meta["id"] == "aaaa-1111"

    def test_repair_recovers_registry_uuid_by_existing_doi_when_called_by_dir_name(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)

        original_dir = tmp_papers / "Smith-2023-Turbulence"
        renamed_dir = tmp_papers / "Smith-2023-Turbulence-Renamed"
        original_dir.rename(renamed_dir)

        meta_path = renamed_dir / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data.pop("id", None)
        meta_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(
            paper_id=renamed_dir.name,
            title="Recovered Turbulence Title",
            doi="",
            author="John Smith",
            year=2023,
            no_api=True,
            dry_run=False,
        )

        cli.cmd_repair(args, cfg)

        repaired_dir = tmp_papers / "Smith-2023-Recovered-Turbulence-Title"
        assert repaired_dir.exists()
        repaired_meta = json.loads((repaired_dir / "meta.json").read_text(encoding="utf-8"))
        assert repaired_meta["id"] == "aaaa-1111"

    def test_repair_replaces_bogus_meta_uuid_when_registry_has_stable_doi_match(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)

        paper_dir = tmp_papers / "Smith-2023-Turbulence"
        meta_path = paper_dir / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["id"] = "bogus-9999"
        meta_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(
            paper_id="10.1234/jfm.2023.001",
            title="Recovered Turbulence Title",
            doi="",
            author="John Smith",
            year=2023,
            no_api=True,
            dry_run=False,
        )

        cli.cmd_repair(args, cfg)

        repaired_dir = tmp_papers / "Smith-2023-Recovered-Turbulence-Title"
        assert repaired_dir.exists()
        repaired_meta = json.loads((repaired_dir / "meta.json").read_text(encoding="utf-8"))
        assert repaired_meta["id"] == "aaaa-1111"

    def test_repair_preserves_existing_metadata_when_no_api(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)

        paper_dir = tmp_papers / "Smith-2023-Turbulence"
        meta_path = paper_dir / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data.update(
            {
                "first_author": "John Smith",
                "citation_count": {
                    "crossref": 10,
                    "semantic_scholar": 12,
                    "openalex": 8,
                },
                "ids": {
                    "doi": "10.1234/jfm.2023.001",
                    "doi_url": "https://doi.org/10.1234/jfm.2023.001",
                    "semantic_scholar": "s2-123",
                    "semantic_scholar_url": "https://www.semanticscholar.org/paper/s2-123",
                    "openalex": "https://openalex.org/W123",
                    "openalex_url": "https://openalex.org/works/W123",
                },
                "api_sources": ["crossref", "semantic_scholar", "openalex"],
                "references": ["10.9999/ref1"],
                "toc": [{"level": 1, "title": "Introduction"}],
                "l3_conclusion": "A careful conclusion.",
            }
        )
        meta_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(
            paper_id="Smith-2023-Turbulence",
            title="Recovered Turbulence Title",
            doi="",
            author="John Smith",
            year=2023,
            no_api=True,
            dry_run=False,
        )

        cli.cmd_repair(args, cfg)

        repaired_dir = tmp_papers / "Smith-2023-Recovered-Turbulence-Title"
        repaired_meta = json.loads((repaired_dir / "meta.json").read_text(encoding="utf-8"))

        assert repaired_meta["id"] == "aaaa-1111"
        assert repaired_meta["doi"] == "10.1234/jfm.2023.001"
        assert repaired_meta["journal"] == "Journal of Fluid Mechanics"
        assert repaired_meta["abstract"] == "We propose a novel turbulence model for boundary layers."
        assert repaired_meta["paper_type"] == "journal-article"
        assert repaired_meta["citation_count"] == data["citation_count"]
        assert repaired_meta["ids"] == data["ids"]
        assert repaired_meta["api_sources"] == data["api_sources"]
        assert repaired_meta["references"] == data["references"]
        assert repaired_meta["toc"] == data["toc"]
        assert repaired_meta["l3_conclusion"] == data["l3_conclusion"]

    def test_repair_accepts_direct_dir_when_meta_json_is_missing(self, tmp_papers, tmp_path):
        paper_dir = tmp_papers / "Broken-2023-Turbulence"
        paper_dir.mkdir()
        (paper_dir / "paper.md").write_text("# Broken metadata\n\nFull text here.", encoding="utf-8")

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_path / "missing-index.db")
        args = Namespace(
            paper_id="Broken-2023-Turbulence",
            title="Recovered Turbulence Title",
            doi="",
            author="John Smith",
            year=2023,
            no_api=True,
            dry_run=False,
        )

        cli.cmd_repair(args, cfg)

        repaired_dir = tmp_papers / "Smith-2023-Recovered-Turbulence-Title"
        assert repaired_dir.exists()
        repaired_meta = json.loads((repaired_dir / "meta.json").read_text(encoding="utf-8"))
        assert repaired_meta["id"]
        assert repaired_meta["title"] == "Recovered Turbulence Title"
        assert (repaired_dir / "paper.md").exists()


class TestShowIdentifierDisplay:
    def test_show_prefers_registry_uuid_when_meta_json_lost_id(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)

        paper_dir = tmp_papers / "Smith-2023-Turbulence"
        meta_path = paper_dir / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data.pop("id", None)
        meta_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(paper_id="10.1234/jfm.2023.001", layer=1)

        cli.cmd_show(args, cfg)

        assert "Paper ID   : aaaa-1111" in messages

    def test_show_replaces_bogus_meta_uuid_with_registry_uuid(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)

        paper_dir = tmp_papers / "Smith-2023-Turbulence"
        meta_path = paper_dir / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["id"] = "bogus-9999"
        meta_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(paper_id="10.1234/jfm.2023.001", layer=1)

        cli.cmd_show(args, cfg)

        assert "Paper ID   : aaaa-1111" in messages
        assert "Paper ID   : bogus-9999" not in messages


class TestShowNotesIntegration:
    def test_notes_displayed_after_header(self, tmp_papers, monkeypatch):
        paper_dir = tmp_papers / "Smith-2023-Turbulence"
        (paper_dir / "notes.md").write_text("## 2026-03-26 | test | analysis\n- Key finding\n", encoding="utf-8")

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_print_header", lambda _: None)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(paper_id="Smith-2023-Turbulence", layer=1)

        cli.cmd_show(args, cfg)

        assert "\n--- Agent notes (notes.md) ---\n" in messages
        assert any("Key finding" in m for m in messages)
        assert "\n--- End notes ---\n" in messages

    def test_no_notes_section_when_file_missing(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_print_header", lambda _: None)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(paper_id="Smith-2023-Turbulence", layer=1)

        cli.cmd_show(args, cfg)

        assert "\n--- Agent notes (notes.md) ---\n" not in messages

    def test_append_notes_visible_in_same_show(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_print_header", lambda _: None)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(
            paper_id="Smith-2023-Turbulence",
            layer=1,
            append_notes="## 2026-03-26 | test | review\n- Important note",
        )

        cli.cmd_show(args, cfg)

        assert any("Appended notes to" in m for m in messages)
        assert "\n--- Agent notes (notes.md) ---\n" in messages
        assert any("Important note" in m for m in messages)

    def test_append_notes_empty_ignored(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_print_header", lambda _: None)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(paper_id="Smith-2023-Turbulence", layer=1, append_notes="   ")

        cli.cmd_show(args, cfg)

        assert any("--append-notes is empty" in m for m in messages)
        assert not (tmp_papers / "Smith-2023-Turbulence" / "notes.md").exists()


class TestSearchResultFormatting:
    def test_format_citations_accepts_legacy_integer_count(self):
        assert cli._format_citations(5) == "5"

    def test_print_search_result_omits_empty_extra(self, monkeypatch):
        messages: list[str] = []

        def fake_ui(message: str = "") -> None:
            messages.append(message)

        monkeypatch.setattr(cli, "ui", fake_ui)

        cli._print_search_result(
            1,
            {
                "paper_id": "paper-1",
                "authors": "Smith, John, Doe, Jane",
                "year": 2023,
                "journal": "JFM",
                "citation_count": 5,
                "title": "Test Paper",
            },
            extra="",
        )

        assert messages
        assert "( [])" not in messages[0]


class TestUnifiedSearchDegradeWarnings:
    def test_cmd_usearch_warns_when_vector_search_degrades(self, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
        monkeypatch.setattr("scholaraio.services.metrics.get_store", lambda: None)
        monkeypatch.setattr(cli, "_record_search_metrics", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            "scholaraio.services.index.unified_search",
            lambda *_args, **_kwargs: (
                [
                    {
                        "paper_id": "paper-1",
                        "dir_name": "Smith-2023-Turbulence",
                        "authors": "John Smith",
                        "year": 2023,
                        "journal": "JFM",
                        "title": "Turbulence modeling in boundary layers",
                        "score": 0.016,
                        "match": "fts",
                    }
                ],
                {"vector_degraded": True},
            ),
        )

        cfg = SimpleNamespace(index_db=Path("dummy.db"), search=SimpleNamespace(top_k=10))
        args = Namespace(query=["mode"], top=3, year=None, journal=None, paper_type=None)

        cli.cmd_usearch(args, cfg)

        assert any("Vector search is unavailable; falling back to keyword search" in m for m in messages)

    def test_cmd_fsearch_warns_when_main_scope_vector_search_degrades(self, monkeypatch, tmp_path):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
        monkeypatch.setattr(
            "scholaraio.services.index.unified_search",
            lambda *_args, **_kwargs: (
                [
                    {
                        "paper_id": "paper-1",
                        "dir_name": "Smith-2023-Turbulence",
                        "authors": "John Smith",
                        "year": 2023,
                        "journal": "JFM",
                        "title": "Turbulence modeling in boundary layers",
                        "score": 0.016,
                        "match": "fts",
                    }
                ],
                {"vector_degraded": True},
            ),
        )

        cfg = SimpleNamespace(index_db=tmp_path / "index.db", papers_dir=tmp_path / "papers")
        cfg.index_db.write_text("", encoding="utf-8")
        args = Namespace(query=["mode"], scope="main", top=3)

        cli.cmd_fsearch(args, cfg)

        assert any("Vector search is unavailable; falling back to keyword search" in m for m in messages)


class TestToolrefCliMessages:
    def test_toolref_show_output_is_localized(self, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(
            "scholaraio.stores.toolref.toolref_show",
            lambda tool, *path, cfg=None: [
                {
                    "page_name": "pw.x/SYSTEM/ecutwfc",
                    "section": "SYSTEM",
                    "program": "pw.x",
                    "synopsis": "wavefunction cutoff",
                    "content": "content body",
                }
            ],
        )

        args = Namespace(toolref_action="show", tool="qe", path=["pw", "ecutwfc"])

        cli.cmd_toolref(args, SimpleNamespace())

        assert any("pw.x/SYSTEM/ecutwfc" in m for m in messages)
        assert any("section:" in m and "program:" in m for m in messages)
        assert all("📖" not in m for m in messages)
        assert all("Namelist:" not in m for m in messages)
        assert all("Program:" not in m for m in messages)


class TestArxivCommands:
    def test_arxiv_fetch_downloads_to_inbox_without_ingest(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        downloaded = tmp_path / "data" / "inbox" / "2603.25200.pdf"

        def fake_download(arxiv_ref, dest_dir, *, overwrite=False):
            dest_dir.mkdir(parents=True, exist_ok=True)
            downloaded.write_bytes(b"%PDF")
            return downloaded

        monkeypatch.setattr("scholaraio.providers.arxiv.download_arxiv_pdf", fake_download)

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(arxiv_ref="2603.25200", ingest=False, force=False, dry_run=False)

        cli.cmd_arxiv_fetch(args, cfg)

        assert downloaded.exists()
        assert any("Downloaded to inbox" in m for m in messages)

    def test_arxiv_fetch_ingest_uses_temp_inbox_pipeline(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        def fake_download(arxiv_ref, dest_dir, *, overwrite=False):
            dest_dir.mkdir(parents=True, exist_ok=True)
            out = dest_dir / "2603.25200.pdf"
            out.write_bytes(b"%PDF")
            return out

        seen: dict[str, object] = {}

        def fake_run_pipeline(step_names, cfg, opts):
            seen["steps"] = step_names
            seen["inbox_dir"] = opts["inbox_dir"]
            seen["opts"] = opts

        monkeypatch.setattr("scholaraio.providers.arxiv.download_arxiv_pdf", fake_download)
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.run_pipeline", fake_run_pipeline)

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(arxiv_ref="2603.25200", ingest=True, force=False, dry_run=False)

        cli.cmd_arxiv_fetch(args, cfg)

        assert seen["steps"] == ["mineru", "extract", "dedup", "ingest", "embed", "index"]
        assert seen["inbox_dir"] != cfg._root / "data" / "inbox"
        assert seen["opts"]["include_aux_inboxes"] is False
        assert any("Start ingesting" in m for m in messages)

    def test_arxiv_fetch_reports_download_failure(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(
            "scholaraio.providers.arxiv.download_arxiv_pdf",
            lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timeout")),
        )

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(arxiv_ref="2603.25200", ingest=False, force=False, dry_run=False)

        cli.cmd_arxiv_fetch(args, cfg)

        assert any("arXiv download failed" in m for m in messages)


class TestFederatedArxivPresence:
    def test_fsearch_marks_arxiv_only_ingested_paper_as_present(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
        monkeypatch.setattr(
            cli,
            "_search_arxiv",
            lambda query, top_k: [
                {
                    "title": "String Junctions and Their Duals in Heterotic String Theory",
                    "authors": ["Y. Imamura"],
                    "year": "1999",
                    "arxiv_id": "hep-th/9901001",
                    "doi": "",
                }
            ],
        )
        monkeypatch.setattr(cli, "_query_dois_for_set", lambda cfg, doi_set: set())

        paper_dir = tmp_path / "papers" / "Imamura-1999-String-Junctions"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "paper-1",
                    "title": "String Junctions and Their Duals in Heterotic String Theory",
                    "arxiv_id": "hep-th/9901001v3",
                    "ids": {"arxiv": "hep-th/9901001v3"},
                }
            ),
            encoding="utf-8",
        )

        cfg = SimpleNamespace(papers_dir=tmp_path / "papers", index_db=tmp_path / "missing.db")
        args = Namespace(query=["string", "junctions"], scope="arxiv", top=5)

        cli.cmd_fsearch(args, cfg)

        assert any("[ingested]" in m for m in messages)


class TestTranslateCliProgress:
    def test_cmd_translate_reports_portable_export_path(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_resolve_paper", lambda paper_id, cfg: tmp_papers / paper_id)
        monkeypatch.setattr(
            "scholaraio.services.translate.translate_paper",
            lambda *args, **kwargs: TranslateResult(
                path=(tmp_papers / "Smith-2023-Turbulence" / "paper_zh.md"),
                portable_path=(
                    tmp_papers.parent
                    / "workspace"
                    / "_system"
                    / "translation-bundles"
                    / "Smith-2023-Turbulence"
                    / "paper_zh.md"
                ),
            ),
        )

        cfg = SimpleNamespace(
            papers_dir=tmp_papers,
            translate=SimpleNamespace(target_lang="zh"),
            workspace_dir=tmp_papers.parent / "workspace",
        )
        args = Namespace(paper_id="Smith-2023-Turbulence", lang="zh", force=True, all=False, portable=True)

        cli.cmd_translate(args, cfg)

        assert any("Translation completed:" in m for m in messages)
        assert any("Portable export:" in m and "translation-bundles" in m for m in messages)

    def test_cmd_translate_reports_resumable_partial_progress(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_resolve_paper", lambda paper_id, cfg: tmp_papers / paper_id)
        monkeypatch.setattr(
            "scholaraio.services.translate.translate_paper",
            lambda *args, **kwargs: TranslateResult(
                path=(tmp_papers / "Smith-2023-Turbulence" / "paper_zh.md"),
                partial=True,
                completed_chunks=2,
                total_chunks=5,
            ),
        )

        cfg = SimpleNamespace(
            papers_dir=tmp_papers,
            translate=SimpleNamespace(target_lang="zh"),
        )
        args = Namespace(paper_id="Smith-2023-Turbulence", lang="zh", force=True, all=False, portable=False)

        try:
            cli.cmd_translate(args, cfg)
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")

        assert any("completed 2/5 chunks" in m for m in messages)
        assert any("you can resume later" in m for m in messages)


class TestExploreCliConfiguredRoots:
    def test_cmd_explore_list_uses_configured_explore_root(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        custom_root = tmp_path / "stores" / "explore"
        custom_lib = custom_root / "alpha"
        custom_lib.mkdir(parents=True)
        (custom_lib / "meta.json").write_text(
            json.dumps({"count": 3, "query": {"issn": "1234-5678"}, "fetched_at": "2026-04-18T00:00:00"}),
            encoding="utf-8",
        )

        legacy_root = tmp_path / "data" / "explore" / "legacy"
        legacy_root.mkdir(parents=True)
        (legacy_root / "meta.json").write_text(
            json.dumps({"count": 9, "query": {"issn": "9999-9999"}, "fetched_at": "2026-04-17T00:00:00"}),
            encoding="utf-8",
        )

        cfg = SimpleNamespace(_root=tmp_path, explore_root=custom_root)
        args = Namespace(explore_action="list")

        cli.cmd_explore(args, cfg)

        assert any("alpha:" in m for m in messages)
        assert all("legacy:" not in m for m in messages)

    def test_cmd_explore_info_uses_configured_explore_root(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        custom_root = tmp_path / "stores" / "explore"
        custom_lib = custom_root / "jfm"
        custom_lib.mkdir(parents=True)
        (custom_lib / "meta.json").write_text(
            json.dumps({"count": 42, "query": {"issn": "0022-1120"}, "fetched_at": "2026-04-18T00:00:00"}),
            encoding="utf-8",
        )

        cfg = SimpleNamespace(_root=tmp_path, explore_root=custom_root)
        args = Namespace(explore_action="info", name="jfm")

        cli.cmd_explore(args, cfg)

        assert any("Explore library: jfm" in m for m in messages)
        assert any("count: 42" in m for m in messages)

    def test_cmd_explore_info_without_name_uses_configured_explore_root(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        custom_root = tmp_path / "stores" / "explore"
        custom_lib = custom_root / "alpha"
        custom_lib.mkdir(parents=True)
        (custom_lib / "meta.json").write_text(
            json.dumps({"count": 5, "query": {"issn": "1111-2222"}, "fetched_at": "2026-04-18T00:00:00"}),
            encoding="utf-8",
        )

        legacy_root = tmp_path / "data" / "explore" / "legacy"
        legacy_root.mkdir(parents=True)
        (legacy_root / "meta.json").write_text(
            json.dumps({"count": 9, "query": {"issn": "9999-9999"}, "fetched_at": "2026-04-17T00:00:00"}),
            encoding="utf-8",
        )

        cfg = SimpleNamespace(_root=tmp_path, explore_root=custom_root)
        args = Namespace(explore_action="info", name=None)

        cli.cmd_explore(args, cfg)

        assert any("alpha:" in m for m in messages)
        assert all("legacy:" not in m for m in messages)


class TestWorkspaceCliConfiguredRoots:
    def test_resolve_ws_paper_ids_uses_configured_workspace_dir(self, tmp_path):
        custom_root = tmp_path / "projects"
        custom_ws = custom_root / "study" / "refs"
        custom_ws.mkdir(parents=True)
        (custom_ws / "papers.json").write_text(
            json.dumps([{"id": "paper-custom", "dir_name": "Paper-Custom"}]),
            encoding="utf-8",
        )

        legacy_ws = tmp_path / "workspace" / "study"
        legacy_ws.mkdir(parents=True)
        (legacy_ws / "papers.json").write_text(
            json.dumps([{"id": "paper-legacy", "dir_name": "Paper-Legacy"}]),
            encoding="utf-8",
        )

        cfg = SimpleNamespace(_root=tmp_path, workspace_dir=custom_root)

        assert cli._resolve_ws_paper_ids(Namespace(ws="study"), cfg) == {"paper-custom"}

    def test_resolve_ws_paper_ids_supports_future_refs_layout(self, tmp_path):
        custom_root = tmp_path / "projects"
        custom_ws = custom_root / "study" / "refs"
        custom_ws.mkdir(parents=True)
        (custom_ws / "papers.json").write_text(
            json.dumps([{"id": "paper-future", "dir_name": "Paper-Future"}]),
            encoding="utf-8",
        )

        cfg = SimpleNamespace(_root=tmp_path, workspace_dir=custom_root)

        assert cli._resolve_ws_paper_ids(Namespace(ws="study"), cfg) == {"paper-future"}

    def test_cmd_ws_init_uses_configured_workspace_dir(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        custom_root = tmp_path / "projects"
        cfg = SimpleNamespace(_root=tmp_path, workspace_dir=custom_root, index_db=tmp_path / "index.db")
        args = Namespace(ws_action="init", name="study")

        cli.cmd_ws(args, cfg)

        assert (custom_root / "study" / "refs" / "papers.json").exists()
        assert not (tmp_path / "workspace" / "study").exists()
        assert any(str(custom_root / "study") in m for m in messages)

    def test_cmd_ws_add_updates_future_refs_layout_without_creating_legacy_index(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        custom_root = tmp_path / "projects"
        ws_dir = custom_root / "study" / "refs"
        ws_dir.mkdir(parents=True)
        (ws_dir / "papers.json").write_text("[]\n", encoding="utf-8")

        cfg = SimpleNamespace(_root=tmp_path, workspace_dir=custom_root, index_db=tmp_path / "index.db")
        args = Namespace(
            ws_action="add", name="study", paper_refs=["paper-a"], add_all=False, add_topic=None, add_search=None
        )

        monkeypatch.setattr(
            "scholaraio.services.index.lookup_paper",
            lambda db_path, ref: {"id": "paper-a", "dir_name": "Paper-A"},
        )

        cli.cmd_ws(args, cfg)

        assert not (custom_root / "study" / "papers.json").exists()
        entries = json.loads((custom_root / "study" / "refs" / "papers.json").read_text(encoding="utf-8"))
        assert [entry["id"] for entry in entries] == ["paper-a"]
        assert any("Added 1 papers to study" in m for m in messages)

    def test_cmd_ws_list_shows_manifest_summary(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        custom_root = tmp_path / "projects"
        ws_dir = custom_root / "study" / "refs"
        ws_dir.mkdir(parents=True)
        (ws_dir / "papers.json").write_text("[]\n", encoding="utf-8")
        (custom_root / "study" / "workspace.yaml").write_text(
            """
schema_version: 1
description: Drafting workspace for review writing
tags:
  - review
  - turbulence
""".strip()
            + "\n",
            encoding="utf-8",
        )

        cfg = SimpleNamespace(_root=tmp_path, workspace_dir=custom_root, index_db=tmp_path / "index.db")
        args = Namespace(ws_action="list")

        cli.cmd_ws(args, cfg)

        assert any("study (0 papers)" in m for m in messages)
        assert any("Description: Drafting workspace for review writing" in m for m in messages)
        assert any("Tags: review, turbulence" in m for m in messages)

    def test_cmd_ws_show_shows_manifest_details(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        custom_root = tmp_path / "projects"
        ws_dir = custom_root / "study" / "refs"
        ws_dir.mkdir(parents=True)
        (ws_dir / "papers.json").write_text(
            json.dumps([{"id": "paper-a", "dir_name": "Paper-A", "added_at": "2024-01-01"}]),
            encoding="utf-8",
        )
        (custom_root / "study" / "workspace.yaml").write_text(
            """
schema_version: 1
name: Turbulence Review
description: Workspace for the main review draft
tags:
  - review
  - turbulence
mounts:
  explore:
    - survey-2026
  toolref:
    - openfoam-2312
outputs:
  default_dir: outputs/reports
""".strip()
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(
            "scholaraio.services.index.lookup_paper",
            lambda db_path, ref: {"id": "paper-a", "dir_name": "Paper-A"},
        )

        cfg = SimpleNamespace(_root=tmp_path, workspace_dir=custom_root, index_db=tmp_path / "index.db")
        args = Namespace(ws_action="show", name="study")

        cli.cmd_ws(args, cfg)

        assert any("workspace study: 1 papers" in m for m in messages)
        assert any("Name: Turbulence Review" in m for m in messages)
        assert any("Description: Workspace for the main review draft" in m for m in messages)
        assert any("Tags: review, turbulence" in m for m in messages)
        assert any("Default output directory: outputs/reports" in m for m in messages)
        assert any("explore mounts: survey-2026" in m for m in messages)
        assert any("toolref mounts: openfoam-2312" in m for m in messages)
        assert any("Paper-A" in m for m in messages)

    def test_cmd_ws_show_ignores_unknown_mount_buckets(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        custom_root = tmp_path / "projects"
        ws_dir = custom_root / "study"
        ws_dir.mkdir(parents=True)
        (ws_dir / "papers.json").write_text("[]\n", encoding="utf-8")
        (ws_dir / "workspace.yaml").write_text(
            """
schema_version: 1
mounts:
  explore:
    - survey-2026
  custom:
    - future-store
""".strip()
            + "\n",
            encoding="utf-8",
        )

        cfg = SimpleNamespace(_root=tmp_path, workspace_dir=custom_root, index_db=tmp_path / "index.db")
        args = Namespace(ws_action="show", name="study")

        cli.cmd_ws(args, cfg)

        assert any("explore mounts: survey-2026" in m for m in messages)
        assert not any("custom mounts: future-store" in m for m in messages)

    def test_cmd_ws_show_keeps_newer_manifest_schema_opaque(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        custom_root = tmp_path / "projects"
        ws_dir = custom_root / "study"
        ws_dir.mkdir(parents=True)
        (ws_dir / "papers.json").write_text("[]\n", encoding="utf-8")
        (ws_dir / "workspace.yaml").write_text(
            """
schema_version: 2
name: Future Workspace
description: This should stay opaque
tags:
  - hidden
mounts:
  explore:
    - survey-2026
outputs:
  default_dir: outputs/reports
""".strip()
            + "\n",
            encoding="utf-8",
        )

        cfg = SimpleNamespace(_root=tmp_path, workspace_dir=custom_root, index_db=tmp_path / "index.db")
        args = Namespace(ws_action="show", name="study")

        cli.cmd_ws(args, cfg)

        assert any("workspace study: 0 papers" in m for m in messages)
        assert not any("Future Workspace" in m for m in messages)
        assert not any("This should stay opaque" in m for m in messages)
        assert not any("survey-2026" in m for m in messages)
        assert not any("outputs/reports" in m for m in messages)

    def test_export_docx_defaults_to_configured_workspace_dir(self, tmp_path, monkeypatch):
        source = tmp_path / "note.md"
        source.write_text("# Title\n\ncontent", encoding="utf-8")

        seen: dict[str, Path | str | None] = {}

        def fake_export_docx(content, output, title=None):
            seen["content"] = content
            seen["output"] = output
            seen["title"] = title

        monkeypatch.setattr("scholaraio.services.export.export_docx", fake_export_docx)

        cfg = SimpleNamespace(_root=tmp_path, workspace_dir=tmp_path / "projects")
        args = Namespace(input=str(source), output=None, title=None)

        cli._cmd_export_docx(args, cfg)

        assert seen["content"] == "# Title\n\ncontent"
        assert seen["output"] == tmp_path / "projects" / "output.docx"

    def test_export_docx_uses_cli_default_output_helper(self, tmp_path, monkeypatch):
        source = tmp_path / "note.md"
        source.write_text("# Title\n\ncontent", encoding="utf-8")

        seen: dict[str, Path | str | None] = {}

        def fake_export_docx(content, output, title=None):
            seen["content"] = content
            seen["output"] = output
            seen["title"] = title

        monkeypatch.setattr("scholaraio.services.export.export_docx", fake_export_docx)
        monkeypatch.setattr(
            cli,
            "_default_docx_output_path",
            lambda cfg: tmp_path / "projects" / "_system" / "output" / "note.docx",
            raising=False,
        )

        cfg = SimpleNamespace(_root=tmp_path, workspace_dir=tmp_path / "projects")
        args = Namespace(input=str(source), output=None, title=None)

        cli._cmd_export_docx(args, cfg)

        assert seen["content"] == "# Title\n\ncontent"
        assert seen["output"] == tmp_path / "projects" / "_system" / "output" / "note.docx"

    def test_export_docx_uses_configured_output_path_accessor(self, tmp_path, monkeypatch):
        source = tmp_path / "note.md"
        source.write_text("# Title\n\ncontent", encoding="utf-8")

        seen: dict[str, Path | str | None] = {}

        def fake_export_docx(content, output, title=None):
            seen["content"] = content
            seen["output"] = output
            seen["title"] = title

        monkeypatch.setattr("scholaraio.services.export.export_docx", fake_export_docx)

        cfg = SimpleNamespace(
            _root=tmp_path,
            workspace_dir=tmp_path / "projects",
            workspace_docx_output_path=tmp_path / "projects" / "_system" / "output" / "output.docx",
        )
        args = Namespace(input=str(source), output=None, title=None)

        cli._cmd_export_docx(args, cfg)

        assert seen["content"] == "# Title\n\ncontent"
        assert seen["output"] == tmp_path / "projects" / "_system" / "output" / "output.docx"

    def test_import_zotero_collections_as_workspaces_uses_configured_workspace_dir(self, tmp_path, monkeypatch):
        papers_dir = tmp_path / "papers"
        paper_dir = papers_dir / "Smith-2024-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(
            json.dumps({"id": "paper-1", "doi": "10.1000/test", "title": "Test Paper"}),
            encoding="utf-8",
        )

        seen: dict[str, object] = {}

        monkeypatch.setattr(
            "scholaraio.providers.zotero.list_collections_local",
            lambda _path: [{"key": "coll-1", "name": "Heat Transfer"}],
        )
        monkeypatch.setattr(
            "scholaraio.providers.zotero.parse_zotero_local",
            lambda _path, collection_key=None: ([SimpleNamespace(doi="10.1000/test")], None),
        )
        monkeypatch.setattr(
            "scholaraio.projects.workspace.create",
            lambda ws_dir: seen.setdefault("create", ws_dir),
        )
        monkeypatch.setattr(
            "scholaraio.projects.workspace.add",
            lambda ws_dir, uuids, db_path: seen.setdefault("add", (ws_dir, tuple(uuids), db_path)),
        )

        cfg = SimpleNamespace(
            papers_dir=papers_dir,
            workspace_dir=tmp_path / "projects",
            index_db=tmp_path / "index.db",
        )
        args = Namespace(local=str(tmp_path / "zotero.sqlite"))

        cli._import_zotero_collections_as_workspaces(
            args,
            cfg,
            api_key="",
            library_id="library-id",
            library_type="user",
        )

        expected_ws = tmp_path / "projects" / "Heat_Transfer"
        assert seen["create"] == expected_ws
        assert seen["add"] == (expected_ws, ("paper-1",), tmp_path / "index.db")


class TestArxivCliConfiguredRoots:
    def test_arxiv_fetch_downloads_to_configured_inbox_without_ingest(self, tmp_path, monkeypatch):
        messages: list[str] = []
        seen: dict[str, Path] = {}

        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("scholaraio.providers.arxiv.normalize_arxiv_ref", lambda ref: "2603.25200")

        def fake_download(arxiv_id, inbox_dir, overwrite=False):
            seen["inbox_dir"] = inbox_dir
            inbox_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = inbox_dir / f"{arxiv_id}.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")
            return pdf_path

        monkeypatch.setattr("scholaraio.providers.arxiv.download_arxiv_pdf", fake_download)

        custom_inbox = tmp_path / "stores" / "inbox"
        cfg = SimpleNamespace(_root=tmp_path, inbox_dir=custom_inbox)
        args = Namespace(arxiv_ref="2603.25200", ingest=False, force=False, dry_run=False)

        cli.cmd_arxiv_fetch(args, cfg)

        assert seen["inbox_dir"] == custom_inbox
        assert not (tmp_path / "data" / "inbox" / "2603.25200.pdf").exists()
        assert any(str(custom_inbox / "2603.25200.pdf") in m for m in messages)


class TestEnrichTocCliProgress:
    def test_cmd_enrich_toc_reports_single_paper_success(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        def fake_enrich_toc(json_path, md_path, cfg, *, force=False, inspect=False):
            data = json.loads(json_path.read_text(encoding="utf-8"))
            data["toc"] = [{"line": 1, "level": 1, "title": "Introduction"}]
            json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return True

        monkeypatch.setattr("scholaraio.services.loader.enrich_toc", fake_enrich_toc)

        cfg = SimpleNamespace(papers_dir=tmp_papers)
        args = Namespace(all=False, paper_id="Smith-2023-Turbulence", force=True, inspect=False)

        cli.cmd_enrich_toc(args, cfg)

        assert any("Extracting TOC" in m for m in messages)
        assert any("TOC extraction completed" in m and "1 sections" in m for m in messages)

    def test_cmd_enrich_toc_all_uses_llm_concurrency_budget(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        max_workers_seen: list[int] = []
        submitted: list[str] = []

        class FakeExecutor:
            def __init__(self, max_workers):
                max_workers_seen.append(max_workers)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn, *args, **kwargs):
                submitted.append(args[0].parent.name)
                fut = concurrent.futures.Future()
                fut.set_result(fn(*args, **kwargs))
                return fut

        monkeypatch.setattr(cli.concurrent.futures, "ThreadPoolExecutor", FakeExecutor)
        monkeypatch.setattr(cli.concurrent.futures, "as_completed", lambda futures: list(futures))

        def fake_enrich_toc(json_path, md_path, cfg, *, force=False, inspect=False):
            data = json.loads(json_path.read_text(encoding="utf-8"))
            data["toc"] = [{"line": 1, "level": 1, "title": json_path.parent.name}]
            json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return True

        monkeypatch.setattr("scholaraio.services.loader.enrich_toc", fake_enrich_toc)

        cfg = SimpleNamespace(papers_dir=tmp_papers, llm=SimpleNamespace(concurrency=7))
        args = Namespace(all=True, paper_id=None, force=True, inspect=False)

        cli.cmd_enrich_toc(args, cfg)

        assert max_workers_seen == [2]
        assert submitted == [
            "Smith-2023-Turbulence",
            "Wang-2024-DeepLearning",
        ]
        assert any("Smith-2023-Turbulence" in m and "Start processing" in m for m in messages)
        assert any("Wang-2024-DeepLearning" in m and "Start processing" in m for m in messages)
        assert any("Smith-2023-Turbulence" in m and "TOC extraction completed" in m for m in messages)
        assert any("Wang-2024-DeepLearning" in m and "TOC extraction completed" in m for m in messages)
        assert any("Done: 2 succeeded | 0 failed | 0 skipped" in m for m in messages)


class TestEnrichL3CliBatchRetries:
    def test_cmd_enrich_l3_all_retries_failed_papers_with_backoff(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        sleep_delays: list[float] = []
        monkeypatch.setattr(cli.time, "sleep", sleep_delays.append)

        attempts: dict[str, int] = {}

        class FakeExecutor:
            def __init__(self, max_workers):
                self.max_workers = max_workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn, *args, **kwargs):
                fut = concurrent.futures.Future()
                try:
                    fut.set_result(fn(*args, **kwargs))
                except Exception as exc:
                    fut.set_exception(exc)
                return fut

        monkeypatch.setattr(cli.concurrent.futures, "ThreadPoolExecutor", FakeExecutor)
        monkeypatch.setattr(cli.concurrent.futures, "as_completed", lambda futures: list(futures))

        def fake_enrich_l3(json_path, md_path, cfg, *, force=False, max_retries=2, inspect=False):
            name = json_path.parent.name
            attempts[name] = attempts.get(name, 0) + 1
            if name == "Smith-2023-Turbulence" and attempts[name] < 3:
                raise TimeoutError("transient")
            return True

        monkeypatch.setattr("scholaraio.services.loader.enrich_l3", fake_enrich_l3)

        cfg = SimpleNamespace(papers_dir=tmp_papers, llm=SimpleNamespace(concurrency=4))
        args = Namespace(all=True, paper_id=None, force=True, inspect=False, max_retries=2)

        cli.cmd_enrich_l3(args, cfg)

        assert attempts == {
            "Smith-2023-Turbulence": 3,
            "Wang-2024-DeepLearning": 1,
        }
        assert sleep_delays == [1.0, 2.0]
        assert any("Smith-2023-Turbulence" in m and "Start processing" in m for m in messages)
        assert any("Wang-2024-DeepLearning" in m and "Start processing" in m for m in messages)
        assert any("Smith-2023-Turbulence" in m and "Succeeded after retry" in m for m in messages)
        assert any("Smith-2023-Turbulence" in m and "Conclusion extraction completed" in m for m in messages)
        assert any("Wang-2024-DeepLearning" in m and "Conclusion extraction completed" in m for m in messages)
        assert any("Done: 2 succeeded | 0 failed | 0 skipped" in m for m in messages)


class TestImportEndnoteOptionalDeps:
    def test_import_endnote_reports_missing_optional_dependency(self, tmp_path, monkeypatch):
        src = tmp_path / "library.xml"
        src.write_text("<xml />", encoding="utf-8")

        errors: list[str] = []

        monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
        monkeypatch.setattr(
            "scholaraio.providers.endnote._load_endnote_core",
            lambda: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'endnote_utils'", name="endnote_utils")),
        )

        cfg = SimpleNamespace()
        args = Namespace(files=[str(src)], no_api=False, dry_run=True, no_convert=False)

        try:
            cli.cmd_import_endnote(args, cfg)
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")

        assert any("Missing dependency: endnote_utils" in msg for msg in errors)
        assert any("pip install scholaraio[import]" in msg for msg in errors)


class TestOptionalDependencyHints:
    def test_office_dependency_hint_uses_scholaraio_extra(self, monkeypatch):
        errors: list[str] = []
        monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))

        try:
            cli._check_import_error(ModuleNotFoundError("No module named 'docx'", name="docx"))
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")

        assert any("Missing dependency: docx" in msg for msg in errors)
        assert any("pip install scholaraio[office]" in msg for msg in errors)

    def test_pdf_dependency_hint_uses_scholaraio_extra(self, monkeypatch):
        errors: list[str] = []
        monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))

        try:
            cli._check_import_error(ModuleNotFoundError("No module named 'fitz'", name="fitz"))
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")

        assert any("Missing dependency: fitz" in msg for msg in errors)
        assert any("pip install scholaraio[pdf]" in msg for msg in errors)


class TestTopicCliErrors:
    def test_cmd_topics_reports_embedding_disabled_cleanly(self, tmp_path, monkeypatch):
        errors: list[str] = []
        monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
        monkeypatch.setattr(
            "scholaraio.services.topics.build_topics",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                FileNotFoundError("Current embed.provider=none; cannot build a topic model")
            ),
        )

        cfg = SimpleNamespace(
            index_db=tmp_path / "index.db",
            papers_dir=tmp_path / "papers",
            topics_model_dir=tmp_path / "topic_model",
            topics=SimpleNamespace(min_topic_size=5, nr_topics=0),
        )
        args = Namespace(
            build=True,
            rebuild=False,
            min_topic_size=None,
            nr_topics=None,
            reduce=None,
            merge=None,
            topic=None,
            show_outliers=False,
            viz=False,
        )

        try:
            cli.cmd_topics(args, cfg)
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")

        assert any("embed.provider=none" in msg for msg in errors)

    def test_cmd_explore_topics_reports_embedding_disabled_cleanly(self, tmp_path, monkeypatch):
        errors: list[str] = []
        monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
        monkeypatch.setattr("scholaraio.stores.explore._explore_dir", lambda *_args, **_kwargs: tmp_path / "explore")
        monkeypatch.setattr(
            "scholaraio.stores.explore.build_explore_topics",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                FileNotFoundError("Current embed.provider=none; cannot build a topic model")
            ),
        )

        cfg = SimpleNamespace()
        args = Namespace(
            explore_action="topics",
            name="demo",
            build=True,
            rebuild=False,
            min_topic_size=None,
            nr_topics=None,
            topic=None,
            top=None,
        )

        try:
            cli.cmd_explore(args, cfg)
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")

        assert any("embed.provider=none" in msg for msg in errors)

    def test_cmd_explore_search_semantic_reports_embedding_disabled_cleanly(self, monkeypatch):
        errors: list[str] = []
        monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
        monkeypatch.setattr(
            "scholaraio.stores.explore.explore_vsearch",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                FileNotFoundError("Current embed.provider=none; semantic vector search is disabled")
            ),
        )

        cfg = SimpleNamespace()
        args = Namespace(
            explore_action="search",
            name="demo",
            query=["turbulence"],
            mode="semantic",
            top=5,
        )

        try:
            cli.cmd_explore(args, cfg)
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("expected SystemExit")

        assert any("embed.provider=none" in msg for msg in errors)


class TestAttachPdfFallback:
    def test_attach_pdf_falls_back_without_cloud_key(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
        src_pdf = tmp_path / "input.pdf"
        src_pdf.write_bytes(b"%PDF-1.4\n")

        cfg = SimpleNamespace(
            ingest=SimpleNamespace(
                mineru_endpoint="http://localhost:8000",
                mineru_cloud_url="https://mineru.net/api/v4",
                mineru_backend_local="pipeline",
                mineru_model_version_cloud="v1",
                mineru_lang="en",
                mineru_parse_method="auto",
                mineru_enable_formula=True,
                mineru_enable_table=True,
                mineru_poll_timeout=900,
                pdf_fallback_order=["auto"],
                pdf_fallback_auto_detect=True,
            ),
            papers_dir=tmp_path / "papers",
        )
        cfg.resolved_mineru_api_key = lambda: ""

        monkeypatch.setattr(cli, "_resolve_paper", lambda *_: paper_dir)
        monkeypatch.setattr(cli, "ui", lambda *_args, **_kwargs: None)

        import scholaraio.providers.mineru as mineru
        import scholaraio.providers.pdf_fallback as pdf_fallback

        _allow_pdf_validation(monkeypatch)
        monkeypatch.setattr(mineru, "check_server", lambda *_: False)

        calls: list[tuple[Path, Path]] = []

        def _fallback(pdf_path, md_path, parser_order=None, auto_detect=True):
            calls.append((pdf_path, md_path))
            md_path.write_text("fallback attach ok\n", encoding="utf-8")
            return True, "docling", None

        monkeypatch.setattr(pdf_fallback, "convert_pdf_with_fallback", _fallback)
        monkeypatch.setattr("scholaraio.stores.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_index", lambda *_: None)

        args = Namespace(paper_id="paper-1", pdf_path=str(src_pdf), dry_run=False)
        cli.cmd_attach_pdf(args, cfg)

        assert calls == [(paper_dir / "input.pdf", paper_dir / "paper.md")]
        assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "fallback attach ok\n"
        assert not (paper_dir / "input.pdf").exists()

    def test_attach_pdf_prefers_configured_fallback_without_result_object(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
        src_pdf = tmp_path / "input.pdf"
        src_pdf.write_bytes(b"%PDF-1.4\n")

        cfg = SimpleNamespace(
            ingest=SimpleNamespace(
                mineru_endpoint="http://localhost:8000",
                mineru_cloud_url="https://mineru.net/api/v4",
                mineru_backend_local="pipeline",
                mineru_model_version_cloud="v1",
                mineru_lang="en",
                mineru_parse_method="auto",
                mineru_enable_formula=True,
                mineru_enable_table=True,
                mineru_poll_timeout=900,
                pdf_preferred_parser="docling",
                pdf_fallback_order=["auto"],
                pdf_fallback_auto_detect=True,
            ),
            papers_dir=tmp_path / "papers",
        )
        cfg.resolved_mineru_api_key = lambda: ""

        monkeypatch.setattr(cli, "_resolve_paper", lambda *_: paper_dir)
        monkeypatch.setattr(cli, "ui", lambda *_args, **_kwargs: None)

        import scholaraio.providers.mineru as mineru
        import scholaraio.providers.pdf_fallback as pdf_fallback

        monkeypatch.setattr(
            mineru,
            "validate_pdf_for_mineru",
            lambda _path: PDFValidationResult(ok=False, error="PDF validation failed: should not run"),
        )
        monkeypatch.setattr(
            mineru,
            "check_server",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("fallback-only path should not check MinerU")
            ),
        )

        calls: list[tuple[Path, Path]] = []

        def _fallback(pdf_path, md_path, parser_order=None, auto_detect=True):
            calls.append((pdf_path, md_path))
            md_path.write_text("preferred attach ok\n", encoding="utf-8")
            return True, "docling", None

        monkeypatch.setattr(pdf_fallback, "convert_pdf_with_fallback", _fallback)
        monkeypatch.setattr("scholaraio.stores.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_index", lambda *_: None)

        args = Namespace(paper_id="paper-1", pdf_path=str(src_pdf), dry_run=False)
        cli.cmd_attach_pdf(args, cfg)

        assert calls == [(paper_dir / "input.pdf", paper_dir / "paper.md")]
        assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "preferred attach ok\n"

    def test_attach_pdf_cloud_does_not_split_when_under_new_limits(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
        src_pdf = tmp_path / "input.pdf"
        src_pdf.write_bytes(b"%PDF-1.4\n")

        cfg = SimpleNamespace(
            ingest=SimpleNamespace(
                mineru_endpoint="http://localhost:8000",
                mineru_cloud_url="https://mineru.net/api/v4",
                mineru_backend_local="pipeline",
                mineru_model_version_cloud="pipeline",
                mineru_lang="en",
                mineru_parse_method="auto",
                mineru_enable_formula=True,
                mineru_enable_table=True,
                mineru_poll_timeout=900,
                chunk_page_limit=100,
                pdf_fallback_order=["auto"],
                pdf_fallback_auto_detect=True,
            ),
            papers_dir=tmp_path / "papers",
        )
        cfg.resolved_mineru_api_key = lambda: "token"

        monkeypatch.setattr(cli, "_resolve_paper", lambda *_: paper_dir)
        monkeypatch.setattr(cli, "ui", lambda *_args, **_kwargs: None)

        import scholaraio.providers.mineru as mineru

        _allow_pdf_validation(monkeypatch)
        monkeypatch.setattr(mineru, "check_server", lambda *_: False)
        monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
        monkeypatch.setattr(
            mineru,
            "_convert_long_pdf_cloud",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not split")),
        )
        monkeypatch.setattr(
            mineru,
            "convert_pdf_cloud",
            lambda pdf_path, *_args, **_kwargs: ConvertResult(
                pdf_path=pdf_path,
                md_path=paper_dir / "input.md",
                success=True,
            ),
        )
        monkeypatch.setattr("scholaraio.stores.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_index", lambda *_: None)
        (paper_dir / "input.md").write_text("ok\n", encoding="utf-8")

        args = Namespace(paper_id="paper-1", pdf_path=str(src_pdf), dry_run=False)
        cli.cmd_attach_pdf(args, cfg)

        assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "ok\n"

    def test_attach_pdf_cloud_uses_configured_poll_timeout(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
        src_pdf = tmp_path / "input.pdf"
        src_pdf.write_bytes(b"%PDF-1.4\n")

        cfg = SimpleNamespace(
            ingest=SimpleNamespace(
                mineru_endpoint="http://localhost:8000",
                mineru_cloud_url="https://mineru.net/api/v4",
                mineru_backend_local="pipeline",
                mineru_model_version_cloud="pipeline",
                mineru_lang="en",
                mineru_parse_method="auto",
                mineru_enable_formula=True,
                mineru_enable_table=True,
                mineru_poll_timeout=321,
                chunk_page_limit=100,
                pdf_fallback_order=["auto"],
                pdf_fallback_auto_detect=True,
            ),
            papers_dir=tmp_path / "papers",
        )
        cfg.resolved_mineru_api_key = lambda: "token"

        monkeypatch.setattr(cli, "_resolve_paper", lambda *_: paper_dir)
        monkeypatch.setattr(cli, "ui", lambda *_args, **_kwargs: None)

        import scholaraio.providers.mineru as mineru

        _allow_pdf_validation(monkeypatch)
        monkeypatch.setattr(mineru, "check_server", lambda *_: False)
        monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
        captured: dict[str, object] = {}

        def fake_convert_pdf_cloud(_pdf_path, opts, **_kwargs):
            captured["poll_timeout"] = opts.poll_timeout
            return ConvertResult(pdf_path=src_pdf, md_path=paper_dir / "input.md", success=True)

        monkeypatch.setattr(mineru, "convert_pdf_cloud", fake_convert_pdf_cloud)
        monkeypatch.setattr("scholaraio.stores.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_index", lambda *_: None)
        (paper_dir / "input.md").write_text("ok\n", encoding="utf-8")

        args = Namespace(paper_id="paper-1", pdf_path=str(src_pdf), dry_run=False)
        cli.cmd_attach_pdf(args, cfg)

        assert captured["poll_timeout"] == 321

    def test_attach_pdf_cloud_moves_nested_markdown_images(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
        src_pdf = tmp_path / "input.pdf"
        src_pdf.write_bytes(b"%PDF-1.4\n")

        cfg = SimpleNamespace(
            ingest=SimpleNamespace(
                mineru_endpoint="http://localhost:8000",
                mineru_cloud_url="https://mineru.net/api/v4",
                mineru_backend_local="pipeline",
                mineru_model_version_cloud="pipeline",
                mineru_lang="en",
                mineru_parse_method="auto",
                mineru_enable_formula=True,
                mineru_enable_table=True,
                mineru_poll_timeout=900,
                chunk_page_limit=100,
                pdf_fallback_order=["auto"],
                pdf_fallback_auto_detect=True,
            ),
            papers_dir=tmp_path / "papers",
        )
        cfg.resolved_mineru_api_key = lambda: "token"

        monkeypatch.setattr(cli, "_resolve_paper", lambda *_: paper_dir)
        monkeypatch.setattr(cli, "ui", lambda *_args, **_kwargs: None)

        import scholaraio.providers.mineru as mineru

        _allow_pdf_validation(monkeypatch)
        nested_dir = paper_dir / "flowchart"
        nested_dir.mkdir()
        nested_md = nested_dir / "index.md"
        nested_md.write_text("![img](images/fig.png)\n", encoding="utf-8")
        (nested_dir / "images").mkdir()
        (nested_dir / "images" / "fig.png").write_bytes(b"png")

        monkeypatch.setattr(mineru, "check_server", lambda *_: False)
        monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
        monkeypatch.setattr(
            mineru,
            "convert_pdf_cloud",
            lambda pdf_path, *_args, **_kwargs: ConvertResult(
                pdf_path=pdf_path,
                md_path=nested_md,
                success=True,
            ),
        )
        monkeypatch.setattr("scholaraio.stores.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_index", lambda *_: None)

        args = Namespace(paper_id="paper-1", pdf_path=str(src_pdf), dry_run=False)
        cli.cmd_attach_pdf(args, cfg)

        assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "![img](images/fig.png)\n"
        assert (paper_dir / "images" / "fig.png").exists()
        assert not nested_dir.exists()

    def test_attach_pdf_cloud_keeps_flat_images_without_self_move(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
        src_pdf = tmp_path / "input.pdf"
        src_pdf.write_bytes(b"%PDF-1.4\n")

        cfg = SimpleNamespace(
            ingest=SimpleNamespace(
                mineru_endpoint="http://localhost:8000",
                mineru_cloud_url="https://mineru.net/api/v4",
                mineru_backend_local="pipeline",
                mineru_model_version_cloud="pipeline",
                mineru_lang="en",
                mineru_parse_method="auto",
                mineru_enable_formula=True,
                mineru_enable_table=True,
                mineru_poll_timeout=900,
                chunk_page_limit=100,
                pdf_fallback_order=["auto"],
                pdf_fallback_auto_detect=True,
            ),
            papers_dir=tmp_path / "papers",
        )
        cfg.resolved_mineru_api_key = lambda: "token"

        monkeypatch.setattr(cli, "_resolve_paper", lambda *_: paper_dir)
        monkeypatch.setattr(cli, "ui", lambda *_args, **_kwargs: None)

        import scholaraio.providers.mineru as mineru

        _allow_pdf_validation(monkeypatch)
        flat_md = paper_dir / "flowchart.md"
        flat_md.write_text("![img](images/fig.png)\n", encoding="utf-8")
        (paper_dir / "images").mkdir()
        (paper_dir / "images" / "fig.png").write_bytes(b"png")

        monkeypatch.setattr(mineru, "check_server", lambda *_: False)
        monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
        monkeypatch.setattr(
            mineru,
            "convert_pdf_cloud",
            lambda pdf_path, *_args, **_kwargs: ConvertResult(
                pdf_path=pdf_path,
                md_path=flat_md,
                success=True,
            ),
        )
        monkeypatch.setattr("scholaraio.stores.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_index", lambda *_: None)

        args = Namespace(paper_id="paper-1", pdf_path=str(src_pdf), dry_run=False)
        cli.cmd_attach_pdf(args, cfg)

        assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "![img](images/fig.png)\n"
        assert (paper_dir / "images" / "fig.png").exists()

    def test_attach_pdf_cloud_splits_when_new_limits_require_it(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
        src_pdf = tmp_path / "input.pdf"
        src_pdf.write_bytes(b"%PDF-1.4\n")

        cfg = SimpleNamespace(
            ingest=SimpleNamespace(
                mineru_endpoint="http://localhost:8000",
                mineru_cloud_url="https://mineru.net/api/v4",
                mineru_backend_local="pipeline",
                mineru_model_version_cloud="pipeline",
                mineru_lang="en",
                mineru_parse_method="auto",
                mineru_enable_formula=True,
                mineru_enable_table=True,
                mineru_poll_timeout=900,
                chunk_page_limit=100,
                pdf_fallback_order=["auto"],
                pdf_fallback_auto_detect=True,
            ),
            papers_dir=tmp_path / "papers",
        )
        cfg.resolved_mineru_api_key = lambda: "token"

        monkeypatch.setattr(cli, "_resolve_paper", lambda *_: paper_dir)
        monkeypatch.setattr(cli, "ui", lambda *_args, **_kwargs: None)

        import scholaraio.providers.mineru as mineru

        _allow_pdf_validation(monkeypatch)
        monkeypatch.setattr(mineru, "check_server", lambda *_: False)
        monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (True, 320, "too large"))
        monkeypatch.setattr(
            mineru,
            "convert_pdf_cloud",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should use split path")),
        )
        captured: dict[str, object] = {}

        def fake_convert_long(pdf_path, opts, *, api_key, cloud_url, chunk_size):
            captured["chunk_size"] = chunk_size
            (paper_dir / "input.md").write_text("split ok\n", encoding="utf-8")
            return ConvertResult(pdf_path=pdf_path, md_path=paper_dir / "input.md", success=True)

        monkeypatch.setattr(mineru, "_convert_long_pdf_cloud", fake_convert_long)
        monkeypatch.setattr("scholaraio.stores.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_index", lambda *_: None)

        args = Namespace(paper_id="paper-1", pdf_path=str(src_pdf), dry_run=False)
        cli.cmd_attach_pdf(args, cfg)

        assert captured["chunk_size"] == 320
        assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "split ok\n"
        assert not (paper_dir / "input.pdf").exists()

    def test_attach_pdf_cloud_split_importerror_falls_back(self, tmp_path, monkeypatch):
        paper_dir = tmp_path / "papers" / "Smith-2023-Test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text("{}", encoding="utf-8")
        src_pdf = tmp_path / "input.pdf"
        src_pdf.write_bytes(b"%PDF-1.4\n")
        messages: list[str] = []

        cfg = SimpleNamespace(
            ingest=SimpleNamespace(
                mineru_endpoint="http://localhost:8000",
                mineru_cloud_url="https://mineru.net/api/v4",
                mineru_backend_local="pipeline",
                mineru_model_version_cloud="pipeline",
                mineru_lang="en",
                mineru_parse_method="auto",
                mineru_enable_formula=True,
                mineru_enable_table=True,
                mineru_poll_timeout=900,
                chunk_page_limit=100,
                pdf_fallback_order=["auto"],
                pdf_fallback_auto_detect=True,
            ),
            papers_dir=tmp_path / "papers",
        )
        cfg.resolved_mineru_api_key = lambda: "token"

        monkeypatch.setattr(cli, "_resolve_paper", lambda *_: paper_dir)
        monkeypatch.setattr(cli, "ui", messages.append)

        import scholaraio.providers.mineru as mineru
        import scholaraio.providers.pdf_fallback as pdf_fallback

        _allow_pdf_validation(monkeypatch)
        monkeypatch.setattr(mineru, "check_server", lambda *_: False)
        monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (True, 320, "too large"))
        monkeypatch.setattr(
            mineru,
            "_convert_long_pdf_cloud",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ImportError("install pymupdf")),
        )
        monkeypatch.setattr(
            pdf_fallback,
            "convert_pdf_with_fallback",
            lambda _pdf, md_path, **_kwargs: (
                md_path.write_text("fallback attach ok\n", encoding="utf-8"),
                True,
                "docling",
                None,
            )[1:],
        )
        monkeypatch.setattr("scholaraio.stores.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.services.ingest.pipeline.step_index", lambda *_: None)

        args = Namespace(paper_id="paper-1", pdf_path=str(src_pdf), dry_run=False)
        cli.cmd_attach_pdf(args, cfg)

        assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "fallback attach ok\n"
        assert any("scholaraio[pdf]" in msg for msg in messages)


class TestSetupMetricsFallback:
    def test_setup_check_skips_metrics_init_failure(self, tmp_path, monkeypatch):
        messages: list[str] = []

        monkeypatch.setattr(
            cli,
            "load_config",
            lambda: SimpleNamespace(
                ensure_dirs=lambda: None,
                metrics_db_path="/tmp/metrics.db",
                instance_meta_path=tmp_path / "instance.json",
                ingest=SimpleNamespace(contact_email=""),
                resolved_s2_api_key=lambda: "",
            ),
        )
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("scholaraio.core.log.setup", lambda cfg: "session-1")

        def _boom(*_args, **_kwargs):
            raise RuntimeError("database is locked")

        monkeypatch.setattr("scholaraio.services.metrics.init", _boom)
        monkeypatch.setattr("scholaraio.services.ingest_metadata._models.configure_session", lambda *_: None)
        monkeypatch.setattr("scholaraio.services.ingest_metadata._models.configure_s2_session", lambda *_: None)
        monkeypatch.setattr(cli, "cmd_setup", lambda args, cfg: print("SETUP_OK"))
        monkeypatch.setattr("sys.argv", ["scholaraio", "setup", "check", "--lang", "zh"])

        cli.main()

        assert any("metrics initialization failed and was skipped" in msg for msg in messages)

    def test_main_bootstraps_instance_metadata(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)

        monkeypatch.setattr(cli, "load_config", lambda: cfg)
        monkeypatch.setattr("scholaraio.core.log.setup", lambda _cfg: "session-1")
        monkeypatch.setattr("scholaraio.services.metrics.init", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("scholaraio.services.ingest_metadata._models.configure_session", lambda *_: None)
        monkeypatch.setattr("scholaraio.services.ingest_metadata._models.configure_s2_session", lambda *_: None)
        monkeypatch.setattr(cli, "cmd_metrics", lambda args, cfg: None)
        monkeypatch.setattr("sys.argv", ["scholaraio", "metrics", "--summary"])

        cli.main()

        assert cfg.instance_meta_path.exists()
        payload = json.loads(cfg.instance_meta_path.read_text(encoding="utf-8"))
        assert payload["layout_state"] == "legacy_implicit"
        assert payload["instance_id"]


class TestMigrationLockGating:
    def test_main_blocks_non_migrate_commands_while_lock_exists(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        ensure_instance_metadata(cfg)
        write_migration_lock(cfg, migration_id="mig-001", pid=999999)

        messages: list[str] = []
        monkeypatch.setattr(cli, "load_config", lambda: cfg)
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("sys.argv", ["scholaraio", "metrics", "--summary"])

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 2
        assert any("migration.lock" in msg for msg in messages)
        assert any("scholaraio migrate status" in msg for msg in messages)
        assert any("scholaraio migrate recover --clear-lock" in msg for msg in messages)

    def test_main_allows_migrate_status_while_lock_exists(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        ensure_instance_metadata(cfg)
        write_migration_lock(cfg, migration_id="mig-001", pid=999999)

        messages: list[str] = []
        monkeypatch.setattr(cli, "load_config", lambda: cfg)
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("sys.argv", ["scholaraio", "migrate", "status"])

        cli.main()

        assert any("Migration lock status" in msg for msg in messages)
        assert any("mig-001" in msg for msg in messages)

    def test_cmd_migrate_recover_clear_lock_marks_instance_needs_recovery(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        meta = ensure_instance_metadata(cfg)
        meta["layout_state"] = "migrating"
        cfg.instance_meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        write_migration_lock(cfg, migration_id="mig-001", pid=999999)

        cli.cmd_migrate(Namespace(migrate_action="recover", clear_lock=True), cfg)

        stored = json.loads(cfg.instance_meta_path.read_text(encoding="utf-8"))
        assert not cfg.migration_lock_path.exists()
        assert stored["layout_state"] == "needs_recovery"
        assert any("Cleared migration.lock" in msg for msg in messages)
        assert any("needs_recovery" in msg for msg in messages)

    def test_migrate_status_reports_latest_journal(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        ensure_instance_metadata(cfg)
        ensure_migration_journal(cfg, migration_id="mig-20260418-001")

        messages: list[str] = []
        monkeypatch.setattr(cli, "load_config", lambda: cfg)
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("sys.argv", ["scholaraio", "migrate", "status"])

        cli.main()

        assert any("journal_count: 1" in msg for msg in messages)
        assert any("latest_journal: mig-20260418-001" in msg for msg in messages)

    def test_migrate_status_prefers_most_recent_journal_activity_over_lexical_order(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        ensure_instance_metadata(cfg)

        older = ensure_migration_journal(cfg, migration_id="zz-older")
        newer = ensure_migration_journal(cfg, migration_id="aa-newer")

        # Simulate a later finalize/verify touch on a lexically earlier id.
        newer_summary = newer / "summary.md"
        newer_summary.write_text(
            newer_summary.read_text(encoding="utf-8") + "\n- status: completed\n",
            encoding="utf-8",
        )
        newer_stamp = older.stat().st_mtime + 10
        os.utime(newer, (newer_stamp, newer_stamp))
        os.utime(newer_summary, (newer_stamp, newer_stamp))

        messages: list[str] = []
        monkeypatch.setattr(cli, "load_config", lambda: cfg)
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("sys.argv", ["scholaraio", "migrate", "status"])

        cli.main()

        assert any("journal_count: 2" in msg for msg in messages)
        assert any("latest_journal: aa-newer" in msg for msg in messages)


class TestFutureLayoutGating:
    def test_main_blocks_normal_commands_for_unsupported_future_layout(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        meta = ensure_instance_metadata(cfg)
        meta["layout_version"] = 99
        cfg.instance_meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        messages: list[str] = []
        monkeypatch.setattr(cli, "load_config", lambda: cfg)
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("sys.argv", ["scholaraio", "metrics", "--summary"])

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 2
        assert any("layout_version=99" in msg for msg in messages)
        assert any("This program supports up to layout version 1" in msg for msg in messages)
        assert any("scholaraio migrate status" in msg for msg in messages)

    def test_main_allows_migrate_status_for_unsupported_future_layout(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        meta = ensure_instance_metadata(cfg)
        meta["layout_version"] = 99
        cfg.instance_meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        messages: list[str] = []
        monkeypatch.setattr(cli, "load_config", lambda: cfg)
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("sys.argv", ["scholaraio", "migrate", "status"])

        cli.main()

        assert any("layout_version: 99" in msg for msg in messages)


class TestMigrationVerify:
    def test_cmd_migrate_verify_refreshes_latest_journal(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        ensure_instance_metadata(cfg)
        ensure_migration_journal(cfg, migration_id="mig-20260418-001")

        cli.cmd_migrate(Namespace(migrate_action="verify", migration_id=None), cfg)

        stored = json.loads(
            (cfg.migration_journals_root / "mig-20260418-001" / "verify.json").read_text(encoding="utf-8")
        )
        assert stored["status"] == "passed"
        assert any("Verification completed" in msg for msg in messages)
        assert any("mig-20260418-001" in msg for msg in messages)
        assert any("status: passed" in msg for msg in messages)

    def test_cmd_migrate_verify_requires_existing_journal(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        ensure_instance_metadata(cfg)

        with pytest.raises(SystemExit) as exc:
            cli.cmd_migrate(Namespace(migrate_action="verify", migration_id=None), cfg)

        assert exc.value.code == 2
        assert any("No migration journal found" in msg for msg in messages)


class TestMigrationPlan:
    def test_cmd_migrate_plan_writes_requested_journal(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        ensure_instance_metadata(cfg)

        cli.cmd_migrate(Namespace(migrate_action="plan", migration_id="mig-plan-20260418"), cfg)

        stored = json.loads(
            (cfg.migration_journals_root / "mig-plan-20260418" / "plan.json").read_text(encoding="utf-8")
        )
        assert stored["migration_id"] == "mig-plan-20260418"
        assert stored["plan_state"] == "planned"
        assert any("Plan completed" in msg for msg in messages)
        assert any("mig-plan-20260418" in msg for msg in messages)

    def test_cmd_migrate_plan_reports_planned_legacy_moves(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        ensure_instance_metadata(cfg)
        style_path = tmp_path / "data" / "citation_styles" / "custom.py"
        style_path.parent.mkdir(parents=True, exist_ok=True)
        style_path.write_text("def format_entry(entry):\n    return 'custom'\n", encoding="utf-8")

        cli.cmd_migrate(Namespace(migrate_action="plan", migration_id="mig-plan-20260419"), cfg)

        assert any("planned_legacy_moves: 1" in msg for msg in messages)


class TestMigrationCleanup:
    def test_cmd_migrate_cleanup_requires_successful_verify(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        ensure_instance_metadata(cfg)
        ensure_migration_journal(cfg, migration_id="mig-cleanup-20260419")

        with pytest.raises(SystemExit) as exc:
            cli.cmd_migrate(Namespace(migrate_action="cleanup", migration_id=None, confirm=False), cfg)

        assert exc.value.code == 2
        assert any("successful verification" in msg for msg in messages)

    def test_cmd_migrate_cleanup_records_preview_and_status(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        ensure_instance_metadata(cfg)
        ensure_migration_journal(cfg, migration_id="mig-cleanup-20260419")
        run_migration_verification(cfg, migration_id="mig-cleanup-20260419")

        cli.cmd_migrate(Namespace(migrate_action="cleanup", migration_id=None, confirm=False), cfg)
        assert any("Cleanup evaluation completed" in msg for msg in messages)
        assert any("status: preview" in msg for msg in messages)
        assert any("candidate_count: 0" in msg for msg in messages)

        messages.clear()
        cli.cmd_migrate(Namespace(migrate_action="cleanup", migration_id=None, confirm=True), cfg)
        assert any("status: completed_noop" in msg for msg in messages)
        assert any("removed_count: 0" in msg for msg in messages)

        messages.clear()
        cli.cmd_migrate(Namespace(migrate_action="status"), cfg)
        assert any("latest_cleanup_status: completed_noop" in msg for msg in messages)

    def test_cmd_migrate_cleanup_reports_archived_recorded_candidates(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        legacy_styles = tmp_path / "data" / "citation_styles"
        legacy_styles.mkdir(parents=True, exist_ok=True)
        (legacy_styles / "custom.py").write_text(
            "def format_ref(meta, idx=None):\n    return 'legacy'\n", encoding="utf-8"
        )

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()

        run_migration_store(cfg, store="citation_styles", migration_id="mig-run-20260420", confirm=True)

        cli.cmd_migrate(Namespace(migrate_action="cleanup", migration_id="mig-run-20260420", confirm=True), cfg)

        assert any("status: completed_archived" in msg for msg in messages)
        assert any("candidate_count: 1" in msg for msg in messages)
        assert any("archived_count: 1" in msg for msg in messages)
        assert any("removed_count: 0" in msg for msg in messages)
        assert not any("blocked_reason:" in msg for msg in messages)


class TestMigrationRun:
    def test_cmd_migrate_run_requires_confirm(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()

        with pytest.raises(SystemExit) as exc:
            cli.cmd_migrate(
                Namespace(
                    migrate_action="run", store="citation_styles", migration_id="mig-run-20260420", confirm=False
                ),
                cfg,
            )

        assert exc.value.code == 2
        assert any("--confirm" in msg for msg in messages)

    def test_cmd_migrate_run_citation_styles_reports_result(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        legacy_styles = tmp_path / "data" / "citation_styles"
        legacy_styles.mkdir(parents=True, exist_ok=True)
        (legacy_styles / "custom.py").write_text(
            "def format_ref(meta, idx=None):\n    return 'legacy ' + (meta.get('title') or '')\n",
            encoding="utf-8",
        )

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()

        cli.cmd_migrate(
            Namespace(migrate_action="run", store="citation_styles", migration_id="mig-run-20260420", confirm=True),
            cfg,
        )

        assert any("Migration run completed" in msg for msg in messages)
        assert any("store: citation_styles" in msg for msg in messages)
        assert any("copied_count: 1" in msg for msg in messages)
        assert any("cleanup_candidate_count: 1" in msg for msg in messages)
        assert any("verify_status: passed" in msg for msg in messages)

    def test_cmd_migrate_run_toolref_reports_result(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        _write_toolref_fixture(tmp_path / "data" / "toolref")

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()

        cli.cmd_migrate(
            Namespace(migrate_action="run", store="toolref", migration_id="mig-run-toolref-20260420", confirm=True),
            cfg,
        )

        assert any("Migration run completed" in msg for msg in messages)
        assert any("store: toolref" in msg for msg in messages)
        assert any("cleanup_candidate_count: 1" in msg for msg in messages)
        assert any("verify_status: passed" in msg for msg in messages)

    def test_cmd_migrate_run_explore_reports_result(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        _write_explore_fixture(tmp_path / "data" / "explore")

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()

        cli.cmd_migrate(
            Namespace(migrate_action="run", store="explore", migration_id="mig-run-explore-20260420", confirm=True),
            cfg,
        )

        assert any("Migration run completed" in msg for msg in messages)
        assert any("store: explore" in msg for msg in messages)
        assert any("cleanup_candidate_count: 1" in msg for msg in messages)
        assert any("verify_status: passed" in msg for msg in messages)

    def test_cmd_migrate_run_proceedings_reports_result(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        _write_proceedings_fixture(tmp_path / "data" / "proceedings")

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()

        cli.cmd_migrate(
            Namespace(
                migrate_action="run",
                store="proceedings",
                migration_id="mig-run-proceedings-20260420",
                confirm=True,
            ),
            cfg,
        )

        assert any("Migration run completed" in msg for msg in messages)
        assert any("store: proceedings" in msg for msg in messages)
        assert any("cleanup_candidate_count: 1" in msg for msg in messages)
        assert any("verify_status: passed" in msg for msg in messages)

    def test_cmd_migrate_run_spool_reports_result(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        _write_spool_fixture(tmp_path / "data")

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()

        cli.cmd_migrate(
            Namespace(
                migrate_action="run",
                store="spool",
                migration_id="mig-run-spool-20260420",
                confirm=True,
            ),
            cfg,
        )

        assert any("Migration run completed" in msg for msg in messages)
        assert any("store: spool" in msg for msg in messages)
        assert any("copied_count: 6" in msg for msg in messages)
        assert any("cleanup_candidate_count: 6" in msg for msg in messages)
        assert any("verify_status: passed" in msg for msg in messages)

    def test_cmd_migrate_run_papers_reports_result(self, tmp_path, monkeypatch):
        from scholaraio.services.index import build_index

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        _write_papers_fixture(tmp_path / "data" / "papers")

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        build_index(cfg.papers_dir, cfg.index_db, rebuild=True)

        cli.cmd_migrate(
            Namespace(
                migrate_action="run",
                store="papers",
                migration_id="mig-run-papers-20260420",
                confirm=True,
            ),
            cfg,
        )

        assert any("Migration run completed" in msg for msg in messages)
        assert any("store: papers" in msg for msg in messages)
        assert any("copied_count: 2" in msg for msg in messages)
        assert any("cleanup_candidate_count: 1" in msg for msg in messages)
        assert any("verify_status: passed" in msg for msg in messages)


class TestMigrationUpgrade:
    def test_cmd_migrate_upgrade_reports_one_command_result(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        legacy_styles = tmp_path / "data" / "citation_styles"
        legacy_styles.mkdir(parents=True, exist_ok=True)
        (legacy_styles / "custom.py").write_text(
            "def format_ref(meta, idx=None):\n    return 'legacy ' + (meta.get('title') or '')\n",
            encoding="utf-8",
        )
        paper_name = _write_papers_fixture(tmp_path / "data" / "papers")
        ws_dir = tmp_path / "workspace" / "demo-ws"
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / "papers.json").write_text(json.dumps([{"id": "paper-1", "dir_name": paper_name}]), encoding="utf-8")

        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()

        cli.cmd_migrate(
            Namespace(migrate_action="upgrade", migration_id="mig-upgrade-20260425", confirm=True),
            cfg,
        )

        assert any("Upgrade completed: mig-upgrade-20260425" in msg for msg in messages)
        assert any("status: completed" in msg for msg in messages)
        assert any("target_layout_version: 1" in msg for msg in messages)
        assert any("store_run_count: 3" in msg for msg in messages)
        assert any("stores: workspace, citation_styles, papers" in msg for msg in messages)
        assert any("finalize_status: completed" in msg for msg in messages)
        assert any("verify_after_cleanup: passed" in msg for msg in messages)
