from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
from importlib.machinery import PathFinder
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_GUIDES = (ROOT / "AGENTS.md", ROOT / "CLAUDE.md")
CANONICAL_IMPLEMENTATION_ROOTS = (
    ROOT / "scholaraio" / "core",
    ROOT / "scholaraio" / "providers",
    ROOT / "scholaraio" / "stores",
    ROOT / "scholaraio" / "projects",
    ROOT / "scholaraio" / "services",
    ROOT / "scholaraio" / "interfaces",
)
LEGACY_FACADE_MODULES = (
    "scholaraio.audit",
    "scholaraio.backup",
    "scholaraio.citation_check",
    "scholaraio.citation_styles",
    "scholaraio.config",
    "scholaraio.diagram",
    "scholaraio.document",
    "scholaraio.explore",
    "scholaraio.export",
    "scholaraio.index",
    "scholaraio.ingest",
    "scholaraio.ingest.extractor",
    "scholaraio.ingest.metadata",
    "scholaraio.ingest.mineru",
    "scholaraio.ingest.parser_matrix_benchmark",
    "scholaraio.ingest.pdf_fallback",
    "scholaraio.ingest.pipeline",
    "scholaraio.ingest.proceedings",
    "scholaraio.insights",
    "scholaraio.loader",
    "scholaraio.log",
    "scholaraio.metrics",
    "scholaraio.migration_control",
    "scholaraio.papers",
    "scholaraio.patent_fetch",
    "scholaraio.proceedings",
    "scholaraio.setup",
    "scholaraio.sources",
    "scholaraio.sources.arxiv",
    "scholaraio.sources.endnote",
    "scholaraio.sources.webtools",
    "scholaraio.sources.zotero",
    "scholaraio.toolref",
    "scholaraio.topics",
    "scholaraio.translate",
    "scholaraio.uspto_odp",
    "scholaraio.uspto_ppubs",
    "scholaraio.vectors",
    "scholaraio.workspace",
)
LEGACY_FACADE_ROOT_EXPORTS = (
    "audit",
    "backup",
    "citation_check",
    "citation_styles",
    "config",
    "diagram",
    "document",
    "explore",
    "export",
    "index",
    "ingest",
    "insights",
    "loader",
    "log",
    "metrics",
    "migration_control",
    "papers",
    "patent_fetch",
    "proceedings",
    "setup",
    "sources",
    "topics",
    "toolref",
    "translate",
    "uspto_odp",
    "uspto_ppubs",
    "vectors",
    "workspace",
)


def _local_package_spec(module_name: str):
    importlib.import_module("scholaraio")
    package_root = ROOT / "scholaraio"
    relative_parts = module_name.split(".")[1:]
    search_root = package_root.joinpath(*relative_parts[:-1])
    if not search_root.exists():
        return None
    return PathFinder.find_spec(module_name, [str(search_root)])


def test_gui_root_is_reserved_as_presentation_only_boundary() -> None:
    readme = ROOT / "gui" / "README.md"

    assert readme.exists()
    content = readme.read_text(encoding="utf-8")
    assert "presentation" in content.lower()
    assert "MUST NOT" in content
    assert "runtime" in content.lower()


def test_future_package_namespaces_are_importable_without_moving_behavior() -> None:
    for name in ("core", "providers", "stores", "projects", "services", "interfaces", "compat"):
        module = importlib.import_module(f"scholaraio.{name}")

        assert module.__name__ == f"scholaraio.{name}"


def test_config_core_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.core.config")
    core = importlib.import_module("scholaraio.core.config")

    assert core.Config is legacy.Config
    assert core.PathsConfig is legacy.PathsConfig
    assert core.LLMConfig is legacy.LLMConfig
    assert core.load_config is legacy.load_config
    assert core._build_config is legacy._build_config
    assert core._deep_merge is legacy._deep_merge


def test_config_legacy_module_aliases_core_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.core.config")
    core = importlib.import_module("scholaraio.core.config")

    assert legacy is core


def test_config_implementation_lives_in_core_namespace() -> None:
    legacy = importlib.import_module("scholaraio.core.config")
    core = importlib.import_module("scholaraio.core.config")

    source = Path(inspect.getsourcefile(core.load_config) or "")

    assert source.parts[-3:] == ("scholaraio", "core", "config.py")
    assert legacy.load_config is core.load_config


def test_project_guides_describe_migrated_runtime_modules_by_canonical_namespace() -> None:
    required_rows = (
        "`scholaraio/stores/explore.py`",
        "`scholaraio/projects/workspace.py`",
        "`scholaraio/services/insights.py`",
        "`scholaraio/services/translate.py`",
        "`scholaraio/interfaces/cli/`",
        "`scholaraio/cli.py` as the published entrypoint",
    )
    stale_rows = (
        "| `explore.py` |",
        "| `workspace.py` |",
        "| `insights.py` |",
        "| `translate.py` |",
        "| `cli.py` | Main CLI entry point |",
        "(`explore.py` compatibility alias)",
        "(`workspace.py` compatibility alias)",
        "(`insights.py` compatibility alias)",
        "(`translate.py` compatibility alias)",
        "`cli.py` compatibility facade",
    )

    for guide in PROJECT_GUIDES:
        content = guide.read_text(encoding="utf-8")
        for row in required_rows:
            assert row in content, f"{guide.name} should document {row}"
        for row in stale_rows:
            assert row not in content, f"{guide.name} still has stale module row {row}"


def test_migration_development_docs_do_not_restate_resolved_path_authority_gaps() -> None:
    config_audit = (ROOT / "docs" / "development" / "config-surface-audit.md").read_text(encoding="utf-8")
    migration_sequence = (ROOT / "docs" / "development" / "directory-migration-sequence.md").read_text(encoding="utf-8")

    stale_phrases = (
        "Status: Draft",
        "workspace_dir` Exists Only as a Hardcoded Property",
        "real migrate-run support for queues and the main paper library",
        "current imports are still broadly flat",
        "this is better handled by a future workspace/output convention than by global config",
        "add an explicit config accessor such as `translation_bundle_root`",
        'translation_bundle_root` defaults under `cfg.workspace_dir / "translation-ws"',
        "the non-breaking compatibility default remains `workspace/translation-ws/<paper>/`",
        "document export defaults to `<workspace>/output.docx`",
        "diagram generation defaults to `<workspace>/figures/`",
        "the non-breaking compatibility default remains `<workspace>/output.docx`",
        "the non-breaking compatibility default remains `<workspace>/figures/`",
        "`scholaraio/translate.py`",
        "`scholaraio/translate.py:578-595` locks portable translation bundles under `workspace/translation-ws/`",
        "`scholaraio/translate.py` anchors portable output to `workspace/translation-ws/`",
    )
    for phrase in stale_phrases:
        assert phrase not in config_audit
        assert phrase not in migration_sequence

    assert "Status: Historical audit, updated for the current compatibility window" in config_audit
    assert "workspace_figures_dir" in config_audit
    assert "workspace_docx_output_path" in config_audit
    assert "translation_bundle_root" in config_audit
    assert "primary default authority for portable translation bundles" in config_audit
    assert "resolves portable translation bundles through `translation_bundle_root`" in migration_sequence
    assert "migrate run --store spool --confirm" in migration_sequence
    assert "migrate run --store papers --confirm" in migration_sequence


def test_upgrade_entry_and_user_migration_strategy_reflect_current_breaking_cleanup_generation() -> None:
    upgrade_plan = (ROOT / "docs" / "development" / "scholaraio-upgrade-plan.md").read_text(encoding="utf-8")
    user_strategy = (ROOT / "docs" / "development" / "user-data-migration-strategy.md").read_text(encoding="utf-8")

    assert "Last Updated: 2026-04-24" in upgrade_plan
    assert "docs/development/upgrade-validation-matrix.md" in upgrade_plan
    assert "docs/development/breaking-compat-cleanup-plan.md" in upgrade_plan
    assert "上述 7 份权威文档" in upgrade_plan
    assert "breaking cleanup generation is now the active release gate" in upgrade_plan
    assert "migrate finalize --confirm" in upgrade_plan
    assert "Status: Historical compatibility-window strategy record" in user_strategy
    assert (
        "migration-run support still covers `citation_styles`, `toolref`, `explore`, `proceedings`, `spool`, and `papers`"
        in user_strategy
    )
    assert "the active runtime is now fresh-layout-only" in user_strategy
    assert "migrate finalize --confirm" in user_strategy
    assert "\n- `scholaraio/translate.py`\n" not in user_strategy
    assert "`scholaraio/services/translate.py`" in user_strategy


