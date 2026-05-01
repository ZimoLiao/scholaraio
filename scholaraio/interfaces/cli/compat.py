"""Internal CLI wiring shared by parser/runtime/command modules.

This module is intentionally *not* a public compatibility facade. It simply
keeps CLI assembly in one place so ``scholaraio.cli`` can stay as a minimal
entrypoint while the command handlers continue sharing helpers.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time

from scholaraio.core.config import load_config
from scholaraio.core.log import ui
from scholaraio.interfaces.cli import arguments as _arguments_cli
from scholaraio.interfaces.cli import attach_pdf as _attach_pdf_cli
from scholaraio.interfaces.cli import dependencies as _dependencies_cli
from scholaraio.interfaces.cli import diagram as _diagram_cli
from scholaraio.interfaces.cli import enrich as _enrich_cli
from scholaraio.interfaces.cli import explore as _explore_cli
from scholaraio.interfaces.cli import export as _export_cli
from scholaraio.interfaces.cli import fsearch as _fsearch_cli
from scholaraio.interfaces.cli import import_zotero as _import_zotero_cli
from scholaraio.interfaces.cli import ingest_link as _ingest_link_cli
from scholaraio.interfaces.cli import output as _output_cli
from scholaraio.interfaces.cli import paper as _paper_cli
from scholaraio.interfaces.cli import paper2any as _paper2any_cli
from scholaraio.interfaces.cli import parser as _parser_cli
from scholaraio.interfaces.cli import paths as _paths_cli
from scholaraio.interfaces.cli import publish as _publish_cli
from scholaraio.interfaces.cli import runtime as _runtime_cli
from scholaraio.interfaces.cli import search_metrics as _search_metrics_cli
from scholaraio.interfaces.cli import topics as _topics_cli
from scholaraio.interfaces.cli import web as _web_cli
from scholaraio.interfaces.cli.arxiv import cmd_arxiv_fetch, cmd_arxiv_search
from scholaraio.interfaces.cli.audit import cmd_audit
from scholaraio.interfaces.cli.backfill_abstract import cmd_backfill_abstract
from scholaraio.interfaces.cli.backup import cmd_backup
from scholaraio.interfaces.cli.citation_check import cmd_citation_check
from scholaraio.interfaces.cli.citations import cmd_top_cited
from scholaraio.interfaces.cli.document import cmd_document
from scholaraio.interfaces.cli.graph import cmd_citing, cmd_refs, cmd_shared_refs
from scholaraio.interfaces.cli.import_endnote import cmd_import_endnote
from scholaraio.interfaces.cli.index import cmd_index
from scholaraio.interfaces.cli.insights import cmd_insights
from scholaraio.interfaces.cli.metrics import cmd_metrics
from scholaraio.interfaces.cli.migrate import cmd_migrate
from scholaraio.interfaces.cli.patent import cmd_patent_fetch, cmd_patent_search
from scholaraio.interfaces.cli.pipeline import cmd_pipeline
from scholaraio.interfaces.cli.proceedings import cmd_proceedings
from scholaraio.interfaces.cli.refetch import cmd_refetch
from scholaraio.interfaces.cli.rename import cmd_rename
from scholaraio.interfaces.cli.repair import cmd_repair
from scholaraio.interfaces.cli.retrieval import cmd_embed, cmd_usearch, cmd_vsearch
from scholaraio.interfaces.cli.search import cmd_search, cmd_search_author
from scholaraio.interfaces.cli.setup import cmd_setup
from scholaraio.interfaces.cli.show import cmd_show
from scholaraio.interfaces.cli.style import cmd_style
from scholaraio.interfaces.cli.toolref import cmd_toolref
from scholaraio.interfaces.cli.translate import cmd_translate
from scholaraio.interfaces.cli.workspace import cmd_ws

_log = logging.getLogger(__name__)
FUTURES = concurrent.futures
TIME = time

cmd_export = _export_cli.cmd_export
_cmd_export_bibtex = _export_cli._cmd_export_bibtex
_cmd_export_docx = _export_cli._cmd_export_docx
_cmd_export_markdown = _export_cli._cmd_export_markdown
_cmd_export_ris = _export_cli._cmd_export_ris
cmd_diagram = _diagram_cli.cmd_diagram
_build_diagram_out_path = _diagram_cli._build_diagram_out_path
_print_diagram_hint = _diagram_cli._print_diagram_hint
cmd_fsearch = _fsearch_cli.cmd_fsearch
_query_arxiv_ids_for_set = _fsearch_cli._query_arxiv_ids_for_set
_query_dois_for_set = _fsearch_cli._query_dois_for_set
_search_arxiv = _fsearch_cli._search_arxiv
cmd_import_zotero = _import_zotero_cli.cmd_import_zotero
_import_zotero_collections_as_workspaces = _import_zotero_cli._import_zotero_collections_as_workspaces
cmd_topics = _topics_cli.cmd_topics
_write_all_viz = _topics_cli._write_all_viz
cmd_enrich_toc = _enrich_cli.cmd_enrich_toc
cmd_enrich_l3 = _enrich_cli.cmd_enrich_l3
_toc_success_message = _enrich_cli._toc_success_message
_run_batch_enrich = _enrich_cli._run_batch_enrich
cmd_websearch = _web_cli.cmd_websearch
cmd_webextract = _web_cli.cmd_webextract
cmd_paper2any = _paper2any_cli.cmd_paper2any
_terminal_preview = _web_cli._terminal_preview
cmd_explore = _explore_cli.cmd_explore
_explore_root = _explore_cli._explore_root
cmd_ingest_link = _ingest_link_cli.cmd_ingest_link
cmd_publish_site = _publish_cli.cmd_publish_site
_slugify_ingest_link_title = _ingest_link_cli._slugify_ingest_link_title
_fallback_ingest_link_title = _ingest_link_cli._fallback_ingest_link_title
_render_ingest_link_markdown = _ingest_link_cli._render_ingest_link_markdown
_webextract_for_ingest_link = _ingest_link_cli._webextract_for_ingest_link
cmd_attach_pdf = _attach_pdf_cli.cmd_attach_pdf
_batch_convert_pdfs = _attach_pdf_cli._batch_convert_pdfs

_ResultLimitAction = _arguments_cli._ResultLimitAction
_add_result_limit_arg = _arguments_cli._add_result_limit_arg
_resolve_result_limit = _arguments_cli._resolve_result_limit
_resolve_top = _arguments_cli._resolve_top
_add_filter_args = _arguments_cli._add_filter_args
_print_search_result = _output_cli._print_search_result
_print_search_next_steps = _output_cli._print_search_next_steps
_format_match_tag = _output_cli._format_match_tag
_format_citations = _output_cli._format_citations
_INSTALL_HINTS = _dependencies_cli._INSTALL_HINTS
_check_import_error = _dependencies_cli._check_import_error
_resolve_ws_paper_ids = _paths_cli._resolve_ws_paper_ids
_workspace_root = _paths_cli._workspace_root
_default_docx_output_path = _paths_cli._default_docx_output_path
_workspace_figures_dir = _paths_cli._workspace_figures_dir
_default_inbox_dir = _paths_cli._default_inbox_dir
_lookup_registry_by_candidates = _paper_cli._lookup_registry_by_candidates
_resolve_paper = _paper_cli._resolve_paper
_print_header = _paper_cli._print_header
_enrich_show_header = _paper_cli._enrich_show_header
_record_search_metrics = _search_metrics_cli._record_search_metrics
_build_parser = _parser_cli._build_parser
main = _runtime_cli.main

__all__ = [
    "FUTURES",
    "TIME",
    "_INSTALL_HINTS",
    "_ResultLimitAction",
    "_add_filter_args",
    "_add_result_limit_arg",
    "_batch_convert_pdfs",
    "_build_diagram_out_path",
    "_build_parser",
    "_check_import_error",
    "_cmd_export_bibtex",
    "_cmd_export_docx",
    "_cmd_export_markdown",
    "_cmd_export_ris",
    "_default_docx_output_path",
    "_default_inbox_dir",
    "_enrich_show_header",
    "_explore_root",
    "_fallback_ingest_link_title",
    "_format_citations",
    "_format_match_tag",
    "_import_zotero_collections_as_workspaces",
    "_log",
    "_lookup_registry_by_candidates",
    "_print_diagram_hint",
    "_print_header",
    "_print_search_next_steps",
    "_print_search_result",
    "_query_arxiv_ids_for_set",
    "_query_dois_for_set",
    "_record_search_metrics",
    "_render_ingest_link_markdown",
    "_resolve_paper",
    "_resolve_result_limit",
    "_resolve_top",
    "_resolve_ws_paper_ids",
    "_run_batch_enrich",
    "_search_arxiv",
    "_slugify_ingest_link_title",
    "_terminal_preview",
    "_toc_success_message",
    "_webextract_for_ingest_link",
    "_workspace_figures_dir",
    "_workspace_root",
    "_write_all_viz",
    "cmd_arxiv_fetch",
    "cmd_arxiv_search",
    "cmd_attach_pdf",
    "cmd_audit",
    "cmd_backfill_abstract",
    "cmd_backup",
    "cmd_citation_check",
    "cmd_citing",
    "cmd_diagram",
    "cmd_document",
    "cmd_embed",
    "cmd_enrich_l3",
    "cmd_enrich_toc",
    "cmd_explore",
    "cmd_export",
    "cmd_fsearch",
    "cmd_import_endnote",
    "cmd_import_zotero",
    "cmd_index",
    "cmd_ingest_link",
    "cmd_insights",
    "cmd_metrics",
    "cmd_migrate",
    "cmd_paper2any",
    "cmd_patent_fetch",
    "cmd_patent_search",
    "cmd_pipeline",
    "cmd_proceedings",
    "cmd_publish_site",
    "cmd_refetch",
    "cmd_refs",
    "cmd_rename",
    "cmd_repair",
    "cmd_search",
    "cmd_search_author",
    "cmd_setup",
    "cmd_shared_refs",
    "cmd_show",
    "cmd_style",
    "cmd_toolref",
    "cmd_top_cited",
    "cmd_topics",
    "cmd_translate",
    "cmd_usearch",
    "cmd_vsearch",
    "cmd_webextract",
    "cmd_websearch",
    "cmd_ws",
    "load_config",
    "main",
    "ui",
]
