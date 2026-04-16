"""Regression tests for localized CLI/setup messaging."""

from __future__ import annotations

import concurrent.futures
import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scholaraio import cli
from scholaraio.index import build_index
from scholaraio.ingest.mineru import ConvertResult, PDFValidationResult
from scholaraio.setup import _S
from scholaraio.translate import TranslateResult


def _allow_pdf_validation(monkeypatch):
    import scholaraio.ingest.mineru as mineru

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

        assert "面向 AI coding agent 的研究终端" in root_help
        assert "本地学术文献检索工具" not in root_help

    def test_setup_help_is_fully_localized(self):
        parser = cli._build_parser()
        setup_parser = parser._subparsers._group_actions[0].choices["setup"]
        setup_help = setup_parser.format_help()
        setup_check = setup_parser._subparsers._group_actions[0].choices["check"].format_help()

        assert "默认进入交互式安装向导" in setup_help
        assert "检查环境状态" in setup_help
        assert "输出语言（zh 或 en，默认 zh）" in setup_check
        assert "Start the interactive setup wizard" not in setup_help
        assert "Check environment status" not in setup_help
        assert "Output language" not in setup_check

    def test_toolref_fetch_help_uses_prefix_free_version_example(self):
        parser = cli._build_parser()
        toolref_parser = parser._subparsers._group_actions[0].choices["toolref"]
        toolref_fetch = toolref_parser._subparsers._group_actions[0].choices["fetch"].format_help()

        assert "版本号（如 7.5, 22Jul2025_update3）" in toolref_fetch
        assert "stable_22Jul2025_update3" not in toolref_fetch

    def test_fsearch_help_mentions_proceedings_scope(self):
        parser = cli._build_parser()
        fsearch_help = parser._subparsers._group_actions[0].choices["fsearch"].format_help()

        assert "proceedings" in fsearch_help

    def test_explore_help_mentions_multidimensional_exploration(self):
        parser = cli._build_parser()
        root_help = parser.format_help()

        assert "多维文献探索" in root_help
        assert "期刊全量探索" not in root_help

    def test_refetch_help_accepts_uuid_and_doi_identifiers(self):
        parser = cli._build_parser()
        refetch_help = parser._subparsers._group_actions[0].choices["refetch"].format_help()

        assert "目录名 / UUID / DOI" in refetch_help

    def test_backup_help_exposes_list_and_run_subcommands(self):
        parser = cli._build_parser()
        backup_parser = parser._subparsers._group_actions[0].choices["backup"]
        backup_help = backup_parser.format_help()
        run_help = backup_parser._subparsers._group_actions[0].choices["run"].format_help()

        assert "rsync 增量备份" in backup_help
        assert "列出已配置的备份目标" in backup_help
        assert "预演模式" in run_help