def test_upgrade_validation_matrix_tracks_current_release_gate_and_migration_surface() -> None:
    validation = (ROOT / "docs" / "development" / "upgrade-validation-matrix.md").read_text(encoding="utf-8")
    mechanism_spec = (ROOT / "docs" / "development" / "migration-mechanism-spec.md").read_text(encoding="utf-8")
    user_strategy = (ROOT / "docs" / "development" / "user-data-migration-strategy.md").read_text(encoding="utf-8")

    assert "Status: Compatibility-window validation authority" in validation
    assert "Last Updated: 2026-04-24" in validation
    assert "A `--help` screen does not count as functional validation." in validation
    assert "`../scholaraio/`" in validation
    assert "workspace/release-validation/<stamp>/" in validation
    assert "`citation_styles`, `toolref`, `explore`, `proceedings`, `spool`, `papers`, and `workspace`" in validation
    assert "scholaraio migrate plan --migration-id <migration-id>" in validation
    assert "scholaraio migrate upgrade --migration-id <migration-id> --confirm" in validation
    assert "scholaraio migrate run --store <store> --migration-id <migration-id> --confirm" in validation
    assert "scholaraio migrate cleanup --migration-id <migration-id> --confirm" in validation
    assert "scholaraio migrate finalize --migration-id <migration-id> --confirm" in validation
    assert "all provider-backed surfaces must be marked explicitly as unverified" in validation.lower()
    assert "Rehearsal roots must be writable." in validation
    assert "set `SCHOLARAIO_CONFIG=<rehearsal-root>/config.yaml`" in validation
    assert "`../scholaraio/config.yaml`" in validation
    assert "`../scholaraio/config.local.yaml`" in validation
    assert "stores classified `not_present` must be recorded as `N/A`" in validation
    assert (
        "do not parallelize `status`, `plan`, `verify`, `run`, `cleanup`, `cleanup --confirm`, `finalize --confirm`, or `upgrade --confirm`"
        in validation
    )
    assert "pipeline --dry-run --inspect` by itself is incomplete" in validation
    assert "`diagram --from-ir`" in validation
    assert "`diagram --from-text`" in validation
    assert "edges must use `from` / `to` keys" in validation
    assert "migrate durable user-owned content as whole trees" in validation
    assert "rebuild derived search/index state wherever a supported rebuild path exists" in validation
    assert "migrate PDF / Markdown / JSON / images / workspace trees intact" in validation
    assert "`index --rebuild` and `embed --rebuild`" in validation
    assert "seed `fresh-root/` only with new-layout stores" in validation
    assert "`toolref fetch`" in validation
    assert "cp ../scholaraio/config.yaml" in validation
    assert "docs/development/upgrade-validation-matrix.md" in mechanism_spec
    assert "migrate upgrade --confirm" in mechanism_spec
    assert "migrate finalize --confirm" in mechanism_spec
    assert "default migration posture SHOULD therefore be: migrate durable content trees" in user_strategy


def test_authoritative_migration_specs_are_not_stale_drafts() -> None:
    structure_spec = (ROOT / "docs" / "development" / "directory-structure-spec.md").read_text(encoding="utf-8")
    mechanism_spec = (ROOT / "docs" / "development" / "migration-mechanism-spec.md").read_text(encoding="utf-8")

    assert "Status: Draft" not in structure_spec
    assert "Status: Draft" not in mechanism_spec
    assert "Status: Current layout specification" in structure_spec
    assert "Status: Compatibility-window mechanism specification" in mechanism_spec
    assert "Last Updated: 2026-04-24" in structure_spec
    assert "Last Updated: 2026-04-24" in mechanism_spec


def test_workspace_topology_docs_keep_named_workspaces_free_form_and_system_outputs_reserved() -> None:
    structure_spec = (ROOT / "docs" / "development" / "directory-structure-spec.md").read_text(encoding="utf-8")
    migration_sequence = (ROOT / "docs" / "development" / "directory-migration-sequence.md").read_text(encoding="utf-8")
    user_strategy = (ROOT / "docs" / "development" / "user-data-migration-strategy.md").read_text(encoding="utf-8")

    assert "`workspace/<name>/` MUST remain a free-form user project tree" in structure_spec
    assert "system-owned or cross-workspace outputs SHOULD converge under `workspace/_system/`" in structure_spec
    assert "| `workspace/figures/` | `workspace/_system/figures/` |" in structure_spec
    assert "| `workspace/output.*` | `workspace/_system/output/` |" in structure_spec

    assert "named workspaces remain opaque/free-form project roots" in migration_sequence
    assert "`workspace/translation-ws/` -> `workspace/_system/translation-bundles/`" in migration_sequence
    assert "`workspace/figures/` -> `workspace/_system/figures/`" in migration_sequence
    assert "`workspace/output.*` -> `workspace/_system/output/`" in migration_sequence
    assert (
        "the minimal additive `workspace.yaml` envelope is `schema_version`, optional `name` / `description` / `tags`, optional explicit `mounts`, and optional `outputs`"
        in migration_sequence
    )
    assert "it MUST NOT replace root `papers.json` or future-compatible `refs/papers.json`" in migration_sequence
    assert "the validation/normalization policy for that minimal envelope is also fixed" in migration_sequence
    assert "absent manifests stay valid" in migration_sequence
    assert "unknown keys are preserved" in migration_sequence
    assert "`outputs.default_dir` stays workspace-relative" in migration_sequence
    assert "shared-store mounts are logical IDs rather than physical paths" in migration_sequence
    assert (
        "`explore` remains a shared store for the compatibility window; if workspace-local mounts are added later,"
        in migration_sequence
    )
    assert "they MUST be explicit manifest-declared opt-ins and SHOULD start read-only" in migration_sequence
    assert "`.claude/skills/` remains the canonical skill source and is not a migration target" in migration_sequence
    assert (
        "whether `workspace/translation-ws/` remains a special export root or becomes a more general project-export area"
        not in migration_sequence
    )
    assert (
        "whether legacy `workspace/figures/` and root-level `workspace/output.*` fold into `workspace/<name>/outputs/` or `workspace/_system/`"
        not in migration_sequence
    )
    assert "the exact future workspace manifest schema remains deferred" not in migration_sequence
    assert "workspace-local mounts stay out of scope until a later design pass" not in migration_sequence

    assert "future workspace migration MUST NOT turn named workspaces into rigid templates" in user_strategy
    assert "system-owned workspace outputs SHOULD migrate toward `workspace/_system/`" in user_strategy
    assert "future moves SHOULD happen by changing `translation_bundle_root`" in user_strategy
    assert (
        "any future `workspace.yaml` MUST stay additive and MUST NOT replace `papers.json` / `refs/papers.json`"
        in structure_spec
    )
    assert "future manifest-driven mounts or output preferences MUST be explicit opt-ins" in structure_spec
    assert "### 7.2.1 Minimal `workspace.yaml` Envelope" in structure_spec
    assert "schema_version: 1" in structure_spec
    assert "name: turbulence-review" in structure_spec
    assert "mounts:" in structure_spec
    assert "explore: []" in structure_spec
    assert "toolref: []" in structure_spec
    assert "outputs:" in structure_spec
    assert "default_dir: outputs/" in structure_spec
    assert "paper references MUST remain authoritative in `papers.json` / `refs/papers.json`" in structure_spec
    assert "### 7.2.2 Manifest Validation and Normalization Rules" in structure_spec
    assert "the absence of `workspace.yaml` MUST remain a normal, fully supported state" in structure_spec
    assert "current readers recognize `schema_version: 1`" in structure_spec
    assert "unknown mount buckets and unknown top-level keys SHOULD be preserved and ignored" in structure_spec
    assert "`outputs.default_dir`, when present, MUST resolve to a workspace-relative path" in structure_spec
    assert "normalization SHOULD be idempotent" in structure_spec
    assert "`workspace.yaml` MUST NOT duplicate paper-reference payloads" in structure_spec


def test_migration_docs_reference_canonical_workspace_explore_and_insights_modules() -> None:
    migration_sequence = (ROOT / "docs" / "development" / "directory-migration-sequence.md").read_text(encoding="utf-8")
    user_strategy = (ROOT / "docs" / "development" / "user-data-migration-strategy.md").read_text(encoding="utf-8")

    for content in (migration_sequence, user_strategy):
        assert "\n- `scholaraio/workspace.py`\n" not in content
        assert "\n- `scholaraio/explore.py`\n" not in content
        assert "\n- `scholaraio/insights.py`\n" not in content

    assert "`scholaraio/projects/workspace.py`" in migration_sequence
    assert "`scholaraio/stores/explore.py`" in migration_sequence
    assert "`scholaraio/services/insights.py`" in migration_sequence
    assert "`scholaraio/projects/workspace.py`" in user_strategy
    assert "`scholaraio/stores/explore.py`" in user_strategy
    assert "`scholaraio/services/insights.py`" in user_strategy


