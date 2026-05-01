"""Tests for scholaraio.core.config — YAML loading, merging, path resolution, defaults."""

from __future__ import annotations

import logging
from pathlib import Path

from scholaraio.core.config import _build_config, _deep_merge, load_config


class TestDeepMerge:
    def test_scalar_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        assert _deep_merge(base, override) == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"llm": {"model": "gpt-4", "timeout": 30}}
        override = {"llm": {"timeout": 60}}
        result = _deep_merge(base, override)
        assert result == {"llm": {"model": "gpt-4", "timeout": 60}}

    def test_add_new_keys(self):
        base = {"a": 1}
        override = {"b": 2}
        assert _deep_merge(base, override) == {"a": 1, "b": 2}

    def test_empty_override(self):
        base = {"a": 1}
        assert _deep_merge(base, {}) == {"a": 1}

    def test_empty_base(self):
        override = {"a": 1}
        assert _deep_merge({}, override) == {"a": 1}

    def test_override_dict_with_scalar(self):
        base = {"a": {"nested": True}}
        override = {"a": "flat"}
        assert _deep_merge(base, override) == {"a": "flat"}

    def test_deep_nesting(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"c": 99}}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": {"c": 99, "d": 2}}}


class TestBuildConfig:
    def test_empty_dict_uses_defaults(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.llm.model == "deepseek-chat"
        assert cfg.llm.backend == "openai-compat"
        assert cfg.paths.papers_dir == "data/libraries/papers"
        assert cfg.search.top_k == 20
        assert cfg.websearch.base_url == ""
        assert cfg.webextract.base_url == ""
        assert cfg.paper2any.root == ""
        assert cfg.paper2any.mcp_url == ""

    def test_partial_override(self, tmp_path):
        data = {"llm": {"model": "gpt-4o", "timeout": 60}}
        cfg = _build_config(data, tmp_path)
        assert cfg.llm.model == "gpt-4o"
        assert cfg.llm.timeout == 60
        assert cfg.llm.backend == "openai-compat"  # default preserved

    def test_concurrency_min_1(self, tmp_path):
        data = {"llm": {"concurrency": 0}}
        cfg = _build_config(data, tmp_path)
        assert cfg.llm.concurrency == 1

    def test_concurrency_negative(self, tmp_path):
        data = {"llm": {"concurrency": -5}}
        cfg = _build_config(data, tmp_path)
        assert cfg.llm.concurrency == 1

    def test_api_key_none_becomes_empty(self, tmp_path):
        data = {"llm": {"api_key": None}}
        cfg = _build_config(data, tmp_path)
        assert cfg.llm.api_key == ""

    def test_ingest_defaults(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.ingest.extractor == "robust"
        assert cfg.ingest.chunk_page_limit == 100
        assert cfg.ingest.mineru_batch_size == 20
        assert cfg.ingest.mineru_upload_workers == 4
        assert cfg.ingest.mineru_upload_retries == 3
        assert cfg.ingest.mineru_download_retries == 3
        assert cfg.ingest.mineru_poll_timeout == 900
        assert cfg.ingest.pdf_preferred_parser == "mineru"
        assert cfg.ingest.pdf_fallback_order == ["auto"]
        assert cfg.ingest.pdf_fallback_auto_detect is True

    def test_ingest_fallback_order_override(self, tmp_path):
        cfg = _build_config(
            {
                "ingest": {
                    "pdf_preferred_parser": "docling",
                    "pdf_fallback_order": ["pymupdf"],
                    "pdf_fallback_auto_detect": False,
                }
            },
            tmp_path,
        )
        assert cfg.ingest.pdf_preferred_parser == "docling"
        assert cfg.ingest.pdf_fallback_order == ["pymupdf"]
        assert cfg.ingest.pdf_fallback_auto_detect is False

    def test_ingest_fallback_order_accepts_single_string(self, tmp_path):
        cfg = _build_config({"ingest": {"pdf_fallback_order": "auto"}}, tmp_path)
        assert cfg.ingest.pdf_fallback_order == ["auto"]

    def test_ingest_choice_fields_are_case_insensitive(self, tmp_path):
        cfg = _build_config(
            {
                "ingest": {
                    "mineru_backend_local": "Pipeline",
                    "mineru_parse_method": "OCR",
                    "pdf_preferred_parser": "Docling",
                }
            },
            tmp_path,
        )
        assert cfg.ingest.mineru_backend_local == "pipeline"
        assert cfg.ingest.mineru_parse_method == "ocr"
        assert cfg.ingest.pdf_preferred_parser == "docling"

    def test_ingest_fallback_order_ignores_null_and_non_string_entries(self, tmp_path):
        cfg = _build_config({"ingest": {"pdf_fallback_order": ["auto", None, 123, "docling"]}}, tmp_path)
        assert cfg.ingest.pdf_fallback_order == ["auto", "docling"]

    def test_ingest_fallback_order_invalid_scalar_type_warns_and_uses_default(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            cfg = _build_config({"ingest": {"pdf_fallback_order": 123}}, tmp_path)

        assert cfg.ingest.pdf_fallback_order == ["auto"]
        assert "invalid string-list config value" in caplog.text

    def test_ingest_fallback_auto_detect_parses_string_bool(self, tmp_path):
        cfg = _build_config({"ingest": {"pdf_fallback_auto_detect": "false"}}, tmp_path)
        assert cfg.ingest.pdf_fallback_auto_detect is False

    def test_ingest_fallback_auto_detect_none_uses_default(self, tmp_path):
        cfg = _build_config({"ingest": {"pdf_fallback_auto_detect": None}}, tmp_path)
        assert cfg.ingest.pdf_fallback_auto_detect is True

    def test_null_sections_handled(self, tmp_path):
        data = {"llm": None, "paths": None}
        cfg = _build_config(data, tmp_path)
        assert cfg.llm.model == "deepseek-chat"
        assert cfg.paths.papers_dir == "data/libraries/papers"

    def test_zotero_library_id_coerced_to_str(self, tmp_path):
        data = {"zotero": {"library_id": 12345}}
        cfg = _build_config(data, tmp_path)
        assert cfg.zotero.library_id == "12345"

    def test_translate_defaults_are_exposed(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.translate.auto_translate is False
        assert cfg.translate.target_lang == "zh"
        assert cfg.translate.chunk_size == 4000
        assert cfg.translate.concurrency == 20

    def test_web_service_sections_are_loaded(self, tmp_path):
        cfg = _build_config(
            {
                "websearch": {
                    "base_url": "http://localhost:8765",
                    "api_key": "search-key",
                    "transport": "mcp",
                    "mcp_url": "http://localhost:8765/mcp",
                    "mcp_tool": "search_bing",
                },
                "webextract": {
                    "base_url": "http://localhost:8766",
                    "api_key": "extract-key",
                    "transport": "mcp",
                    "mcp_url": "http://localhost:8766/mcp",
                    "mcp_tool": "fetch_url",
                },
            },
            tmp_path,
        )

        assert cfg.websearch.base_url == "http://localhost:8765"
        assert cfg.websearch.api_key == "search-key"
        assert cfg.websearch.transport == "mcp"
        assert cfg.websearch.mcp_url == "http://localhost:8765/mcp"
        assert cfg.websearch.mcp_tool == "search_bing"
        assert cfg.webextract.base_url == "http://localhost:8766"
        assert cfg.webextract.api_key == "extract-key"
        assert cfg.webextract.transport == "mcp"
        assert cfg.webextract.mcp_url == "http://localhost:8766/mcp"
        assert cfg.webextract.mcp_tool == "fetch_url"

    def test_paper2any_section_is_loaded_without_dependency_surface(self, tmp_path):
        cfg = _build_config(
            {
                "paper2any": {
                    "root": "data/runtime/extensions/paper2any/Paper2Any",
                    "transport": "mcp",
                    "mcp_url": "http://127.0.0.1:8770/mcp",
                    "base_url": "http://127.0.0.1:8000",
                    "api_key": "sidecar-secret",
                    "backend_api_key": "backend-secret",
                }
            },
            tmp_path,
        )

        assert cfg.paper2any.root == "data/runtime/extensions/paper2any/Paper2Any"
        assert cfg.paper2any.transport == "mcp"
        assert cfg.paper2any.mcp_url == "http://127.0.0.1:8770/mcp"
        assert cfg.paper2any.base_url == "http://127.0.0.1:8000"
        assert cfg.paper2any.api_key == "sidecar-secret"
        assert cfg.paper2any.backend_api_key == "backend-secret"
        assert not hasattr(cfg.paper2any, "requirements")
        assert not hasattr(cfg.paper2any, "install_command")

    def test_backup_defaults_are_exposed(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.backup.source_dir == "data"
        assert cfg.backup.rsync_bin == "rsync"
        assert cfg.backup.ssh_bin == "ssh"
        assert cfg.backup.targets == {}

    def test_backup_target_mode_defaults_to_safe_full_sync(self, tmp_path):
        cfg = _build_config(
            {
                "backup": {
                    "targets": {
                        "lab": {
                            "host": "backup.example.com",
                            "path": "/srv/scholaraio",
                        }
                    }
                }
            },
            tmp_path,
        )

        assert cfg.backup.targets["lab"].mode == "default"

    def test_backup_targets_are_parsed_and_normalized(self, tmp_path):
        cfg = _build_config(
            {
                "backup": {
                    "source_dir": "library-data",
                    "targets": {
                        "lab": {
                            "host": "backup.example.com",
                            "user": "alice",
                            "path": "/srv/scholaraio",
                            "port": 2222,
                            "identity_file": "keys/id_ed25519",
                            "password": "secret",
                            "mode": "Append-Verify",
                            "compress": "false",
                            "enabled": "true",
                            "exclude": ["*.tmp", None, 123, "metrics.db"],
                        }
                    },
                }
            },
            tmp_path,
        )

        assert cfg.backup.source_dir == "library-data"
        assert "lab" in cfg.backup.targets
        target = cfg.backup.targets["lab"]
        assert target.host == "backup.example.com"
        assert target.user == "alice"
        assert target.path == "/srv/scholaraio"
        assert target.port == 2222
        assert target.identity_file == "keys/id_ed25519"
        assert target.password == "secret"
        assert target.mode == "append-verify"
        assert target.compress is False
        assert target.enabled is True
        assert target.exclude == ["*.tmp", "metrics.db"]

    def test_backup_source_dir_expands_user_home(self, tmp_path):
        cfg = _build_config({"backup": {"source_dir": "~/scholaraio-backup-source"}}, tmp_path)
        assert cfg.backup_source_dir == Path("~/scholaraio-backup-source").expanduser().resolve()

    def test_zotero_library_type_default_and_override(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.zotero.library_type == "user"

        cfg2 = _build_config({"zotero": {"library_type": "group"}}, tmp_path)
        assert cfg2.zotero.library_type == "group"

    def test_mineru_formula_and_table_null_use_defaults(self, tmp_path):
        data = {
            "ingest": {
                "mineru_enable_formula": None,
                "mineru_enable_table": None,
            }
        }
        cfg = _build_config(data, tmp_path)
        assert cfg.ingest.mineru_enable_formula is True
        assert cfg.ingest.mineru_enable_table is True

    def test_invalid_mineru_pdf_cloud_settings_fall_back_to_safe_defaults(self, tmp_path):
        data = {
            "ingest": {
                "mineru_backend_local": "unknown-backend",
                "mineru_model_version_cloud": "MinerU-HTML",
                "mineru_lang": "",
                "mineru_parse_method": "bad-mode",
                "mineru_batch_size": 999,
                "pdf_preferred_parser": "bad-parser",
            }
        }
        cfg = _build_config(data, tmp_path)
        assert cfg.ingest.mineru_backend_local == "pipeline"
        assert cfg.ingest.mineru_model_version_cloud == "pipeline"
        assert cfg.ingest.mineru_lang == "ch"
        assert cfg.ingest.mineru_parse_method == "auto"
        assert cfg.ingest.mineru_batch_size == 200
        assert cfg.ingest.pdf_preferred_parser == "mineru"

    def test_mineru_lang_is_normalized_to_lowercase(self, tmp_path):
        cfg = _build_config({"ingest": {"mineru_lang": " EN "}}, tmp_path)
        assert cfg.ingest.mineru_lang == "en"

    def test_mineru_cloud_model_version_is_case_insensitive(self, tmp_path):
        cfg = _build_config({"ingest": {"mineru_model_version_cloud": " VLM "}}, tmp_path)
        assert cfg.ingest.mineru_model_version_cloud == "vlm"

    def test_zero_or_negative_mineru_batch_size_uses_default(self, tmp_path):
        cfg = _build_config({"ingest": {"mineru_batch_size": 0}}, tmp_path)
        assert cfg.ingest.mineru_batch_size == 20

    def test_embed_env_vars_override_yaml(self, tmp_path, monkeypatch):
        data = {
            "embed": {
                "provider": "local",
                "source": "modelscope",
                "cache_dir": "/yaml-cache",
                "model": "yaml-model",
                "api_base": "https://yaml-embed.example/v1",
            }
        }
        monkeypatch.setenv("SCHOLARAIO_EMBED_PROVIDER", "openai-compat")
        monkeypatch.setenv("SCHOLARAIO_EMBED_SOURCE", "huggingface")
        monkeypatch.setenv("SCHOLARAIO_EMBED_CACHE_DIR", "/env-cache")
        monkeypatch.setenv("SCHOLARAIO_EMBED_MODEL", "env-model")
        monkeypatch.setenv("SCHOLARAIO_EMBED_API_BASE", "https://env-embed.example/v1")
        cfg = _build_config(data, tmp_path)
        assert cfg.embed.provider == "openai-compat"
        assert cfg.embed.source == "huggingface"
        assert cfg.embed.cache_dir == "/env-cache"
        assert cfg.embed.model == "env-model"
        assert cfg.embed.api_base == "https://env-embed.example/v1"

    def test_scholaraio_hf_endpoint_wins_over_hf_endpoint(self, tmp_path, monkeypatch):
        data = {"embed": {"hf_endpoint": "https://yaml-mirror.example"}}
        monkeypatch.setenv("SCHOLARAIO_HF_ENDPOINT", "https://scholaraio-mirror.example")
        monkeypatch.setenv("HF_ENDPOINT", "https://generic-mirror.example")
        cfg = _build_config(data, tmp_path)
        assert cfg.embed.hf_endpoint == "https://scholaraio-mirror.example"

    def test_empty_embed_env_vars_do_not_override_yaml(self, tmp_path, monkeypatch):
        data = {
            "embed": {
                "provider": "local",
                "source": "huggingface",
                "cache_dir": "/yaml-cache",
                "model": "yaml-model",
                "hf_endpoint": "https://yaml-mirror.example",
                "api_base": "https://yaml-embed.example/v1",
            }
        }
        monkeypatch.setenv("SCHOLARAIO_EMBED_PROVIDER", "")
        monkeypatch.setenv("SCHOLARAIO_EMBED_SOURCE", "")
        monkeypatch.setenv("SCHOLARAIO_EMBED_CACHE_DIR", "")
        monkeypatch.setenv("SCHOLARAIO_EMBED_MODEL", "")
        monkeypatch.setenv("SCHOLARAIO_EMBED_API_BASE", "")
        monkeypatch.setenv("SCHOLARAIO_HF_ENDPOINT", "")
        monkeypatch.setenv("HF_ENDPOINT", "")
        cfg = _build_config(data, tmp_path)
        assert cfg.embed.provider == "local"
        assert cfg.embed.source == "huggingface"
        assert cfg.embed.cache_dir == "/yaml-cache"
        assert cfg.embed.model == "yaml-model"
        assert cfg.embed.hf_endpoint == "https://yaml-mirror.example"
        assert cfg.embed.api_base == "https://yaml-embed.example/v1"

    def test_embed_provider_defaults_to_local(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.embed.provider == "local"

    def test_openai_compat_embed_defaults_are_cloud_friendly(self, tmp_path):
        cfg = _build_config({"embed": {"provider": "openai-compat"}}, tmp_path)
        assert cfg.embed.model == "text-embedding-3-small"
        assert cfg.embed.api_base == "https://api.openai.com/v1"

    def test_openai_compat_embed_defaults_are_case_insensitive(self, tmp_path):
        cfg = _build_config({"embed": {"provider": "OpenAI-Compat"}}, tmp_path)
        assert cfg.embed.provider == "openai-compat"
        assert cfg.embed.model == "text-embedding-3-small"
        assert cfg.embed.api_base == "https://api.openai.com/v1"

    def test_embed_batch_size_min_1(self, tmp_path):
        cfg = _build_config({"embed": {"batch_size": 0}}, tmp_path)
        assert cfg.embed.batch_size == 1


class TestConfigProperties:
    def test_papers_dir_absolute(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.papers_dir.is_absolute()
        assert cfg.papers_dir == (tmp_path / "data" / "libraries" / "papers").resolve()

    def test_index_db_absolute(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.index_db.is_absolute()
        assert cfg.index_db == (tmp_path / "data" / "state" / "search" / "index.db").resolve()

    def test_log_file_absolute(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.log_file.is_absolute()

    def test_metrics_db_path(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.metrics_db_path == (tmp_path / "data" / "state" / "metrics" / "metrics.db").resolve()

    def test_topics_model_dir(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        assert cfg.topics_model_dir == (tmp_path / "data" / "state" / "topics").resolve()

    def test_runtime_path_accessors_default_to_logical_runtime_layout(self, tmp_path):
        cfg = _build_config({}, tmp_path)

        assert cfg.workspace_dir == (tmp_path / "workspace").resolve()
        assert cfg.workspace_figures_dir == (tmp_path / "workspace" / "_system" / "figures").resolve()
        assert (
            cfg.workspace_docx_output_path == (tmp_path / "workspace" / "_system" / "output" / "output.docx").resolve()
        )
        assert cfg.inbox_dir == (tmp_path / "data" / "spool" / "inbox").resolve()
        assert cfg.doc_inbox_dir == (tmp_path / "data" / "spool" / "inbox-doc").resolve()
        assert cfg.thesis_inbox_dir == (tmp_path / "data" / "spool" / "inbox-thesis").resolve()
        assert cfg.patent_inbox_dir == (tmp_path / "data" / "spool" / "inbox-patent").resolve()
        assert cfg.proceedings_inbox_dir == (tmp_path / "data" / "spool" / "inbox-proceedings").resolve()
        assert cfg.pending_dir == (tmp_path / "data" / "spool" / "pending").resolve()
        assert cfg.proceedings_dir == (tmp_path / "data" / "libraries" / "proceedings").resolve()
        assert cfg.explore_root == (tmp_path / "data" / "libraries" / "explore").resolve()
        assert cfg.toolref_root == (tmp_path / "data" / "libraries" / "toolref").resolve()
        assert cfg.citation_styles_dir == (tmp_path / "data" / "libraries" / "citation_styles").resolve()
        assert cfg.translation_bundle_root == (tmp_path / "workspace" / "_system" / "translation-bundles").resolve()
        assert cfg.state_root == (tmp_path / "data" / "state").resolve()
        assert cfg.cache_root == (tmp_path / "data" / "cache").resolve()
        assert cfg.runtime_root == (tmp_path / "data" / "runtime").resolve()
        assert cfg.search_state_dir == (tmp_path / "data" / "state" / "search").resolve()
        assert cfg.metrics_state_dir == (tmp_path / "data" / "state" / "metrics").resolve()
        assert cfg.topics_state_dir == (tmp_path / "data" / "state" / "topics").resolve()
        assert cfg.control_root == (tmp_path / ".scholaraio-control").resolve()
        assert cfg.instance_meta_path == (tmp_path / ".scholaraio-control" / "instance.json").resolve()
        assert cfg.migration_lock_path == (tmp_path / ".scholaraio-control" / "migration.lock").resolve()
        assert cfg.migration_journals_root == (tmp_path / ".scholaraio-control" / "migrations").resolve()

    def test_stateful_paths_ignore_legacy_locations_without_explicit_override(self, tmp_path):
        legacy_index = tmp_path / "data" / "index.db"
        legacy_index.parent.mkdir(parents=True)
        legacy_index.write_text("", encoding="utf-8")

        legacy_metrics = tmp_path / "data" / "metrics.db"
        legacy_metrics.write_text("", encoding="utf-8")

        legacy_topics = tmp_path / "data" / "topic_model"
        legacy_topics.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.index_db == (tmp_path / "data" / "state" / "search" / "index.db").resolve()
        assert cfg.metrics_db_path == (tmp_path / "data" / "state" / "metrics" / "metrics.db").resolve()
        assert cfg.topics_model_dir == (tmp_path / "data" / "state" / "topics").resolve()

    def test_papers_dir_ignores_legacy_default_location_when_present(self, tmp_path):
        legacy_papers = tmp_path / "data" / "papers"
        legacy_papers.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.papers_dir == (tmp_path / "data" / "libraries" / "papers").resolve()

    def test_papers_dir_prefers_durable_library_target_when_present(self, tmp_path):
        legacy_papers = tmp_path / "data" / "papers"
        target_papers = tmp_path / "data" / "libraries" / "papers"
        legacy_papers.mkdir(parents=True)
        target_papers.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.papers_dir == target_papers.resolve()

    def test_explicit_relative_legacy_papers_dir_override_is_honored(self, tmp_path):
        legacy_papers = tmp_path / "data" / "papers"
        legacy_papers.mkdir(parents=True)

        cfg = _build_config({"paths": {"papers_dir": "data/papers"}}, tmp_path)

        assert cfg.papers_dir == legacy_papers.resolve()

    def test_absolute_papers_dir_override_can_still_force_legacy_path(self, tmp_path):
        legacy_papers = tmp_path / "data" / "papers"
        target_papers = tmp_path / "data" / "libraries" / "papers"
        legacy_papers.mkdir(parents=True)
        target_papers.mkdir(parents=True)

        cfg = _build_config({"paths": {"papers_dir": str(legacy_papers)}}, tmp_path)

        assert cfg.papers_dir == legacy_papers.resolve()

    def test_citation_styles_dir_ignores_legacy_location_when_present(self, tmp_path):
        legacy_styles = tmp_path / "data" / "citation_styles"
        legacy_styles.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.citation_styles_dir == (tmp_path / "data" / "libraries" / "citation_styles").resolve()

    def test_toolref_root_ignores_legacy_location_when_present(self, tmp_path):
        legacy_toolref = tmp_path / "data" / "toolref"
        legacy_toolref.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.toolref_root == (tmp_path / "data" / "libraries" / "toolref").resolve()

    def test_explore_root_ignores_legacy_location_when_present(self, tmp_path):
        legacy_explore = tmp_path / "data" / "explore"
        legacy_explore.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.explore_root == (tmp_path / "data" / "libraries" / "explore").resolve()

    def test_proceedings_dir_ignores_legacy_location_when_present(self, tmp_path):
        legacy_proceedings = tmp_path / "data" / "proceedings"
        legacy_proceedings.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.proceedings_dir == (tmp_path / "data" / "libraries" / "proceedings").resolve()

    def test_spool_dirs_ignore_legacy_locations_when_present(self, tmp_path):
        legacy_paths = {
            "inbox_dir": tmp_path / "data" / "inbox",
            "doc_inbox_dir": tmp_path / "data" / "inbox-doc",
            "thesis_inbox_dir": tmp_path / "data" / "inbox-thesis",
            "patent_inbox_dir": tmp_path / "data" / "inbox-patent",
            "proceedings_inbox_dir": tmp_path / "data" / "inbox-proceedings",
            "pending_dir": tmp_path / "data" / "pending",
        }
        for path in legacy_paths.values():
            path.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.inbox_dir == (tmp_path / "data" / "spool" / "inbox").resolve()
        assert cfg.doc_inbox_dir == (tmp_path / "data" / "spool" / "inbox-doc").resolve()
        assert cfg.thesis_inbox_dir == (tmp_path / "data" / "spool" / "inbox-thesis").resolve()
        assert cfg.patent_inbox_dir == (tmp_path / "data" / "spool" / "inbox-patent").resolve()
        assert cfg.proceedings_inbox_dir == (tmp_path / "data" / "spool" / "inbox-proceedings").resolve()
        assert cfg.pending_dir == (tmp_path / "data" / "spool" / "pending").resolve()

    def test_spool_dirs_prefer_spool_targets_when_present(self, tmp_path):
        legacy_paths = [
            tmp_path / "data" / "inbox",
            tmp_path / "data" / "inbox-doc",
            tmp_path / "data" / "inbox-thesis",
            tmp_path / "data" / "inbox-patent",
            tmp_path / "data" / "inbox-proceedings",
            tmp_path / "data" / "pending",
        ]
        target_paths = {
            "inbox_dir": tmp_path / "data" / "spool" / "inbox",
            "doc_inbox_dir": tmp_path / "data" / "spool" / "inbox-doc",
            "thesis_inbox_dir": tmp_path / "data" / "spool" / "inbox-thesis",
            "patent_inbox_dir": tmp_path / "data" / "spool" / "inbox-patent",
            "proceedings_inbox_dir": tmp_path / "data" / "spool" / "inbox-proceedings",
            "pending_dir": tmp_path / "data" / "spool" / "pending",
        }
        for path in [*legacy_paths, *target_paths.values()]:
            path.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        for attr, path in target_paths.items():
            assert getattr(cfg, attr) == path.resolve()

    def test_toolref_root_prefers_durable_library_target_when_present(self, tmp_path):
        legacy_toolref = tmp_path / "data" / "toolref"
        target_toolref = tmp_path / "data" / "libraries" / "toolref"
        legacy_toolref.mkdir(parents=True)
        target_toolref.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.toolref_root == target_toolref.resolve()

    def test_explore_root_prefers_durable_library_target_when_present(self, tmp_path):
        legacy_explore = tmp_path / "data" / "explore"
        target_explore = tmp_path / "data" / "libraries" / "explore"
        legacy_explore.mkdir(parents=True)
        target_explore.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.explore_root == target_explore.resolve()

    def test_proceedings_dir_prefers_durable_library_target_when_present(self, tmp_path):
        legacy_proceedings = tmp_path / "data" / "proceedings"
        target_proceedings = tmp_path / "data" / "libraries" / "proceedings"
        legacy_proceedings.mkdir(parents=True)
        target_proceedings.mkdir(parents=True)

        cfg = _build_config({}, tmp_path)

        assert cfg.proceedings_dir == target_proceedings.resolve()

    def test_runtime_path_accessors_follow_current_workspace_system_defaults(self, tmp_path):
        cfg = _build_config(
            {
                "paths": {
                    "papers_dir": "library/papers",
                    "workspace_dir": "projects",
                }
            },
            tmp_path,
        )

        assert cfg.papers_dir == (tmp_path / "library" / "papers").resolve()
        assert cfg.workspace_dir == (tmp_path / "projects").resolve()
        assert cfg.workspace_figures_dir == (tmp_path / "projects" / "_system" / "figures").resolve()
        assert (
            cfg.workspace_docx_output_path == (tmp_path / "projects" / "_system" / "output" / "output.docx").resolve()
        )
        assert cfg.citation_styles_dir == (tmp_path / "data" / "libraries" / "citation_styles").resolve()
        assert cfg.translation_bundle_root == (tmp_path / "projects" / "_system" / "translation-bundles").resolve()

    def test_runtime_path_accessors_allow_explicit_overrides(self, tmp_path):
        cfg = _build_config(
            {
                "paths": {
                    "workspace_dir": "projects",
                    "workspace_figures_dir": "projects/_system/figures",
                    "workspace_docx_output_path": "projects/_system/output/output.docx",
                    "inbox_dir": "queues/inbox",
                    "pending_dir": "queues/pending-review",
                    "explore_root": "stores/explore",
                    "toolref_root": "stores/toolref",
                    "citation_styles_dir": "stores/styles",
                    "translation_bundle_root": "projects/_system/translation-bundles",
                    "state_root": "var/state",
                    "cache_root": "var/cache",
                    "runtime_root": "var/runtime",
                }
            },
            tmp_path,
        )

        assert cfg.workspace_dir == (tmp_path / "projects").resolve()
        assert cfg.workspace_figures_dir == (tmp_path / "projects" / "_system" / "figures").resolve()
        assert (
            cfg.workspace_docx_output_path == (tmp_path / "projects" / "_system" / "output" / "output.docx").resolve()
        )
        assert cfg.inbox_dir == (tmp_path / "queues" / "inbox").resolve()
        assert cfg.pending_dir == (tmp_path / "queues" / "pending-review").resolve()
        assert cfg.explore_root == (tmp_path / "stores" / "explore").resolve()
        assert cfg.toolref_root == (tmp_path / "stores" / "toolref").resolve()
        assert cfg.citation_styles_dir == (tmp_path / "stores" / "styles").resolve()
        assert cfg.translation_bundle_root == (tmp_path / "projects" / "_system" / "translation-bundles").resolve()
        assert cfg.state_root == (tmp_path / "var" / "state").resolve()
        assert cfg.cache_root == (tmp_path / "var" / "cache").resolve()
        assert cfg.runtime_root == (tmp_path / "var" / "runtime").resolve()

    def test_stateful_paths_allow_explicit_legacy_or_custom_overrides(self, tmp_path):
        cfg = _build_config(
            {
                "paths": {
                    "index_db": "legacy/index.db",
                    "state_root": "var/state",
                },
                "logging": {
                    "metrics_db": "legacy/metrics.db",
                },
                "topics": {
                    "model_dir": "legacy/topic_model",
                },
            },
            tmp_path,
        )

        assert cfg.index_db == (tmp_path / "legacy" / "index.db").resolve()
        assert cfg.metrics_db_path == (tmp_path / "legacy" / "metrics.db").resolve()
        assert cfg.topics_model_dir == (tmp_path / "legacy" / "topic_model").resolve()
        assert cfg.search_state_dir == (tmp_path / "var" / "state" / "search").resolve()


class TestEnsureDirs:
    def test_creates_required_dirs(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        assert cfg.papers_dir.exists()
        assert cfg.inbox_dir.exists()
        assert cfg.proceedings_inbox_dir.exists()
        assert cfg.thesis_inbox_dir.exists()
        assert cfg.patent_inbox_dir.exists()
        assert cfg.doc_inbox_dir.exists()
        assert cfg.pending_dir.exists()
        assert cfg.proceedings_dir.exists()
        assert cfg.workspace_dir.exists()
        assert cfg.explore_root.exists()
        assert cfg.state_root.exists()
        assert cfg.cache_root.exists()
        assert cfg.runtime_root.exists()
        assert cfg.search_state_dir.exists()
        assert cfg.metrics_state_dir.exists()
        assert cfg.topics_state_dir.exists()
        assert cfg.toolref_root.exists()
        assert cfg.citation_styles_dir.exists()
        assert cfg.workspace_figures_dir.exists()
        assert cfg.workspace_docx_output_path.parent.exists()
        assert cfg.translation_bundle_root.exists()
        assert cfg.control_root.exists()
        assert cfg.migration_journals_root.exists()

    def test_idempotent(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        cfg.ensure_dirs()
        cfg.ensure_dirs()  # should not raise

    def test_ensure_dirs_uses_accessor_paths(self, tmp_path):
        cfg = _build_config(
            {
                "paths": {
                    "papers_dir": "library/papers",
                    "workspace_dir": "projects",
                    "workspace_figures_dir": "projects/_system/figures",
                    "workspace_docx_output_path": "projects/_system/output/output.docx",
                    "translation_bundle_root": "projects/_system/translation-bundles",
                    "inbox_dir": "queues/inbox-main",
                    "doc_inbox_dir": "queues/inbox-docs",
                    "thesis_inbox_dir": "queues/inbox-thesis",
                    "patent_inbox_dir": "queues/inbox-patent",
                    "proceedings_inbox_dir": "queues/inbox-proceedings",
                    "pending_dir": "queues/pending-review",
                    "proceedings_dir": "libraries/proceedings",
                }
            },
            tmp_path,
        )

        cfg.ensure_dirs()

        assert cfg.papers_dir.exists()
        assert cfg.workspace_dir.exists()
        assert cfg.inbox_dir.exists()
        assert cfg.doc_inbox_dir.exists()
        assert cfg.thesis_inbox_dir.exists()
        assert cfg.patent_inbox_dir.exists()
        assert cfg.proceedings_inbox_dir.exists()
        assert cfg.pending_dir.exists()
        assert cfg.proceedings_dir.exists()
        assert cfg.citation_styles_dir.exists()
        assert cfg.workspace_figures_dir.exists()
        assert cfg.workspace_docx_output_path.parent.exists()
        assert cfg.translation_bundle_root.exists()
        assert not (tmp_path / "data" / "inbox").exists()
        assert not (tmp_path / "data" / "inbox-doc").exists()
        assert not (tmp_path / "data" / "inbox-thesis").exists()
        assert not (tmp_path / "data" / "inbox-patent").exists()
        assert not (tmp_path / "data" / "inbox-proceedings").exists()
        assert not (tmp_path / "data" / "pending").exists()
        assert not (tmp_path / "data" / "proceedings").exists()


class TestResolvedApiKey:
    def test_config_key_wins(self, tmp_path, monkeypatch):
        data = {"llm": {"api_key": "from-config"}}
        cfg = _build_config(data, tmp_path)
        monkeypatch.setenv("SCHOLARAIO_LLM_API_KEY", "from-env")
        assert cfg.resolved_api_key() == "from-config"

    def test_generic_env_var(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("SCHOLARAIO_LLM_API_KEY", "generic-key")
        assert cfg.resolved_api_key() == "generic-key"

    def test_backend_specific_env_openai(self, tmp_path, monkeypatch):
        cfg = _build_config({"llm": {"backend": "openai-compat"}}, tmp_path)
        monkeypatch.delenv("SCHOLARAIO_LLM_API_KEY", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dsk-123")
        assert cfg.resolved_api_key() == "dsk-123"

    def test_backend_specific_env_anthropic(self, tmp_path, monkeypatch):
        cfg = _build_config({"llm": {"backend": "anthropic"}}, tmp_path)
        monkeypatch.delenv("SCHOLARAIO_LLM_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
        assert cfg.resolved_api_key() == "ant-key"

    def test_backend_specific_env_google(self, tmp_path, monkeypatch):
        cfg = _build_config({"llm": {"backend": "google"}}, tmp_path)
        monkeypatch.delenv("SCHOLARAIO_LLM_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "goog-key")
        assert cfg.resolved_api_key() == "goog-key"

    def test_no_key_returns_empty(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        for v in ("SCHOLARAIO_LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(v, raising=False)
        assert cfg.resolved_api_key() == ""

    def test_mineru_key_from_config(self, tmp_path):
        cfg = _build_config({"ingest": {"mineru_api_key": "mu-key"}}, tmp_path)
        assert cfg.resolved_mineru_api_key() == "mu-key"

    def test_mineru_key_from_env(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("MINERU_API_KEY", "mu-env")
        assert cfg.resolved_mineru_api_key() == "mu-env"

    def test_mineru_token_env_wins_over_legacy_api_key_env(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("MINERU_TOKEN", "new-token")
        monkeypatch.setenv("MINERU_API_KEY", "legacy-token")
        assert cfg.resolved_mineru_api_key() == "new-token"

    def test_s2_key_from_config(self, tmp_path):
        cfg = _build_config({"ingest": {"s2_api_key": "s2-cfg"}}, tmp_path)
        assert cfg.resolved_s2_api_key() == "s2-cfg"

    def test_s2_key_from_env(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("S2_API_KEY", "s2-env")
        assert cfg.resolved_s2_api_key() == "s2-env"

    def test_s2_key_config_wins_over_env(self, tmp_path, monkeypatch):
        cfg = _build_config({"ingest": {"s2_api_key": "s2-cfg"}}, tmp_path)
        monkeypatch.setenv("S2_API_KEY", "s2-env")
        assert cfg.resolved_s2_api_key() == "s2-cfg"

    def test_s2_key_empty_when_unset(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.delenv("S2_API_KEY", raising=False)
        assert cfg.resolved_s2_api_key() == ""

    def test_embed_key_from_embed_config(self, tmp_path):
        cfg = _build_config({"embed": {"api_key": "embed-key"}}, tmp_path)
        assert cfg.resolved_embed_api_key() == "embed-key"

    def test_embed_key_prefers_embed_env(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.setenv("SCHOLARAIO_EMBED_API_KEY", "embed-env")
        assert cfg.resolved_embed_api_key() == "embed-env"

    def test_embed_key_falls_back_to_llm(self, tmp_path, monkeypatch):
        cfg = _build_config({}, tmp_path)
        monkeypatch.delenv("SCHOLARAIO_EMBED_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("SCHOLARAIO_LLM_API_KEY", "llm-env")
        assert cfg.resolved_embed_api_key() == "llm-env"


class TestLoadConfig:
    def test_load_from_explicit_path(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("llm:\n  model: test-model\n", encoding="utf-8")
        cfg = load_config(cfg_file)
        assert cfg.llm.model == "test-model"

    def test_local_yaml_overrides(self, tmp_path):
        (tmp_path / "config.yaml").write_text(
            "llm:\n  model: base-model\n  timeout: 30\n",
            encoding="utf-8",
        )
        (tmp_path / "config.local.yaml").write_text(
            "llm:\n  model: local-model\n",
            encoding="utf-8",
        )
        cfg = load_config(tmp_path / "config.yaml")
        assert cfg.llm.model == "local-model"
        assert cfg.llm.timeout == 30  # preserved from base

    def test_nonexistent_path_uses_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "nonexistent.yaml")
        assert cfg.llm.model == "deepseek-chat"

    def test_empty_yaml(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("", encoding="utf-8")
        cfg = load_config(cfg_file)
        assert cfg.llm.model == "deepseek-chat"

    def test_env_var_config_path(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text("search:\n  top_k: 42\n", encoding="utf-8")
        monkeypatch.setenv("SCHOLARAIO_CONFIG", str(cfg_file))
        cfg = load_config()
        assert cfg.search.top_k == 42