class TestWebsearchCli:
    def test_cmd_websearch_exits_on_service_unavailable(self, monkeypatch):
        import scholaraio.sources.webtools as webtools

        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        def fake_search_and_display(*args, **kwargs):
            raise webtools.ServiceUnavailableError("service down")

        monkeypatch.setattr(webtools, "search_and_display", fake_search_and_display)

        args = Namespace(query=["test"], count=3)

        with pytest.raises(SystemExit) as exc:
            cli.cmd_websearch(args, SimpleNamespace())

        assert exc.value.code == 1
        assert any("错误: service down" in message for message in messages)
        assert any("GUILessBingSearch" in message for message in messages)

    def test_cmd_websearch_does_not_repeat_success_summary(self, monkeypatch):
        import scholaraio.sources.webtools as webtools

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
        import scholaraio.sources.webtools as webtools

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
        assert any("提取失败: partial extraction failed" in message for message in messages)
        assert all("提取成功" not in message for message in messages)

    def test_cmd_webextract_truncates_long_text_by_default(self, monkeypatch, capsys):
        import scholaraio.sources.webtools as webtools

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

        assert any("提取成功: Page" in message for message in messages)
        assert any("已截断" in message for message in messages)
        assert "abcdefghij" in captured.out
        assert "klmnopqrstuvwxyz" not in captured.out

    def test_cmd_webextract_full_prints_complete_text(self, monkeypatch, capsys):
        import scholaraio.sources.webtools as webtools

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

        assert any("提取成功: Page" in message for message in messages)
        assert all("已截断" not in message for message in messages)
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

        assert "\n--- 全文（zh） ---\n" in messages

    def test_missing_translation_heading_uses_consistent_spacing(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_print_header", lambda _: None)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(paper_id="Smith-2023-Turbulence", layer=4, lang="fr")

        cli.cmd_show(args, cfg)

        assert "\n--- 全文（原文，paper_fr.md 不存在） ---\n" in messages


class TestRefetchIdentifierResolution:
    def test_refetch_resolves_uuid_via_registry(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)

        seen: list[Path] = []
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("scholaraio.ingest.metadata.refetch_metadata", lambda jp: seen.append(jp) or True)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(paper_id="aaaa-1111", all=False, force=False, jobs=5)

        cli.cmd_refetch(args, cfg)

        assert seen == [tmp_papers / "Smith-2023-Turbulence" / "meta.json"]
        assert any("并发 refetch（1 workers，共 1 篇）" in m for m in messages)
        assert any("Smith-2023-Turbulence" in m for m in messages)

    def test_refetch_resolves_mixed_case_doi_without_registry(self, tmp_papers, tmp_path, monkeypatch):
        seen: list[Path] = []
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("scholaraio.ingest.metadata.refetch_metadata", lambda jp: seen.append(jp) or True)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_path / "missing-index.db")
        args = Namespace(paper_id="10.1234/JFM.2023.001", all=False, force=False, jobs=5)

        cli.cmd_refetch(args, cfg)

        assert seen == [tmp_papers / "Smith-2023-Turbulence" / "meta.json"]
        assert any("并发 refetch（1 workers，共 1 篇）" in m for m in messages)
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
            "scholaraio.ingest.metadata.refetch_metadata",
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
        assert any("1 篇需要补全 references" in m for m in messages)
        assert any("并发 refetch（1 workers，共 1 篇）" in m for m in messages)