def test_config_surface_audit_references_canonical_store_and_service_modules() -> None:
    config_audit = (ROOT / "docs" / "development" / "config-surface-audit.md").read_text(encoding="utf-8")

    assert "`scholaraio/proceedings.py`" not in config_audit
    assert "`scholaraio/explore.py:`" not in config_audit
    assert "`scholaraio/citation_styles.py:`" not in config_audit
    assert "`scholaraio/insights.py:`" not in config_audit

    assert "`scholaraio/stores/proceedings.py:proceedings_db_path`" in config_audit
    assert "`scholaraio/stores/proceedings.py:iter_proceedings_dirs`" in config_audit
    assert "`scholaraio/stores/explore.py:_explore_root`" in config_audit
    assert "`scholaraio/stores/explore.py:_fetch_page`" in config_audit
    assert "`scholaraio/stores/citation_styles.py:styles_dir`" in config_audit
    assert "`scholaraio/services/insights.py:recommend_unread_neighbors`" in config_audit


def test_upgrade_docs_lock_policy_decisions_for_manifest_mounts_skills_and_compat_cleanup() -> None:
    migration_sequence = (ROOT / "docs" / "development" / "directory-migration-sequence.md").read_text(encoding="utf-8")
    upgrade_plan = (ROOT / "docs" / "development" / "scholaraio-upgrade-plan.md").read_text(encoding="utf-8")

    assert (
        "compatibility fallback readers stay in place through a full deprecation window and may be removed only in a later breaking-layout generation"
        in migration_sequence
    )
    assert "breaking cleanup generation is now the active release gate" in upgrade_plan
    assert "legacy public import facades are removed" in upgrade_plan
    assert "migrate finalize --confirm" in upgrade_plan
    assert "The following implementation details should remain deferred" in migration_sequence
    assert "`projects/workspace.py:read_manifest()` now parses `workspace.yaml` when present" in migration_sequence
    assert "treats newer schema versions as opaque metadata instead of rewriting them blindly" in migration_sequence
    assert (
        "`interfaces/cli/workspace.py` now surfaces additive `workspace.yaml` metadata in `ws list` / `ws show`"
        in migration_sequence
    )
    assert "keeping manifest-declared mounts informational only" in migration_sequence
    assert (
        "the actual parser/validator implementation for the minimal `workspace.yaml` envelope above"
        not in migration_sequence
    )
    assert "any actual implementation of manifest-declared workspace-local `explore` mounts" in migration_sequence
    assert "any attempt to relocate canonical skill files away from `.claude/skills/`" not in migration_sequence


def test_canonical_implementation_modules_do_not_import_legacy_facades() -> None:
    offenders: list[str] = []

    for root in CANONICAL_IMPLEMENTATION_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                module_names: list[str] = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    module_names.append(node.module)
                    if node.module == "scholaraio":
                        for alias in node.names:
                            if alias.name in LEGACY_FACADE_ROOT_EXPORTS:
                                rel_path = path.relative_to(ROOT)
                                offenders.append(f"{rel_path}:{node.lineno}: scholaraio.{alias.name}")
                elif isinstance(node, ast.Import):
                    module_names.extend(alias.name for alias in node.names)
                for module_name in module_names:
                    if module_name in LEGACY_FACADE_MODULES or any(
                        module_name.startswith(f"{legacy}.") for legacy in LEGACY_FACADE_MODULES
                    ):
                        rel_path = path.relative_to(ROOT)
                        offenders.append(f"{rel_path}:{node.lineno}: {module_name}")

    assert not offenders, "canonical implementation modules should not import legacy facades:\n" + "\n".join(offenders)


def test_removed_legacy_public_modules_do_not_exist_in_local_package_tree() -> None:
    for module_name in LEGACY_FACADE_MODULES:
        assert _local_package_spec(module_name) is None, f"{module_name} should not exist in the local package tree"


def test_citation_styles_store_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.stores.citation_styles")
    store = importlib.import_module("scholaraio.stores.citation_styles")

    assert store.BUILTIN_STYLES is legacy.BUILTIN_STYLES
    assert store.get_formatter is legacy.get_formatter
    assert store.list_styles is legacy.list_styles
    assert store.styles_dir is legacy.styles_dir


def test_citation_styles_implementation_lives_in_store_namespace() -> None:
    legacy = importlib.import_module("scholaraio.stores.citation_styles")
    store = importlib.import_module("scholaraio.stores.citation_styles")

    source = Path(inspect.getsourcefile(store.get_formatter) or "")

    assert source.parts[-3:] == ("scholaraio", "stores", "citation_styles.py")
    assert legacy.get_formatter is store.get_formatter


def test_citation_styles_legacy_module_aliases_store_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.stores.citation_styles")
    store = importlib.import_module("scholaraio.stores.citation_styles")

    assert legacy is store


def test_papers_store_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.stores.papers")
    store = importlib.import_module("scholaraio.stores.papers")

    assert store.paper_dir is legacy.paper_dir
    assert store.iter_paper_dirs is legacy.iter_paper_dirs
    assert store.read_meta is legacy.read_meta
    assert store.write_meta is legacy.write_meta
    assert store.update_meta is legacy.update_meta
    assert store.generate_uuid is legacy.generate_uuid


def test_papers_legacy_module_aliases_store_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.stores.papers")
    store = importlib.import_module("scholaraio.stores.papers")

    assert legacy is store


def test_papers_implementation_lives_in_store_namespace() -> None:
    legacy = importlib.import_module("scholaraio.stores.papers")
    store = importlib.import_module("scholaraio.stores.papers")

    source = Path(inspect.getsourcefile(store.read_meta) or "")

    assert source.parts[-3:] == ("scholaraio", "stores", "papers.py")
    assert legacy.read_meta is store.read_meta


def test_toolref_store_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.stores.toolref")
    store = importlib.import_module("scholaraio.stores.toolref")

    assert store.TOOL_REGISTRY is legacy.TOOL_REGISTRY
    assert store.toolref_fetch is legacy.toolref_fetch
    assert store.toolref_list is legacy.toolref_list
    assert store.toolref_search is legacy.toolref_search
    assert store.toolref_show is legacy.toolref_show
    assert store.toolref_use is legacy.toolref_use


def test_toolref_legacy_package_aliases_store_package_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.stores.toolref")
    store = importlib.import_module("scholaraio.stores.toolref")

    assert legacy is store


def test_toolref_legacy_submodules_alias_store_submodules_for_patch_compatibility() -> None:
    for name in ("constants", "fetch", "indexing", "manifest", "paths", "search", "storage"):
        legacy = importlib.import_module(f"scholaraio.stores.toolref.{name}")
        store = importlib.import_module(f"scholaraio.stores.toolref.{name}")

        assert legacy is store


def test_webtools_provider_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.providers.webtools")
    provider = importlib.import_module("scholaraio.providers.webtools")

    assert provider.WebSearchResult is legacy.WebSearchResult
    assert provider.ServiceUnavailableError is legacy.ServiceUnavailableError
    assert provider.search_web is legacy.search_web
    assert provider.extract_web is legacy.extract_web
    assert provider.websearch is legacy.websearch
    assert provider.webextract is legacy.webextract
    assert provider.webextract_batch is legacy.webextract_batch


def test_webtools_legacy_module_aliases_provider_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.providers.webtools")
    provider = importlib.import_module("scholaraio.providers.webtools")

    assert legacy is provider


def test_arxiv_provider_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.providers.arxiv")
    provider = importlib.import_module("scholaraio.providers.arxiv")

    assert provider.ArxivError is legacy.ArxivError
    assert provider.ArxivRateLimitError is legacy.ArxivRateLimitError
    assert provider.ArxivPaper is legacy.ArxivPaper
    assert provider.normalize_arxiv_ref is legacy.normalize_arxiv_ref
    assert provider.search_arxiv is legacy.search_arxiv
    assert provider.search_and_display is legacy.search_and_display
    assert provider.get_arxiv_paper is legacy.get_arxiv_paper
    assert provider.get_paper_by_id is legacy.get_paper_by_id
    assert provider.download_arxiv_pdf is legacy.download_arxiv_pdf
    assert provider.batch_download is legacy.batch_download
    assert provider._SESSION is legacy._SESSION
    assert provider._query_arxiv_api is legacy._query_arxiv_api


def test_arxiv_legacy_module_aliases_provider_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.providers.arxiv")
    provider = importlib.import_module("scholaraio.providers.arxiv")

    assert legacy is provider


def test_arxiv_implementation_lives_in_provider_namespace() -> None:
    legacy = importlib.import_module("scholaraio.providers.arxiv")
    provider = importlib.import_module("scholaraio.providers.arxiv")

    source = Path(inspect.getsourcefile(provider.search_arxiv) or "")

    assert source.parts[-3:] == ("scholaraio", "providers", "arxiv.py")
    assert legacy.search_arxiv is provider.search_arxiv


