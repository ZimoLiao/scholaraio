"""Tests for setup.py dependency probing, parser recommendation, and checks."""

from __future__ import annotations

import importlib
import os

from scholaraio.core.config import Config
from scholaraio.services.setup import (
    ParserChoice,
    _check_docling,
    _check_huggingface,
    _check_mineru,
    _prompt_text,
    _wizard_deps,
    _wizard_keys,
    _wizard_parser,
    check_dep_group,
    recommend_pdf_parser,
    run_check,
    run_wizard,
)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def test_check_dep_group_treats_runtime_import_failure_as_missing(monkeypatch):
    original = importlib.import_module

    def fake_import(name: str, package=None):
        if name == "bertopic":
            raise RuntimeError("numba cache failure")
        if package is None:
            return original(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    status = check_dep_group("topics")

    assert not status.installed
    assert "bertopic" in status.missing


def test_check_dep_group_suppresses_import_side_effect_output(monkeypatch, capsys):
    original = importlib.import_module

    def fake_import(name: str, package=None):
        if name == "mermaid":
            print("noisy stdout during import")
            raise RuntimeError("optional backend warning")
        if package is None:
            return original(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    status = check_dep_group("draw")

    captured = capsys.readouterr()
    assert not status.installed
    assert captured.out == ""
    assert captured.err == ""


def test_check_dep_group_sets_numba_cache_before_bertopic_import(monkeypatch):
    original = importlib.import_module
    monkeypatch.delenv("NUMBA_CACHE_DIR", raising=False)

    def fake_import(name: str, package=None):
        if name == "bertopic":
            assert os.environ.get("NUMBA_CACHE_DIR")
            return object()
        if package is None:
            return original(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    status = check_dep_group("topics")

    assert status.installed


def test_check_docling_uses_cli_presence(monkeypatch):
    monkeypatch.setattr(
        "scholaraio.services.setup.shutil.which", lambda name: "/usr/bin/docling" if name == "docling" else None
    )

    ok, detail = _check_docling("zh")

    assert ok is True
    assert detail == "/usr/bin/docling"


def test_check_docling_reports_actionable_install_guidance(monkeypatch):
    monkeypatch.setattr("scholaraio.services.setup.shutil.which", lambda name: None)

    ok, detail = _check_docling("zh")

    assert ok is False
    assert "pip install docling" in detail
    assert "安装文档" in detail


def test_check_huggingface_uses_reachability_probe(monkeypatch):
    monkeypatch.setattr("scholaraio.services.setup._probe_url", lambda url, timeout=2: url == "https://huggingface.co")

    ok, detail = _check_huggingface("zh")

    assert ok is True
    assert detail == "可达"


def test_check_huggingface_reports_actionable_failure(monkeypatch):
    monkeypatch.setattr("scholaraio.services.setup._probe_url", lambda url, timeout=2: False)

    ok, detail = _check_huggingface("zh")

    assert ok is False
    assert "Docling" in detail
    assert "MinerU" in detail


def test_recommend_pdf_parser_prefers_mineru_when_both_reachable():
    parser_name, reason = recommend_pdf_parser(True, True, "zh")

    assert parser_name == "MinerU"
    assert "MinerU 可用" in reason
    assert "Hugging Face 也可达" in reason


def test_recommend_pdf_parser_prefers_docling_when_only_huggingface_reachable():
    parser_name, reason = recommend_pdf_parser(False, True, "zh")

    assert parser_name == "Docling"
    assert "Hugging Face 可达而 MinerU 不可用" in reason


def test_run_check_includes_parser_recommendation(monkeypatch):
    cfg = Config()
    monkeypatch.setattr("scholaraio.services.setup._check_mineru", lambda *_: (True, "mineru ok"))
    monkeypatch.setattr("scholaraio.services.setup._check_docling", lambda *_: (True, "docling ok"))
    monkeypatch.setattr("scholaraio.services.setup._check_huggingface", lambda *_: (True, "hf ok"))
    monkeypatch.setattr("scholaraio.services.setup.recommend_pdf_parser", lambda *args: ("MinerU", "both reachable"))

    results = run_check(cfg, "zh")

    labels = [item.label for item in results]
    assert "Docling" in labels
    assert "Hugging Face" in labels
    assert "PDF 解析器推荐" in labels


def test_run_check_includes_pdf_office_and_draw_dependency_groups(monkeypatch):
    cfg = Config()
    monkeypatch.setattr("scholaraio.services.setup._check_mineru", lambda *_: (True, "mineru ok"))
    monkeypatch.setattr("scholaraio.services.setup._check_docling", lambda *_: (True, "docling ok"))
    monkeypatch.setattr("scholaraio.services.setup._check_huggingface", lambda *_: (True, "hf ok"))
    monkeypatch.setattr("scholaraio.services.setup.recommend_pdf_parser", lambda *args: ("MinerU", "both reachable"))

    results = run_check(cfg, "zh")

    labels = [item.label for item in results]
    assert "PDF 依赖" in labels
    assert "Office 依赖" in labels
    assert "绘图依赖" in labels


def test_run_check_includes_optional_api_configuration_statuses(monkeypatch):
    cfg = Config()
    monkeypatch.setattr("scholaraio.services.setup._check_mineru", lambda *_: (True, "mineru ok"))
    monkeypatch.setattr("scholaraio.services.setup._check_docling", lambda *_: (True, "docling ok"))
    monkeypatch.setattr("scholaraio.services.setup._check_huggingface", lambda *_: (True, "hf ok"))
    monkeypatch.setattr("scholaraio.services.setup.recommend_pdf_parser", lambda *args: ("MinerU", "both reachable"))
    monkeypatch.setattr(cfg, "resolved_s2_api_key", lambda: "")
    monkeypatch.setattr(cfg, "resolved_zotero_api_key", lambda: "")

    results = run_check(cfg, "zh")

    result_map = {item.label: item for item in results}
    assert "Semantic Scholar API key" in result_map
    assert "Zotero API key" in result_map
    assert "Paper2Any" in result_map
    assert result_map["Semantic Scholar API key"].ok is True
    assert result_map["Zotero API key"].ok is True
    assert result_map["Paper2Any"].ok is True
    assert "可选" in result_map["Semantic Scholar API key"].detail
    assert "可选" in result_map["Zotero API key"].detail
    assert "OpenDCAI/Paper2Any" in result_map["Paper2Any"].detail


def test_run_check_prefers_mineru_recommendation_when_cli_exists_without_token(monkeypatch):
    cfg = Config()
    monkeypatch.setattr(
        "scholaraio.services.setup._detect_mineru",
        lambda *_args, **_kwargs: type(
            "MinerUStatus",
            (),
            {
                "ok": False,
                "detail": "cli present, token missing",
                "recommendable": True,
                "cloud_only": True,
                "cli_available": True,
                "token_configured": False,
            },
        )(),
    )
    monkeypatch.setattr("scholaraio.services.setup._check_docling", lambda *_: (True, "docling ok"))
    monkeypatch.setattr("scholaraio.services.setup._check_huggingface", lambda *_: (False, "hf down"))

    results = run_check(cfg, "zh")

    result_map = {item.label: item for item in results}
    assert result_map["PDF 解析器推荐"].detail.startswith("MinerU:")


def test_run_check_uses_accessor_dirs_for_directory_status(tmp_path, monkeypatch):
    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "library/papers"
    cfg.paths.workspace_dir = "projects"
    cfg.paths.inbox_dir = "queues/inbox"
    cfg.paths.pending_dir = "queues/pending-review"

    cfg.papers_dir.mkdir(parents=True)
    cfg.workspace_dir.mkdir(parents=True)
    cfg.inbox_dir.mkdir(parents=True)
    cfg.pending_dir.mkdir(parents=True)

    monkeypatch.setattr("scholaraio.services.setup._check_mineru", lambda *_: (True, "mineru ok"))
    monkeypatch.setattr("scholaraio.services.setup._check_docling", lambda *_: (True, "docling ok"))
    monkeypatch.setattr("scholaraio.services.setup._check_huggingface", lambda *_: (True, "hf ok"))
    monkeypatch.setattr("scholaraio.services.setup.recommend_pdf_parser", lambda *args: ("MinerU", "both reachable"))

    results = run_check(cfg, "zh")

    result_map = {item.label: item for item in results}
    assert result_map["目录结构"].ok is True


def test_check_dep_group_supports_draw_extra(monkeypatch):
    original = importlib.import_module

    def fake_import(name: str, package=None):
        if name == "cli_anything":
            raise RuntimeError("bad optional import")
        if package is None:
            return original(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    status = check_dep_group("draw")

    assert not status.installed
    assert "cli-anything-inkscape" in status.missing


def test_check_dep_group_treats_oserror_import_failure_as_missing(monkeypatch):
    original = importlib.import_module

    def fake_import(name: str, package=None):
        if name == "bertopic":
            raise OSError("libstdc++.so missing")
        if package is None:
            return original(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    status = check_dep_group("topics")

    assert not status.installed
    assert "bertopic" in status.missing


def test_check_dep_group_uses_spec_probe_for_embed_deps(monkeypatch):
    original = importlib.util.find_spec

    def fake_find_spec(name: str, package=None):
        if name == "faiss":
            return None
        return original(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    status = check_dep_group("embed")

    assert not status.installed
    assert "faiss-cpu" in status.missing


def test_check_mineru_reports_actionable_failure(monkeypatch):
    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")
    monkeypatch.setattr("scholaraio.services.setup.shutil.which", lambda _name: None)

    class DummyRequests:
        @staticmethod
        def get(*_args, **_kwargs):
            raise RuntimeError("offline")

    monkeypatch.setitem(__import__("sys").modules, "requests", DummyRequests)

    from scholaraio.services.setup import _check_mineru

    ok, detail = _check_mineru(cfg, "zh")

    assert ok is False
    assert "mineru-open-api" in detail
    assert "token" in detail
    assert "Docker" in detail


def test_check_mineru_prefers_local_server_even_when_token_cli_missing(monkeypatch):
    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "token")
    monkeypatch.setattr("scholaraio.services.setup.shutil.which", lambda _name: None)

    class DummyRequests:
        @staticmethod
        def get(*_args, **_kwargs):
            class _Resp:
                status_code = 200

            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "requests", DummyRequests)

    ok, detail = _check_mineru(cfg, "en")

    assert ok is True
    assert "local server" in detail


def test_wizard_parser_mineru_choice_skips_auto_probe(monkeypatch, capsys):
    cfg = Config()
    answers = iter(["1", "y"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        "scholaraio.services.setup._probe_url", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError())
    )

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is False
    out = capsys.readouterr().out
    assert "已选择 MinerU" in out


def test_wizard_parser_auto_choice_shows_advisory_not_override(monkeypatch, capsys):
    cfg = Config()
    answers = iter(["3", "n"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        "scholaraio.services.setup.shutil.which",
        lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None,
    )
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")
    monkeypatch.setattr("scholaraio.services.setup._probe_url", lambda url, timeout=2: "mineru.net" in url)

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is True
    out = capsys.readouterr().out
    assert "检测到现有 MinerU token" not in out
    assert "尚未配置 MinerU API Token" in out
    assert "建议优先使用 MinerU" in out
    assert out.index("建议优先使用 MinerU") < out.index("如果你不打算本地部署")
    assert out.index("如果你不打算本地部署") < out.index("MinerU 本地部署指引")
    assert "如果你已经确定要用另一个" in out


def test_wizard_parser_auto_prefers_configured_mineru_before_probe(monkeypatch, capsys):
    cfg = Config()
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "mineru-key")
    answers = iter(["3", "n"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        "scholaraio.services.setup.shutil.which",
        lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None,
    )
    monkeypatch.setattr("scholaraio.services.setup._probe_url", lambda *_args, **_kwargs: False)

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is True
    out = capsys.readouterr().out
    assert "建议优先使用 MinerU" in out
    assert out.index("建议优先使用 MinerU") < out.index("如果你不打算本地部署")


def test_wizard_parser_auto_detects_local_mineru_server(monkeypatch, capsys):
    cfg = Config()
    answers = iter(["3", "y"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr("scholaraio.services.setup.shutil.which", lambda _name: None)
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")
    monkeypatch.setattr("scholaraio.services.setup._probe_url", lambda *_args, **_kwargs: False)

    class DummyRequests:
        @staticmethod
        def get(url, timeout=2):
            class _Resp:
                status_code = 200

            assert url == cfg.ingest.mineru_endpoint
            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "requests", DummyRequests)

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is False
    out = capsys.readouterr().out
    assert "建议优先使用 MinerU" in out


def test_prompt_text_returns_empty_string_on_eof(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError()))

    value = _prompt_text("  > ")

    assert value == ""


def test_wizard_deps_does_not_auto_install_when_input_stream_hits_eof(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError()))
    monkeypatch.setattr(
        "scholaraio.services.setup.check_dep_group",
        lambda group: type("Status", (), {"installed": group != "topics", "missing": ["bertopic"]})(),
    )

    called = []

    def fake_run(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("pip install should not run on EOF")

    monkeypatch.setattr("scholaraio.services.setup.subprocess.run", fake_run)

    _wizard_deps("zh")

    out = capsys.readouterr().out
    assert called == []
    assert "已跳过" in out


def test_wizard_defaults_to_english_when_language_input_hits_eof(monkeypatch, capsys):
    cfg = Config()
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError()))
    monkeypatch.setattr("scholaraio.services.setup._wizard_deps", lambda lang: print(f"deps:{lang}"))
    monkeypatch.setattr("scholaraio.services.setup._wizard_config", lambda root, lang: print(f"config:{lang}"))
    monkeypatch.setattr(
        "scholaraio.services.setup._wizard_parser",
        lambda cfg, lang: ParserChoice(parser="docling", needs_mineru_key=False),
    )
    monkeypatch.setattr(
        "scholaraio.services.setup._wizard_keys", lambda root, lang, parser_choice: print(f"keys:{lang}")
    )
    monkeypatch.setattr("scholaraio.services.setup.run_check", lambda cfg=None, lang="en": [])
    monkeypatch.setattr("scholaraio.services.setup.format_check_results", lambda results: "")

    run_wizard(cfg)

    out = capsys.readouterr().out
    assert "Language:" in out
    assert "ScholarAIO Setup Wizard" in out
    assert "deps:en" in out
    assert not _has_cjk(out)


def test_wizard_parser_auto_prefers_mineru_when_cli_exists_even_without_token_probe(monkeypatch, capsys):
    cfg = Config()
    answers = iter(["3", "n"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        "scholaraio.services.setup.shutil.which",
        lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None,
    )
    monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")
    monkeypatch.setattr("scholaraio.services.setup._probe_url", lambda *_args, **_kwargs: False)

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is True
    out = capsys.readouterr().out
    assert "建议优先使用 MinerU" in out
    assert "免费" in out
    assert "Token" in out or "token" in out


def test_wizard_parser_auto_choice_defaults_to_cloud_key_on_eof(monkeypatch):
    cfg = Config()
    answers = iter(["3", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(
        "scholaraio.services.setup.shutil.which",
        lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None,
    )
    monkeypatch.setattr("scholaraio.services.setup._probe_url", lambda url, timeout=2: "mineru.net" in url)

    choice = _wizard_parser(cfg, "zh")

    assert choice.parser == "mineru"
    assert choice.needs_mineru_key is True


def test_wizard_keys_persists_docling_parser_preference(tmp_path, monkeypatch):
    answers = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="docling", needs_mineru_key=False))

    local_cfg = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "pdf_preferred_parser: docling" in local_cfg


def test_wizard_keys_handles_null_ingest_section(tmp_path, monkeypatch):
    (tmp_path / "config.local.yaml").write_text("ingest: null\n", encoding="utf-8")
    answers = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="docling", needs_mineru_key=False))

    local_cfg = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "pdf_preferred_parser: docling" in local_cfg


def test_wizard_keys_handles_non_mapping_local_config(tmp_path, monkeypatch):
    (tmp_path / "config.local.yaml").write_text("- unexpected\n", encoding="utf-8")
    answers = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="docling", needs_mineru_key=False))

    local_cfg = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "pdf_preferred_parser: docling" in local_cfg