class TestRepairIdentifierResolution:
    def test_repair_help_accepts_uuid_and_doi_identifiers(self):
        parser = cli._build_parser()
        repair_help = parser._subparsers._group_actions[0].choices["repair"].format_help()

        assert "目录名 / UUID / DOI" in repair_help

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

        assert "论文ID   : aaaa-1111" in messages

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

        assert "论文ID   : aaaa-1111" in messages
        assert "论文ID   : bogus-9999" not in messages


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

        assert "\n--- Agent 笔记 (notes.md) ---\n" in messages
        assert any("Key finding" in m for m in messages)
        assert "\n--- 笔记结束 ---\n" in messages

    def test_no_notes_section_when_file_missing(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_print_header", lambda _: None)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(paper_id="Smith-2023-Turbulence", layer=1)

        cli.cmd_show(args, cfg)

        assert "\n--- Agent 笔记 (notes.md) ---\n" not in messages

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

        assert any("已追加笔记到" in m for m in messages)
        assert "\n--- Agent 笔记 (notes.md) ---\n" in messages
        assert any("Important note" in m for m in messages)

    def test_append_notes_empty_ignored(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_print_header", lambda _: None)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(paper_id="Smith-2023-Turbulence", layer=1, append_notes="   ")

        cli.cmd_show(args, cfg)

        assert any("内容为空" in m for m in messages)
        assert not (tmp_papers / "Smith-2023-Turbulence" / "notes.md").exists()


class TestSearchResultFormatting:
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
        monkeypatch.setattr("scholaraio.metrics.get_store", lambda: None)
        monkeypatch.setattr(cli, "_record_search_metrics", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            "scholaraio.index.unified_search",
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

        assert any("向量检索不可用，已降级为关键词检索" in m for m in messages)

    def test_cmd_fsearch_warns_when_main_scope_vector_search_degrades(self, monkeypatch, tmp_path):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
        monkeypatch.setattr(
            "scholaraio.index.unified_search",
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

        assert any("向量检索不可用，已降级为关键词检索" in m for m in messages)


class TestToolrefCliMessages:
    def test_toolref_show_output_is_localized(self, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(
            "scholaraio.toolref.toolref_show",
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
        assert any("段落：" in m and "程序：" in m for m in messages)
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

        monkeypatch.setattr("scholaraio.sources.arxiv.download_arxiv_pdf", fake_download)

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(arxiv_ref="2603.25200", ingest=False, force=False, dry_run=False)

        cli.cmd_arxiv_fetch(args, cfg)

        assert downloaded.exists()
        assert any("已下载到 inbox" in m for m in messages)

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

        monkeypatch.setattr("scholaraio.sources.arxiv.download_arxiv_pdf", fake_download)
        monkeypatch.setattr("scholaraio.ingest.pipeline.run_pipeline", fake_run_pipeline)

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(arxiv_ref="2603.25200", ingest=True, force=False, dry_run=False)

        cli.cmd_arxiv_fetch(args, cfg)

        assert seen["steps"] == ["mineru", "extract", "dedup", "ingest", "embed", "index"]
        assert seen["inbox_dir"] != cfg._root / "data" / "inbox"
        assert seen["opts"]["include_aux_inboxes"] is False
        assert any("开始直接入库" in m for m in messages)

    def test_arxiv_fetch_reports_download_failure(self, tmp_path, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(
            "scholaraio.sources.arxiv.download_arxiv_pdf",
            lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timeout")),
        )

        cfg = SimpleNamespace(_root=tmp_path, papers_dir=tmp_path / "data" / "papers")
        args = Namespace(arxiv_ref="2603.25200", ingest=False, force=False, dry_run=False)

        cli.cmd_arxiv_fetch(args, cfg)

        assert any("arXiv 下载失败" in m for m in messages)


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

        assert any("[已入库]" in m for m in messages)


class TestTranslateCliProgress:
    def test_cmd_translate_reports_portable_export_path(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_resolve_paper", lambda paper_id, cfg: tmp_papers / paper_id)
        monkeypatch.setattr(
            "scholaraio.translate.translate_paper",
            lambda *args, **kwargs: TranslateResult(
                path=(tmp_papers / "Smith-2023-Turbulence" / "paper_zh.md"),
                portable_path=(
                    tmp_papers.parent / "workspace" / "translation-ws" / "Smith-2023-Turbulence" / "paper_zh.md"
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

        assert any("翻译完成:" in m for m in messages)
        assert any("可移植导出:" in m and "translation-ws" in m for m in messages)

    def test_cmd_translate_reports_resumable_partial_progress(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr(cli, "_resolve_paper", lambda paper_id, cfg: tmp_papers / paper_id)
        monkeypatch.setattr(
            "scholaraio.translate.translate_paper",
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

        assert any("已完成 2/5 块" in m for m in messages)
        assert any("可稍后继续续翻" in m for m in messages)


class TestEnrichTocCliProgress:
    def test_cmd_enrich_toc_reports_single_paper_success(self, tmp_papers, monkeypatch):
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        def fake_enrich_toc(json_path, md_path, cfg, *, force=False, inspect=False):
            data = json.loads(json_path.read_text(encoding="utf-8"))
            data["toc"] = [{"line": 1, "level": 1, "title": "Introduction"}]
            json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return True

        monkeypatch.setattr("scholaraio.loader.enrich_toc", fake_enrich_toc)

        cfg = SimpleNamespace(papers_dir=tmp_papers)
        args = Namespace(all=False, paper_id="Smith-2023-Turbulence", force=True, inspect=False)

        cli.cmd_enrich_toc(args, cfg)

        assert any("开始提取 TOC" in m for m in messages)
        assert any("TOC 提取完成" in m and "1 节" in m for m in messages)

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

        monkeypatch.setattr("scholaraio.loader.enrich_toc", fake_enrich_toc)

        cfg = SimpleNamespace(papers_dir=tmp_papers, llm=SimpleNamespace(concurrency=7))
        args = Namespace(all=True, paper_id=None, force=True, inspect=False)

        cli.cmd_enrich_toc(args, cfg)

        assert max_workers_seen == [2]
        assert submitted == [
            "Smith-2023-Turbulence",
            "Wang-2024-DeepLearning",
        ]
        assert any("Smith-2023-Turbulence" in m and "开始处理" in m for m in messages)
        assert any("Wang-2024-DeepLearning" in m and "开始处理" in m for m in messages)
        assert any("Smith-2023-Turbulence" in m and "TOC 提取完成" in m for m in messages)
        assert any("Wang-2024-DeepLearning" in m and "TOC 提取完成" in m for m in messages)
        assert any("完成: 2 成功 | 0 失败 | 0 跳过" in m for m in messages)


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

        monkeypatch.setattr("scholaraio.loader.enrich_l3", fake_enrich_l3)

        cfg = SimpleNamespace(papers_dir=tmp_papers, llm=SimpleNamespace(concurrency=4))
        args = Namespace(all=True, paper_id=None, force=True, inspect=False, max_retries=2)

        cli.cmd_enrich_l3(args, cfg)

        assert attempts == {
            "Smith-2023-Turbulence": 3,
            "Wang-2024-DeepLearning": 1,
        }
        assert sleep_delays == [1.0, 2.0]
        assert any("Smith-2023-Turbulence" in m and "开始处理" in m for m in messages)
        assert any("Wang-2024-DeepLearning" in m and "开始处理" in m for m in messages)
        assert any("Smith-2023-Turbulence" in m and "重试后成功" in m for m in messages)
        assert any("Smith-2023-Turbulence" in m and "结论提取完成" in m for m in messages)
        assert any("Wang-2024-DeepLearning" in m and "结论提取完成" in m for m in messages)
        assert any("完成: 2 成功 | 0 失败 | 0 跳过" in m for m in messages)


class TestImportEndnoteOptionalDeps:
    def test_import_endnote_reports_missing_optional_dependency(self, tmp_path, monkeypatch):
        src = tmp_path / "library.xml"
        src.write_text("<xml />", encoding="utf-8")

        errors: list[str] = []

        monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
        monkeypatch.setattr(
            "scholaraio.sources.endnote._load_endnote_core",
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

        assert any("缺少依赖: endnote_utils" in msg for msg in errors)
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

        assert any("缺少依赖: docx" in msg for msg in errors)
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

        assert any("缺少依赖: fitz" in msg for msg in errors)
        assert any("pip install scholaraio[pdf]" in msg for msg in errors)


class TestTopicCliErrors:
    def test_cmd_topics_reports_embedding_disabled_cleanly(self, tmp_path, monkeypatch):
        errors: list[str] = []
        monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
        monkeypatch.setattr(
            "scholaraio.topics.build_topics",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                FileNotFoundError("当前 embed.provider=none，无法构建主题模型")
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
        monkeypatch.setattr("scholaraio.explore._explore_dir", lambda *_args, **_kwargs: tmp_path / "explore")
        monkeypatch.setattr(
            "scholaraio.explore.build_explore_topics",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                FileNotFoundError("当前 embed.provider=none，无法构建主题模型")
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
            "scholaraio.explore.explore_vsearch",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                FileNotFoundError("当前 embed.provider=none，已禁用语义向量检索")
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

        import scholaraio.ingest.mineru as mineru
        import scholaraio.ingest.pdf_fallback as pdf_fallback

        _allow_pdf_validation(monkeypatch)
        monkeypatch.setattr(mineru, "check_server", lambda *_: False)

        calls: list[tuple[Path, Path]] = []

        def _fallback(pdf_path, md_path, parser_order=None, auto_detect=True):
            calls.append((pdf_path, md_path))
            md_path.write_text("fallback attach ok\n", encoding="utf-8")
            return True, "docling", None

        monkeypatch.setattr(pdf_fallback, "convert_pdf_with_fallback", _fallback)
        monkeypatch.setattr("scholaraio.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_index", lambda *_: None)

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

        import scholaraio.ingest.mineru as mineru
        import scholaraio.ingest.pdf_fallback as pdf_fallback

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
        monkeypatch.setattr("scholaraio.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_index", lambda *_: None)

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

        import scholaraio.ingest.mineru as mineru

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
        monkeypatch.setattr("scholaraio.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_index", lambda *_: None)
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

        import scholaraio.ingest.mineru as mineru

        _allow_pdf_validation(monkeypatch)
        monkeypatch.setattr(mineru, "check_server", lambda *_: False)
        monkeypatch.setattr(mineru, "_plan_cloud_chunking", lambda *_args, **_kwargs: (False, 600, ""))
        captured: dict[str, object] = {}

        def fake_convert_pdf_cloud(_pdf_path, opts, **_kwargs):
            captured["poll_timeout"] = opts.poll_timeout
            return ConvertResult(pdf_path=src_pdf, md_path=paper_dir / "input.md", success=True)

        monkeypatch.setattr(mineru, "convert_pdf_cloud", fake_convert_pdf_cloud)
        monkeypatch.setattr("scholaraio.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_index", lambda *_: None)
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

        import scholaraio.ingest.mineru as mineru

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
        monkeypatch.setattr("scholaraio.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_index", lambda *_: None)

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

        import scholaraio.ingest.mineru as mineru

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
        monkeypatch.setattr("scholaraio.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_index", lambda *_: None)

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

        import scholaraio.ingest.mineru as mineru

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
        monkeypatch.setattr("scholaraio.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_index", lambda *_: None)

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

        import scholaraio.ingest.mineru as mineru
        import scholaraio.ingest.pdf_fallback as pdf_fallback

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
        monkeypatch.setattr("scholaraio.papers.read_meta", lambda *_: {"abstract": "exists"})
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_embed", lambda *_: None)
        monkeypatch.setattr("scholaraio.ingest.pipeline.step_index", lambda *_: None)

        args = Namespace(paper_id="paper-1", pdf_path=str(src_pdf), dry_run=False)
        cli.cmd_attach_pdf(args, cfg)

        assert (paper_dir / "paper.md").read_text(encoding="utf-8") == "fallback attach ok\n"
        assert any("scholaraio[pdf]" in msg for msg in messages)


class TestSetupMetricsFallback:
    def test_setup_check_skips_metrics_init_failure(self, monkeypatch):
        messages: list[str] = []

        monkeypatch.setattr(
            cli,
            "load_config",
            lambda: SimpleNamespace(
                ensure_dirs=lambda: None,
                metrics_db_path="/tmp/metrics.db",
                ingest=SimpleNamespace(contact_email=""),
                resolved_s2_api_key=lambda: "",
            ),
        )
        monkeypatch.setattr(cli, "ui", messages.append)
        monkeypatch.setattr("scholaraio.log.setup", lambda cfg: "session-1")

        def _boom(*_args, **_kwargs):
            raise RuntimeError("database is locked")

        monkeypatch.setattr("scholaraio.metrics.init", _boom)
        monkeypatch.setattr("scholaraio.ingest.metadata._models.configure_session", lambda *_: None)
        monkeypatch.setattr("scholaraio.ingest.metadata._models.configure_s2_session", lambda *_: None)
        monkeypatch.setattr(cli, "cmd_setup", lambda args, cfg: print("SETUP_OK"))
        monkeypatch.setattr("sys.argv", ["scholaraio", "setup", "check", "--lang", "zh"])

        cli.main()

        assert any("metrics 初始化失败，已跳过" in msg for msg in messages)