def test_endnote_provider_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.providers.endnote")
    provider = importlib.import_module("scholaraio.providers.endnote")

    assert provider.parse_endnote is legacy.parse_endnote
    assert provider.parse_endnote_full is legacy.parse_endnote_full
    assert provider.extract_pdf_map is legacy.extract_pdf_map
    assert provider._load_endnote_core is legacy._load_endnote_core
    assert provider._record_to_meta is legacy._record_to_meta
    assert provider._resolve_pdf_candidates is legacy._resolve_pdf_candidates
    assert provider._pick_main_pdf is legacy._pick_main_pdf


def test_endnote_legacy_module_aliases_provider_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.providers.endnote")
    provider = importlib.import_module("scholaraio.providers.endnote")

    assert legacy is provider


def test_endnote_implementation_lives_in_provider_namespace() -> None:
    legacy = importlib.import_module("scholaraio.providers.endnote")
    provider = importlib.import_module("scholaraio.providers.endnote")

    source = Path(inspect.getsourcefile(provider.parse_endnote_full) or "")

    assert source.parts[-3:] == ("scholaraio", "providers", "endnote.py")
    assert legacy.parse_endnote_full is provider.parse_endnote_full


def test_zotero_provider_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.providers.zotero")
    provider = importlib.import_module("scholaraio.providers.zotero")

    assert provider.fetch_zotero_api is legacy.fetch_zotero_api
    assert provider.list_collections_api is legacy.list_collections_api
    assert provider.parse_zotero_local is legacy.parse_zotero_local
    assert provider.list_collections_local is legacy.list_collections_local
    assert provider._zotero_item_to_meta is legacy._zotero_item_to_meta
    assert provider._find_local_pdf is legacy._find_local_pdf
    assert provider._parse_zotero_date is legacy._parse_zotero_date
    assert provider._creators_to_authors is legacy._creators_to_authors


def test_zotero_legacy_module_aliases_provider_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.providers.zotero")
    provider = importlib.import_module("scholaraio.providers.zotero")

    assert legacy is provider


def test_zotero_implementation_lives_in_provider_namespace() -> None:
    legacy = importlib.import_module("scholaraio.providers.zotero")
    provider = importlib.import_module("scholaraio.providers.zotero")

    source = Path(inspect.getsourcefile(provider.parse_zotero_local) or "")

    assert source.parts[-3:] == ("scholaraio", "providers", "zotero.py")
    assert legacy.parse_zotero_local is provider.parse_zotero_local


def test_pdf_fallback_provider_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.providers.pdf_fallback")
    provider = importlib.import_module("scholaraio.providers.pdf_fallback")

    assert provider.convert_pdf_with_fallback is legacy.convert_pdf_with_fallback
    assert provider.resolve_parser_order is legacy.resolve_parser_order
    assert provider.preferred_parser_order is legacy.preferred_parser_order
    assert provider.prefers_fallback_parser is legacy.prefers_fallback_parser
    assert provider.detect_available_parsers is legacy.detect_available_parsers
    assert provider.run_pymupdf is legacy.run_pymupdf
    assert provider.pick_and_write_md is legacy.pick_and_write_md
    assert provider.copy_parser_assets is legacy.copy_parser_assets


def test_pdf_fallback_legacy_module_aliases_provider_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.providers.pdf_fallback")
    provider = importlib.import_module("scholaraio.providers.pdf_fallback")

    assert legacy is provider


def test_pdf_fallback_implementation_lives_in_provider_namespace() -> None:
    legacy = importlib.import_module("scholaraio.providers.pdf_fallback")
    provider = importlib.import_module("scholaraio.providers.pdf_fallback")

    source = Path(inspect.getsourcefile(provider.convert_pdf_with_fallback) or "")

    assert source.parts[-3:] == ("scholaraio", "providers", "pdf_fallback.py")
    assert legacy.convert_pdf_with_fallback is provider.convert_pdf_with_fallback


def test_mineru_provider_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.providers.mineru")
    provider = importlib.import_module("scholaraio.providers.mineru")

    assert provider.ConvertResult is legacy.ConvertResult
    assert provider.ConvertOptions is legacy.ConvertOptions
    assert provider.PDFValidationResult is legacy.PDFValidationResult
    assert provider.CloudInputAlias is legacy.CloudInputAlias
    assert provider.check_server is legacy.check_server
    assert provider.validate_pdf_for_mineru is legacy.validate_pdf_for_mineru
    assert provider.is_pdf_validation_error is legacy.is_pdf_validation_error
    assert provider.cloud_safe_input_path is legacy.cloud_safe_input_path
    assert provider.convert_pdf is legacy.convert_pdf
    assert provider.convert_pdf_cloud is legacy.convert_pdf_cloud
    assert provider.convert_pdfs_cloud_batch is legacy.convert_pdfs_cloud_batch
    assert provider.cmd_status is legacy.cmd_status
    assert provider.cmd_convert is legacy.cmd_convert
    assert provider.cmd_batch is legacy.cmd_batch
    assert provider.main is legacy.main


def test_mineru_legacy_module_aliases_provider_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.providers.mineru")
    provider = importlib.import_module("scholaraio.providers.mineru")

    assert legacy is provider


def test_mineru_implementation_lives_in_provider_namespace() -> None:
    legacy = importlib.import_module("scholaraio.providers.mineru")
    provider = importlib.import_module("scholaraio.providers.mineru")

    source = Path(inspect.getsourcefile(provider.convert_pdf) or "")

    assert source.parts[-3:] == ("scholaraio", "providers", "mineru.py")
    assert legacy.convert_pdf is provider.convert_pdf


def test_explore_store_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.stores.explore")
    store = importlib.import_module("scholaraio.stores.explore")

    assert store.fetch_explore is legacy.fetch_explore
    assert store.list_explore_libs is legacy.list_explore_libs
    assert store.explore_search is legacy.explore_search
    assert store.explore_unified_search is legacy.explore_unified_search
    assert store.explore_db_path is legacy.explore_db_path


def test_explore_legacy_module_aliases_store_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.stores.explore")
    store = importlib.import_module("scholaraio.stores.explore")

    assert legacy is store


def test_workspace_project_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.projects.workspace")
    project = importlib.import_module("scholaraio.projects.workspace")

    assert project.create is legacy.create
    assert project.add is legacy.add
    assert project.remove is legacy.remove
    assert project.read_paper_ids is legacy.read_paper_ids
    assert project.list_workspaces is legacy.list_workspaces


def test_workspace_legacy_module_aliases_project_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.projects.workspace")
    project = importlib.import_module("scholaraio.projects.workspace")

    assert legacy is project


def test_translate_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.translate")
    service = importlib.import_module("scholaraio.services.translate")

    assert service.TranslateResult is legacy.TranslateResult
    assert service.translate_paper is legacy.translate_paper
    assert service.batch_translate is legacy.batch_translate
    assert service.validate_lang is legacy.validate_lang
    assert service.detect_language is legacy.detect_language
    assert service.SKIP_ALL_CHUNKS_FAILED == legacy.SKIP_ALL_CHUNKS_FAILED


def test_translate_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.translate")
    service = importlib.import_module("scholaraio.services.translate")

    assert legacy is service


def test_insights_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.insights")
    service = importlib.import_module("scholaraio.services.insights")

    assert service.extract_hot_keywords is legacy.extract_hot_keywords
    assert service.aggregate_most_read_titles is legacy.aggregate_most_read_titles
    assert service.build_weekly_read_trend is legacy.build_weekly_read_trend
    assert service.recommend_unread_neighbors is legacy.recommend_unread_neighbors
    assert service.list_workspace_counts is legacy.list_workspace_counts


def test_insights_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.insights")
    service = importlib.import_module("scholaraio.services.insights")

    assert legacy is service


def test_metrics_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.metrics")
    service = importlib.import_module("scholaraio.services.metrics")

    assert service.LLMResult is legacy.LLMResult
    assert service.MetricsStore is legacy.MetricsStore
    assert service.TimerResult is legacy.TimerResult
    assert service.call_llm is legacy.call_llm
    assert service.timer is legacy.timer
    assert service.timed is legacy.timed
    assert service.get_store is legacy.get_store
    assert service.reset is legacy.reset


def test_metrics_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.metrics")
    service = importlib.import_module("scholaraio.services.metrics")

    assert legacy is service


def test_metrics_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.metrics")
    service = importlib.import_module("scholaraio.services.metrics")

    source = Path(inspect.getsourcefile(service.call_llm) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "metrics.py")
    assert legacy.call_llm is service.call_llm


def test_backup_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.backup")
    service = importlib.import_module("scholaraio.services.backup")

    assert service.BackupConfigError is legacy.BackupConfigError
    assert service.BackupRunResult is legacy.BackupRunResult
    assert service.build_rsync_command is legacy.build_rsync_command
    assert service.run_backup is legacy.run_backup


def test_backup_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.backup")
    service = importlib.import_module("scholaraio.services.backup")

    assert legacy is service


def test_backup_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.backup")
    service = importlib.import_module("scholaraio.services.backup")

    source = Path(inspect.getsourcefile(service.run_backup) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "backup.py")
    assert legacy.run_backup is service.run_backup