def test_wizard_keys_handles_null_llm_section(tmp_path, monkeypatch):
    (tmp_path / "config.local.yaml").write_text("llm: null\n", encoding="utf-8")
    answers = iter(["test-key", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="docling", needs_mineru_key=False))

    local_cfg = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "api_key: test-key" in local_cfg


def test_wizard_keys_skips_creating_local_config_when_default_parser_and_no_new_values(tmp_path, monkeypatch, capsys):
    answers = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="mineru", needs_mineru_key=True))

    out = capsys.readouterr().out
    assert not (tmp_path / "config.local.yaml").exists()
    assert "未配置任何密钥" in out


def test_wizard_keys_cleans_redundant_default_parser_override(tmp_path, monkeypatch, capsys):
    (tmp_path / "config.local.yaml").write_text(
        "llm:\n  api_key: existing-llm-key\ningest:\n  mineru_api_key: existing-mineru-key\n  pdf_preferred_parser: mineru\n",
        encoding="utf-8",
    )
    answers = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    _wizard_keys(tmp_path, "zh", ParserChoice(parser="mineru", needs_mineru_key=True))

    out = capsys.readouterr().out
    assert "已保存到 config.local.yaml" in out
    local_cfg = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "pdf_preferred_parser" not in local_cfg
    assert "existing-mineru-key" in local_cfg