def test_document_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.document")
    service = importlib.import_module("scholaraio.services.document")

    assert service.inspect is legacy.inspect
    assert service.inspect_pptx is legacy.inspect_pptx
    assert service.inspect_docx is legacy.inspect_docx
    assert service.inspect_xlsx is legacy.inspect_xlsx


def test_document_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.document")
    service = importlib.import_module("scholaraio.services.document")

    assert legacy is service


def test_document_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.document")
    service = importlib.import_module("scholaraio.services.document")

    source = Path(inspect.getsourcefile(service.inspect) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "document.py")
    assert legacy.inspect is service.inspect


def test_diagram_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.diagram")
    service = importlib.import_module("scholaraio.services.diagram")

    assert service.extract_diagram_ir is legacy.extract_diagram_ir
    assert service.list_renderers is legacy.list_renderers
    assert service.render_ir is legacy.render_ir
    assert service.generate_diagram is legacy.generate_diagram
    assert service.generate_diagram_with_critic is legacy.generate_diagram_with_critic
    assert service.generate_diagram_from_text is legacy.generate_diagram_from_text


def test_diagram_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.diagram")
    service = importlib.import_module("scholaraio.services.diagram")

    assert legacy is service


def test_diagram_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.diagram")
    service = importlib.import_module("scholaraio.services.diagram")

    source = Path(inspect.getsourcefile(service.render_ir) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "diagram.py")
    assert legacy.render_ir is service.render_ir


def test_setup_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.setup")
    service = importlib.import_module("scholaraio.services.setup")

    assert service.CheckResult is legacy.CheckResult
    assert service.ParserChoice is legacy.ParserChoice
    assert service.check_dep_group is legacy.check_dep_group
    assert service.recommend_pdf_parser is legacy.recommend_pdf_parser
    assert service.run_check is legacy.run_check
    assert service.format_check_results is legacy.format_check_results
    assert service.run_wizard is legacy.run_wizard


def test_setup_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.setup")
    service = importlib.import_module("scholaraio.services.setup")

    assert legacy is service


def test_setup_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.setup")
    service = importlib.import_module("scholaraio.services.setup")

    source = Path(inspect.getsourcefile(service.run_check) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "setup.py")
    assert legacy.run_check is service.run_check


def test_migration_control_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.migration_control")
    service = importlib.import_module("scholaraio.services.migration_control")

    assert service.ensure_instance_metadata is legacy.ensure_instance_metadata
    assert service.read_instance_metadata is legacy.read_instance_metadata
    assert service.describe_migration_lock is legacy.describe_migration_lock
    assert service.run_migration_plan is legacy.run_migration_plan
    assert service.run_migration_verification is legacy.run_migration_verification
    assert service.run_migration_cleanup is legacy.run_migration_cleanup
    assert service.run_migration_store is legacy.run_migration_store
    assert service.SUPPORTED_MIGRATION_RUN_STORES is legacy.SUPPORTED_MIGRATION_RUN_STORES


def test_migration_control_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.migration_control")
    service = importlib.import_module("scholaraio.services.migration_control")

    assert legacy is service


def test_migration_control_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.migration_control")
    service = importlib.import_module("scholaraio.services.migration_control")

    source = Path(inspect.getsourcefile(service.run_migration_plan) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "migration_control.py")
    assert legacy.run_migration_plan is service.run_migration_plan


def test_loader_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.loader")
    service = importlib.import_module("scholaraio.services.loader")

    assert service.L3_SKIP_TYPES is legacy.L3_SKIP_TYPES
    assert service.load_l1 is legacy.load_l1
    assert service.load_l2 is legacy.load_l2
    assert service.load_l3 is legacy.load_l3
    assert service.load_l4 is legacy.load_l4
    assert service.load_notes is legacy.load_notes
    assert service.append_notes is legacy.append_notes
    assert service.enrich_toc is legacy.enrich_toc
    assert service.enrich_l3 is legacy.enrich_l3


def test_loader_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.loader")
    service = importlib.import_module("scholaraio.services.loader")

    assert legacy is service


def test_loader_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.loader")
    service = importlib.import_module("scholaraio.services.loader")

    source = Path(inspect.getsourcefile(service.load_l4) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "loader.py")
    assert legacy.load_l4 is service.load_l4


def test_index_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.index")
    service = importlib.import_module("scholaraio.services.index")

    assert service.UnifiedSearchDiagnostics is legacy.UnifiedSearchDiagnostics
    assert service.build_index is legacy.build_index
    assert service.build_proceedings_index is legacy.build_proceedings_index
    assert service.search is legacy.search
    assert service.search_proceedings is legacy.search_proceedings
    assert service.search_author is legacy.search_author
    assert service.top_cited is legacy.top_cited
    assert service.lookup_paper is legacy.lookup_paper
    assert service.unified_search is legacy.unified_search
    assert service.get_references is legacy.get_references
    assert service.get_citing_papers is legacy.get_citing_papers
    assert service.get_shared_references is legacy.get_shared_references


def test_index_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.index")
    service = importlib.import_module("scholaraio.services.index")

    assert legacy is service


def test_index_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.index")
    service = importlib.import_module("scholaraio.services.index")

    source = Path(inspect.getsourcefile(service.build_index) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "index.py")
    assert legacy.build_index is service.build_index


def test_vectors_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.vectors")
    service = importlib.import_module("scholaraio.services.vectors")

    assert service.QwenEmbedder is legacy.QwenEmbedder
    assert service.build_vectors is legacy.build_vectors
    assert service.vsearch is legacy.vsearch
    assert service._embed_provider is legacy._embed_provider
    assert service._embed_signature is legacy._embed_signature
    assert service._embed_query_vector is legacy._embed_query_vector
    assert service._ensure_vector_search_ready is legacy._ensure_vector_search_ready
    assert service._build_faiss_from_db is legacy._build_faiss_from_db
    assert service._vsearch_faiss is legacy._vsearch_faiss
    assert service._pack is legacy._pack
    assert service._unpack is legacy._unpack
    assert service._model_cache is legacy._model_cache


def test_vectors_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.vectors")
    service = importlib.import_module("scholaraio.services.vectors")

    assert legacy is service


def test_vectors_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.vectors")
    service = importlib.import_module("scholaraio.services.vectors")

    source = Path(inspect.getsourcefile(service.build_vectors) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "vectors.py")
    assert legacy.build_vectors is service.build_vectors


def test_topics_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.topics")
    service = importlib.import_module("scholaraio.services.topics")

    assert service.build_topics is legacy.build_topics
    assert service.get_topic_overview is legacy.get_topic_overview
    assert service.get_topic_papers is legacy.get_topic_papers
    assert service.get_outliers is legacy.get_outliers
    assert service.find_related_topics is legacy.find_related_topics
    assert service.visualize_topic_hierarchy is legacy.visualize_topic_hierarchy
    assert service.visualize_topics_2d is legacy.visualize_topics_2d
    assert service.visualize_barchart is legacy.visualize_barchart
    assert service.visualize_heatmap is legacy.visualize_heatmap
    assert service.visualize_term_rank is legacy.visualize_term_rank
    assert service.visualize_topics_over_time is legacy.visualize_topics_over_time
    assert service.reduce_topics_to is legacy.reduce_topics_to
    assert service.merge_topics_by_ids is legacy.merge_topics_by_ids
    assert service.load_model is legacy.load_model


def test_topics_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.topics")
    service = importlib.import_module("scholaraio.services.topics")

    assert legacy is service


def test_topics_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.topics")
    service = importlib.import_module("scholaraio.services.topics")

    source = Path(inspect.getsourcefile(service.build_topics) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "topics.py")
    assert legacy.build_topics is service.build_topics


def test_citation_check_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.citation_check")
    service = importlib.import_module("scholaraio.services.citation_check")

    assert service.extract_citations is legacy.extract_citations
    assert service.check_citations is legacy.check_citations


def test_citation_check_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.citation_check")
    service = importlib.import_module("scholaraio.services.citation_check")

    assert legacy is service


def test_citation_check_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.citation_check")
    service = importlib.import_module("scholaraio.services.citation_check")

    source = Path(inspect.getsourcefile(service.check_citations) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "citation_check.py")
    assert legacy.check_citations is service.check_citations


def test_audit_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.audit")
    service = importlib.import_module("scholaraio.services.audit")

    assert service.Issue is legacy.Issue
    assert service.audit_papers is legacy.audit_papers
    assert service.format_report is legacy.format_report
    assert service.list_scrub_suspects is legacy.list_scrub_suspects


def test_audit_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.audit")
    service = importlib.import_module("scholaraio.services.audit")

    assert legacy is service


def test_audit_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.audit")
    service = importlib.import_module("scholaraio.services.audit")

    source = Path(inspect.getsourcefile(service.audit_papers) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "audit.py")
    assert legacy.audit_papers is service.audit_papers


def test_export_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.export")
    service = importlib.import_module("scholaraio.services.export")

    assert service.meta_to_bibtex is legacy.meta_to_bibtex
    assert service.export_bibtex is legacy.export_bibtex
    assert service.meta_to_ris is legacy.meta_to_ris
    assert service.export_ris is legacy.export_ris
    assert service.export_markdown_refs is legacy.export_markdown_refs
    assert service.export_docx is legacy.export_docx


def test_export_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.export")
    service = importlib.import_module("scholaraio.services.export")

    assert legacy is service


def test_export_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.export")
    service = importlib.import_module("scholaraio.services.export")

    source = Path(inspect.getsourcefile(service.export_bibtex) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "export.py")
    assert legacy.export_bibtex is service.export_bibtex


def test_patent_fetch_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.patent_fetch")
    service = importlib.import_module("scholaraio.services.patent_fetch")

    assert service.PatentFetchError is legacy.PatentFetchError
    assert service.extract_pdf_url is legacy.extract_pdf_url
    assert service.download_patent_pdf is legacy.download_patent_pdf


def test_patent_fetch_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.patent_fetch")
    service = importlib.import_module("scholaraio.services.patent_fetch")

    assert legacy is service


def test_patent_fetch_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.patent_fetch")
    service = importlib.import_module("scholaraio.services.patent_fetch")

    source = Path(inspect.getsourcefile(service.download_patent_pdf) or "")

    assert source.parts[-3:] == ("scholaraio", "services", "patent_fetch.py")
    assert legacy.download_patent_pdf is service.download_patent_pdf


def test_uspto_ppubs_provider_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.providers.uspto_ppubs")
    provider = importlib.import_module("scholaraio.providers.uspto_ppubs")

    assert provider.PpubsError is legacy.PpubsError
    assert provider.PpubsPatent is legacy.PpubsPatent
    assert provider.PpubsClient is legacy.PpubsClient
    assert provider._extract_patent is legacy._extract_patent
    assert provider.search_patents is legacy.search_patents


def test_uspto_ppubs_legacy_module_aliases_provider_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.providers.uspto_ppubs")
    provider = importlib.import_module("scholaraio.providers.uspto_ppubs")

    assert legacy is provider


def test_uspto_ppubs_implementation_lives_in_provider_namespace() -> None:
    legacy = importlib.import_module("scholaraio.providers.uspto_ppubs")
    provider = importlib.import_module("scholaraio.providers.uspto_ppubs")

    source = Path(inspect.getsourcefile(provider.search_patents) or "")

    assert source.parts[-3:] == ("scholaraio", "providers", "uspto_ppubs.py")
    assert legacy.search_patents is provider.search_patents


def test_uspto_odp_provider_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.providers.uspto_odp")
    provider = importlib.import_module("scholaraio.providers.uspto_odp")

    assert provider.USPTOAPIError is legacy.USPTOAPIError
    assert provider.PatentResult is legacy.PatentResult
    assert provider._clean_publication_number is legacy._clean_publication_number
    assert provider._extract_patent_result is legacy._extract_patent_result
    assert provider.search_patents is legacy.search_patents
    assert provider.get_patent_by_application_number is legacy.get_patent_by_application_number


def test_uspto_odp_legacy_module_aliases_provider_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.providers.uspto_odp")
    provider = importlib.import_module("scholaraio.providers.uspto_odp")

    assert legacy is provider


def test_uspto_odp_implementation_lives_in_provider_namespace() -> None:
    legacy = importlib.import_module("scholaraio.providers.uspto_odp")
    provider = importlib.import_module("scholaraio.providers.uspto_odp")

    source = Path(inspect.getsourcefile(provider.search_patents) or "")

    assert source.parts[-3:] == ("scholaraio", "providers", "uspto_odp.py")
    assert legacy.search_patents is provider.search_patents


def test_proceedings_store_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.stores.proceedings")
    store = importlib.import_module("scholaraio.stores.proceedings")

    assert store.read_json is legacy.read_json
    assert store.proceedings_db_path is legacy.proceedings_db_path
    assert store.iter_proceedings_dirs is legacy.iter_proceedings_dirs
    assert store.iter_proceedings_papers is legacy.iter_proceedings_papers


def test_proceedings_legacy_module_aliases_store_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.stores.proceedings")
    store = importlib.import_module("scholaraio.stores.proceedings")

    assert legacy is store


def test_proceedings_implementation_lives_in_store_namespace() -> None:
    legacy = importlib.import_module("scholaraio.stores.proceedings")
    store = importlib.import_module("scholaraio.stores.proceedings")

    source = Path(inspect.getsourcefile(store.iter_proceedings_papers) or "")

    assert source.parts[-3:] == ("scholaraio", "stores", "proceedings.py")
    assert legacy.iter_proceedings_papers is store.iter_proceedings_papers


def test_log_core_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.core.log")
    core = importlib.import_module("scholaraio.core.log")

    assert core.setup is legacy.setup
    assert core.get_session_id is legacy.get_session_id
    assert core.get_logger is legacy.get_logger
    assert core.ui is legacy.ui
    assert core.redirect_console_ui is legacy.redirect_console_ui
    assert core.reset is legacy.reset


def test_log_legacy_module_aliases_core_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.core.log")
    core = importlib.import_module("scholaraio.core.log")

    assert legacy is core


def test_log_implementation_lives_in_core_namespace() -> None:
    legacy = importlib.import_module("scholaraio.core.log")
    core = importlib.import_module("scholaraio.core.log")

    source = Path(inspect.getsourcefile(core.setup) or "")

    assert source.parts[-3:] == ("scholaraio", "core", "log.py")
    assert legacy.setup is core.setup


def test_cli_runtime_entrypoint_lives_in_interface_namespace() -> None:
    from scholaraio import cli

    runtime = importlib.import_module("scholaraio.interfaces.cli.runtime")

    assert cli.main is runtime.main


def _assert_compat_binding(binding_name: str, module_name: str, target_name: str | None = None) -> None:
    from scholaraio.interfaces.cli import compat as cli

    interface = importlib.import_module(module_name)
    target = getattr(interface, target_name or binding_name)
    source = Path(inspect.getsourcefile(target) or "")

    assert getattr(cli, binding_name) is target
    assert source.parts[-4:] == ("scholaraio", "interfaces", "cli", f"{module_name.rsplit('.', 1)[-1]}.py")


def test_internal_cli_wiring_commands_live_in_interface_namespace() -> None:
    for binding_name, module_name in (
        ("cmd_insights", "scholaraio.interfaces.cli.insights"),
        ("cmd_metrics", "scholaraio.interfaces.cli.metrics"),
        ("cmd_translate", "scholaraio.interfaces.cli.translate"),
        ("cmd_backup", "scholaraio.interfaces.cli.backup"),
        ("cmd_style", "scholaraio.interfaces.cli.style"),
        ("cmd_document", "scholaraio.interfaces.cli.document"),
        ("cmd_export", "scholaraio.interfaces.cli.export"),
        ("cmd_diagram", "scholaraio.interfaces.cli.diagram"),
        ("cmd_setup", "scholaraio.interfaces.cli.setup"),
        ("cmd_index", "scholaraio.interfaces.cli.index"),
        ("cmd_search", "scholaraio.interfaces.cli.search"),
        ("cmd_search_author", "scholaraio.interfaces.cli.search"),
        ("cmd_top_cited", "scholaraio.interfaces.cli.citations"),
        ("cmd_rename", "scholaraio.interfaces.cli.rename"),
        ("cmd_audit", "scholaraio.interfaces.cli.audit"),
        ("cmd_refs", "scholaraio.interfaces.cli.graph"),
        ("cmd_citing", "scholaraio.interfaces.cli.graph"),
        ("cmd_shared_refs", "scholaraio.interfaces.cli.graph"),
        ("cmd_toolref", "scholaraio.interfaces.cli.toolref"),
        ("cmd_show", "scholaraio.interfaces.cli.show"),
        ("cmd_citation_check", "scholaraio.interfaces.cli.citation_check"),
        ("cmd_migrate", "scholaraio.interfaces.cli.migrate"),
        ("cmd_proceedings", "scholaraio.interfaces.cli.proceedings"),
        ("cmd_import_endnote", "scholaraio.interfaces.cli.import_endnote"),
        ("cmd_import_zotero", "scholaraio.interfaces.cli.import_zotero"),
        ("cmd_fsearch", "scholaraio.interfaces.cli.fsearch"),
        ("cmd_ws", "scholaraio.interfaces.cli.workspace"),
        ("cmd_embed", "scholaraio.interfaces.cli.retrieval"),
        ("cmd_vsearch", "scholaraio.interfaces.cli.retrieval"),
        ("cmd_usearch", "scholaraio.interfaces.cli.retrieval"),
        ("cmd_repair", "scholaraio.interfaces.cli.repair"),
        ("cmd_pipeline", "scholaraio.interfaces.cli.pipeline"),
        ("cmd_backfill_abstract", "scholaraio.interfaces.cli.backfill_abstract"),
        ("cmd_topics", "scholaraio.interfaces.cli.topics"),
        ("cmd_refetch", "scholaraio.interfaces.cli.refetch"),
        ("cmd_enrich_toc", "scholaraio.interfaces.cli.enrich"),
        ("cmd_enrich_l3", "scholaraio.interfaces.cli.enrich"),
        ("cmd_arxiv_search", "scholaraio.interfaces.cli.arxiv"),
        ("cmd_arxiv_fetch", "scholaraio.interfaces.cli.arxiv"),
        ("cmd_websearch", "scholaraio.interfaces.cli.web"),
        ("cmd_webextract", "scholaraio.interfaces.cli.web"),
        ("cmd_paper2any", "scholaraio.interfaces.cli.paper2any"),
        ("cmd_explore", "scholaraio.interfaces.cli.explore"),
        ("cmd_ingest_link", "scholaraio.interfaces.cli.ingest_link"),
        ("cmd_publish_site", "scholaraio.interfaces.cli.publish"),
        ("cmd_patent_fetch", "scholaraio.interfaces.cli.patent"),
        ("cmd_patent_search", "scholaraio.interfaces.cli.patent"),
        ("cmd_attach_pdf", "scholaraio.interfaces.cli.attach_pdf"),
    ):
        _assert_compat_binding(binding_name, module_name)


def test_internal_cli_wiring_helper_aliases_live_in_interface_namespace() -> None:
    for binding_name, module_name in (
        ("_cmd_export_bibtex", "scholaraio.interfaces.cli.export"),
        ("_cmd_export_ris", "scholaraio.interfaces.cli.export"),
        ("_cmd_export_markdown", "scholaraio.interfaces.cli.export"),
        ("_cmd_export_docx", "scholaraio.interfaces.cli.export"),
        ("_build_diagram_out_path", "scholaraio.interfaces.cli.diagram"),
        ("_print_diagram_hint", "scholaraio.interfaces.cli.diagram"),
        ("_import_zotero_collections_as_workspaces", "scholaraio.interfaces.cli.import_zotero"),
        ("_search_arxiv", "scholaraio.interfaces.cli.fsearch"),
        ("_query_dois_for_set", "scholaraio.interfaces.cli.fsearch"),
        ("_query_arxiv_ids_for_set", "scholaraio.interfaces.cli.fsearch"),
        ("_write_all_viz", "scholaraio.interfaces.cli.topics"),
        ("_toc_success_message", "scholaraio.interfaces.cli.enrich"),
        ("_run_batch_enrich", "scholaraio.interfaces.cli.enrich"),
        ("_terminal_preview", "scholaraio.interfaces.cli.web"),
        ("_explore_root", "scholaraio.interfaces.cli.explore"),
        ("_slugify_ingest_link_title", "scholaraio.interfaces.cli.ingest_link"),
        ("_fallback_ingest_link_title", "scholaraio.interfaces.cli.ingest_link"),
        ("_render_ingest_link_markdown", "scholaraio.interfaces.cli.ingest_link"),
        ("_webextract_for_ingest_link", "scholaraio.interfaces.cli.ingest_link"),
        ("_batch_convert_pdfs", "scholaraio.interfaces.cli.attach_pdf"),
    ):
        _assert_compat_binding(binding_name, module_name)


def test_internal_cli_wiring_utility_aliases_live_in_interface_namespace() -> None:
    from scholaraio.interfaces.cli import compat as cli

    argument_bindings = (
        ("_ResultLimitAction", "scholaraio.interfaces.cli.arguments"),
        ("_add_result_limit_arg", "scholaraio.interfaces.cli.arguments"),
        ("_resolve_result_limit", "scholaraio.interfaces.cli.arguments"),
        ("_resolve_top", "scholaraio.interfaces.cli.arguments"),
        ("_add_filter_args", "scholaraio.interfaces.cli.arguments"),
        ("_print_search_result", "scholaraio.interfaces.cli.output"),
        ("_print_search_next_steps", "scholaraio.interfaces.cli.output"),
        ("_format_match_tag", "scholaraio.interfaces.cli.output"),
        ("_format_citations", "scholaraio.interfaces.cli.output"),
        ("_INSTALL_HINTS", "scholaraio.interfaces.cli.dependencies"),
        ("_check_import_error", "scholaraio.interfaces.cli.dependencies"),
        ("_resolve_ws_paper_ids", "scholaraio.interfaces.cli.paths"),
        ("_workspace_root", "scholaraio.interfaces.cli.paths"),
        ("_default_inbox_dir", "scholaraio.interfaces.cli.paths"),
        ("_default_docx_output_path", "scholaraio.interfaces.cli.paths"),
        ("_workspace_figures_dir", "scholaraio.interfaces.cli.paths"),
        ("_lookup_registry_by_candidates", "scholaraio.interfaces.cli.paper"),
        ("_resolve_paper", "scholaraio.interfaces.cli.paper"),
        ("_print_header", "scholaraio.interfaces.cli.paper"),
        ("_enrich_show_header", "scholaraio.interfaces.cli.paper"),
        ("_record_search_metrics", "scholaraio.interfaces.cli.search_metrics"),
        ("_build_parser", "scholaraio.interfaces.cli.parser"),
    )

    for binding_name, module_name in argument_bindings:
        module = importlib.import_module(module_name)
        assert getattr(cli, binding_name) is getattr(module, binding_name)


def test_ingest_metadata_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest_metadata")
    service = importlib.import_module("scholaraio.services.ingest_metadata")

    assert service.PaperMetadata is legacy.PaperMetadata
    assert service.extract_metadata_from_markdown is legacy.extract_metadata_from_markdown
    assert service.enrich_metadata is legacy.enrich_metadata
    assert service.write_metadata_json is legacy.write_metadata_json
    assert service.metadata_to_dict is legacy.metadata_to_dict
    assert service.refetch_metadata is legacy.refetch_metadata


def test_ingest_metadata_legacy_package_aliases_service_package_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest_metadata")
    service = importlib.import_module("scholaraio.services.ingest_metadata")

    assert legacy is service


def test_ingest_metadata_legacy_submodules_alias_service_submodules_for_patch_compatibility() -> None:
    for name in ("_abstract", "_api", "_cli", "_doc_extract", "_extract", "_models", "_writer"):
        legacy = importlib.import_module(f"scholaraio.services.ingest_metadata.{name}")
        service = importlib.import_module(f"scholaraio.services.ingest_metadata.{name}")

        assert legacy is service


def test_ingest_extractor_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest_metadata.extractor")
    service = importlib.import_module("scholaraio.services.ingest_metadata.extractor")

    assert service.MetadataExtractor is legacy.MetadataExtractor
    assert service.RegexExtractor is legacy.RegexExtractor
    assert service.LLMExtractor is legacy.LLMExtractor
    assert service.FallbackExtractor is legacy.FallbackExtractor
    assert service.RobustExtractor is legacy.RobustExtractor
    assert service.get_extractor is legacy.get_extractor
    assert service._extract_patent_number is legacy._extract_patent_number


def test_ingest_extractor_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest_metadata.extractor")
    service = importlib.import_module("scholaraio.services.ingest_metadata.extractor")

    assert legacy is service


def test_ingest_extractor_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest_metadata.extractor")
    service = importlib.import_module("scholaraio.services.ingest_metadata.extractor")

    source = Path(inspect.getsourcefile(service.get_extractor) or "")

    assert source.parts[-4:] == ("scholaraio", "services", "ingest_metadata", "extractor.py")
    assert legacy.get_extractor is service.get_extractor


def test_ingest_pipeline_paper_global_steps_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    steps = importlib.import_module("scholaraio.services.ingest.steps")

    assert pipeline.step_toc is steps.step_toc
    assert pipeline.step_l3 is steps.step_l3
    assert pipeline.step_translate is steps.step_translate
    assert pipeline.step_embed is steps.step_embed
    assert pipeline.step_index is steps.step_index
    assert pipeline.step_refetch is steps.step_refetch


def test_ingest_pipeline_batch_asset_helpers_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    batch_assets = importlib.import_module("scholaraio.services.ingest.batch_assets")

    assert pipeline._move_batch_images is batch_assets.move_batch_images
    assert pipeline._flatten_cloud_batch_output is batch_assets.flatten_cloud_batch_output


def test_ingest_pipeline_batch_postprocess_helper_lives_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    batch_postprocess = importlib.import_module("scholaraio.services.ingest.batch_postprocess")

    assert pipeline._postprocess_convert is batch_postprocess.postprocess_convert
    assert pipeline._batch_postprocess is batch_postprocess.batch_postprocess


def test_ingest_pipeline_batch_convert_lives_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    batch_convert = importlib.import_module("scholaraio.services.ingest.batch_convert")

    assert pipeline.batch_convert_pdfs is batch_convert.batch_convert_pdfs


def test_ingest_pipeline_external_import_lives_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    external_import = importlib.import_module("scholaraio.services.ingest.external_import")

    assert pipeline.import_external is external_import.import_external


def test_ingest_pipeline_office_step_lives_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    inbox_steps = importlib.import_module("scholaraio.services.ingest.inbox_steps")

    assert pipeline.step_mineru is inbox_steps.step_mineru
    assert pipeline.step_office_convert is inbox_steps.step_office_convert
    assert pipeline.step_extract_doc is inbox_steps.step_extract_doc
    assert pipeline.step_extract is inbox_steps.step_extract
    assert pipeline.step_dedup is inbox_steps.step_dedup
    assert pipeline.step_ingest is inbox_steps.step_ingest


def test_ingest_pipeline_process_inbox_lives_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    inbox_orchestration = importlib.import_module("scholaraio.services.ingest.inbox_orchestration")

    assert pipeline._process_inbox is inbox_orchestration.process_inbox


def test_ingest_pipeline_runner_lives_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    pipeline_runner = importlib.import_module("scholaraio.services.ingest.pipeline_runner")

    assert pipeline.run_pipeline is pipeline_runner.run_pipeline


def test_ingest_pipeline_step_registry_lives_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    step_registry = importlib.import_module("scholaraio.services.ingest.step_registry")

    assert pipeline.STEPS is step_registry.STEPS
    assert pipeline.PRESETS is step_registry.PRESETS
    assert pipeline._DOC_INBOX_STEPS is step_registry.DOC_INBOX_STEPS
    assert pipeline._OFFICE_EXTENSIONS is step_registry.OFFICE_EXTENSIONS


def test_ingest_pipeline_service_namespace_aliases_legacy_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest.pipeline")
    service = importlib.import_module("scholaraio.services.ingest.pipeline")

    assert legacy is service
    assert service.run_pipeline is legacy.run_pipeline
    assert service.import_external is legacy.import_external
    assert service.batch_convert_pdfs is legacy.batch_convert_pdfs


def test_ingest_pipeline_facade_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest.pipeline")
    service = importlib.import_module("scholaraio.services.ingest.pipeline")

    source = Path(service.__file__ or "")

    assert source.parts[-4:] == ("scholaraio", "services", "ingest", "pipeline.py")
    assert legacy is service


def test_ingest_pipeline_path_helpers_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    paths = importlib.import_module("scholaraio.services.ingest.paths")

    assert pipeline._cfg_dir is paths.cfg_dir
    assert pipeline._inbox_dir is paths.inbox_dir
    assert pipeline._doc_inbox_dir is paths.doc_inbox_dir
    assert pipeline._thesis_inbox_dir is paths.thesis_inbox_dir
    assert pipeline._patent_inbox_dir is paths.patent_inbox_dir
    assert pipeline._proceedings_inbox_dir is paths.proceedings_inbox_dir
    assert pipeline._pending_dir is paths.pending_dir
    assert pipeline._proceedings_dir is paths.proceedings_dir


def test_ingest_pipeline_types_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    types = importlib.import_module("scholaraio.services.ingest.types")

    assert pipeline.StepResult is types.StepResult
    assert pipeline.StepDef is types.StepDef
    assert pipeline.InboxCtx is types.InboxCtx


def test_ingest_pipeline_asset_helpers_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    assets = importlib.import_module("scholaraio.services.ingest.assets")

    assert pipeline._find_assets is assets.find_assets
    assert pipeline._asset_stem_candidates is assets.asset_stem_candidates
    assert pipeline._safe_pdf_artifact_stem_from_stem is assets.safe_pdf_artifact_stem_from_stem
    assert pipeline._path_is_dir is assets.path_is_dir
    assert pipeline._safe_glob is assets.safe_glob
    assert pipeline._strip_artifact_prefix is assets.strip_artifact_prefix
    assert pipeline._move_assets is assets.move_assets
    assert pipeline._cleanup_assets is assets.cleanup_assets


def test_ingest_pipeline_identifier_helpers_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    identifiers = importlib.import_module("scholaraio.services.ingest.identifiers")

    assert pipeline._collect_existing_ids is identifiers.collect_existing_ids
    assert pipeline._collect_existing_dois is identifiers.collect_existing_dois
    assert pipeline._normalize_arxiv_id is identifiers.normalize_arxiv_id


def test_ingest_pipeline_detection_helpers_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    detection = importlib.import_module("scholaraio.services.ingest.detection")

    assert pipeline._parse_detect_json is detection.parse_detect_json
    assert pipeline._detect_patent is detection.detect_patent
    assert pipeline._detect_thesis is detection.detect_thesis
    assert pipeline._detect_book is detection.detect_book


def test_ingest_pipeline_document_helpers_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    documents = importlib.import_module("scholaraio.services.ingest.documents")

    assert pipeline._load_doc_sidecar_metadata is documents.load_doc_sidecar_metadata
    assert pipeline._repair_abstract is documents.repair_abstract


def test_ingest_pipeline_registry_helpers_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    registry = importlib.import_module("scholaraio.services.ingest.registry")

    assert pipeline._registry_migrated is registry.registry_migrated
    assert pipeline._ensure_registry_schema is registry.ensure_registry_schema
    assert pipeline._update_registry is registry.update_registry


def test_ingest_pipeline_cleanup_helpers_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    cleanup = importlib.import_module("scholaraio.services.ingest.cleanup")

    assert pipeline._cleanup_inbox is cleanup.cleanup_inbox


def test_ingest_pipeline_pending_helpers_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    pending = importlib.import_module("scholaraio.services.ingest.pending")

    assert pipeline._move_to_pending is pending.move_to_pending


def test_ingest_pipeline_proceedings_helpers_live_in_service_namespace() -> None:
    pipeline = importlib.import_module("scholaraio.services.ingest.pipeline")
    proceedings = importlib.import_module("scholaraio.services.ingest.proceedings")

    assert pipeline._ingest_proceedings_ctx is proceedings.ingest_proceedings_ctx


def test_ingest_proceedings_volume_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest.proceedings_volume")
    service = importlib.import_module("scholaraio.services.ingest.proceedings_volume")

    assert service.build_proceedings_clean_candidates is legacy.build_proceedings_clean_candidates
    assert service.apply_proceedings_clean_plan is legacy.apply_proceedings_clean_plan
    assert service.apply_proceedings_split_plan is legacy.apply_proceedings_split_plan
    assert service.ingest_proceedings_markdown is legacy.ingest_proceedings_markdown


def test_ingest_proceedings_legacy_module_aliases_volume_service_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest.proceedings_volume")
    service = importlib.import_module("scholaraio.services.ingest.proceedings_volume")

    assert legacy is service


def test_ingest_proceedings_volume_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest.proceedings_volume")
    service = importlib.import_module("scholaraio.services.ingest.proceedings_volume")

    source = Path(inspect.getsourcefile(service.ingest_proceedings_markdown) or "")

    assert source.parts[-4:] == ("scholaraio", "services", "ingest", "proceedings_volume.py")
    assert legacy.ingest_proceedings_markdown is service.ingest_proceedings_markdown


def test_parser_matrix_benchmark_service_namespace_reexports_current_behavior() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest.parser_matrix_benchmark")
    service = importlib.import_module("scholaraio.services.ingest.parser_matrix_benchmark")

    assert service.RunConfig is legacy.RunConfig
    assert service.expand_run_configs is legacy.expand_run_configs
    assert service.run_benchmark is legacy.run_benchmark
    assert service.run_one is legacy.run_one
    assert service.summarize_results is legacy.summarize_results
    assert service.render_summary is legacy.render_summary


def test_parser_matrix_benchmark_legacy_module_aliases_service_module_for_patch_compatibility() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest.parser_matrix_benchmark")
    service = importlib.import_module("scholaraio.services.ingest.parser_matrix_benchmark")

    assert legacy is service


def test_parser_matrix_benchmark_implementation_lives_in_service_namespace() -> None:
    legacy = importlib.import_module("scholaraio.services.ingest.parser_matrix_benchmark")
    service = importlib.import_module("scholaraio.services.ingest.parser_matrix_benchmark")

    source = Path(inspect.getsourcefile(service.run_benchmark) or "")

    assert source.parts[-4:] == ("scholaraio", "services", "ingest", "parser_matrix_benchmark.py")
    assert legacy.run_benchmark is service.run_benchmark


def test_agent_and_skill_discovery_surfaces_remain_at_repository_root() -> None:
    for rel_path in (
        "AGENTS.md",
        "CLAUDE.md",
        "AGENTS_CN.md",
        ".claude/skills",
        ".agents/skills",
        ".qwen/QWEN.md",
        ".qwen/skills",
        "skills",
        "clawhub.yaml",
    ):
        assert (ROOT / rel_path).exists()
