"""CLI parser construction."""

from __future__ import annotations

import argparse

from scholaraio.interfaces.cli.arguments import _add_filter_args, _add_result_limit_arg


def _build_parser() -> argparse.ArgumentParser:
    from scholaraio.interfaces.cli import compat as cli_mod

    cmd_index = cli_mod.cmd_index
    cmd_search = cli_mod.cmd_search
    cmd_search_author = cli_mod.cmd_search_author
    cmd_show = cli_mod.cmd_show
    cmd_embed = cli_mod.cmd_embed
    cmd_vsearch = cli_mod.cmd_vsearch
    cmd_usearch = cli_mod.cmd_usearch
    cmd_citation_check = cli_mod.cmd_citation_check
    cmd_enrich_toc = cli_mod.cmd_enrich_toc
    cmd_enrich_l3 = cli_mod.cmd_enrich_l3
    cmd_pipeline = cli_mod.cmd_pipeline
    cmd_refetch = cli_mod.cmd_refetch
    cmd_top_cited = cli_mod.cmd_top_cited
    cmd_refs = cli_mod.cmd_refs
    cmd_citing = cli_mod.cmd_citing
    cmd_shared_refs = cli_mod.cmd_shared_refs
    cmd_topics = cli_mod.cmd_topics
    cmd_backfill_abstract = cli_mod.cmd_backfill_abstract
    cmd_rename = cli_mod.cmd_rename
    cmd_audit = cli_mod.cmd_audit
    cmd_repair = cli_mod.cmd_repair
    cmd_explore = cli_mod.cmd_explore
    cmd_ws = cli_mod.cmd_ws
    cmd_export = cli_mod.cmd_export
    cmd_diagram = cli_mod.cmd_diagram
    cmd_document = cli_mod.cmd_document
    cmd_fsearch = cli_mod.cmd_fsearch
    cmd_import_endnote = cli_mod.cmd_import_endnote
    cmd_import_zotero = cli_mod.cmd_import_zotero
    cmd_attach_pdf = cli_mod.cmd_attach_pdf
    cmd_fetch_pdf = cli_mod.cmd_fetch_pdf
    cmd_ingest_link = cli_mod.cmd_ingest_link
    cmd_arxiv_search = cli_mod.cmd_arxiv_search
    cmd_arxiv_fetch = cli_mod.cmd_arxiv_fetch
    cmd_patent_search = cli_mod.cmd_patent_search
    cmd_patent_fetch = cli_mod.cmd_patent_fetch
    cmd_proceedings = cli_mod.cmd_proceedings
    cmd_toolref = cli_mod.cmd_toolref
    cmd_style = cli_mod.cmd_style
    cmd_setup = cli_mod.cmd_setup
    cmd_insights = cli_mod.cmd_insights
    cmd_migrate = cli_mod.cmd_migrate
    cmd_translate = cli_mod.cmd_translate
    cmd_websearch = cli_mod.cmd_websearch
    cmd_webextract = cli_mod.cmd_webextract
    cmd_paper2any = cli_mod.cmd_paper2any
    cmd_backup = cli_mod.cmd_backup
    cmd_metrics = cli_mod.cmd_metrics
    cmd_publish_site = cli_mod.cmd_publish_site
    cmd_gui = cli_mod.cmd_gui

    parser = argparse.ArgumentParser(
        prog="scholaraio",
        description="Research terminal for AI coding agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- index ---
    p_index = sub.add_parser("index", help="Build the FTS5 search index")
    p_index.set_defaults(func=cmd_index)
    p_index.add_argument("--rebuild", action="store_true", help="Clear and rebuild the index")

    # --- search ---
    p_search = sub.add_parser("search", help="Keyword search")
    p_search.set_defaults(func=cmd_search)
    p_search.add_argument("query", nargs="+", help="Search terms")
    _add_result_limit_arg(p_search, "Return at most N results (default: config search.top_k)")
    _add_filter_args(p_search)

    # --- search-author ---
    p_sa = sub.add_parser("search-author", help="Search by author name")
    p_sa.set_defaults(func=cmd_search_author)
    p_sa.add_argument("query", nargs="+", help="Author name (fuzzy match)")
    _add_result_limit_arg(p_sa, "Return at most N results (default: config search.top_k)")
    _add_filter_args(p_sa)

    # --- show ---
    p_show = sub.add_parser("show", help="Show paper content")
    p_show.set_defaults(func=cmd_show)
    p_show.add_argument("paper_id", help="Paper ID (directory name / UUID / DOI)")
    p_show.add_argument(
        "--layer",
        type=int,
        default=2,
        choices=[1, 2, 3, 4],
        help="Content layer: 1=metadata, 2=abstract, 3=conclusion, 4=full text (default: 2)",
    )
    p_show.add_argument(
        "--lang", type=str, default=None, help="Load a translated version (for example zh); only applies to L4"
    )
    p_show.add_argument(
        "--append-notes",
        type=str,
        default=None,
        metavar="TEXT",
        help="Append text to paper notes.md (T2 notes reused across sessions)",
    )

    # --- embed ---
    p_embed = sub.add_parser("embed", help="Generate semantic vectors into index.db")
    p_embed.set_defaults(func=cmd_embed)
    p_embed.add_argument("--rebuild", action="store_true", help="Clear and rebuild vectors")

    # --- vsearch ---
    p_vsearch = sub.add_parser("vsearch", help="Semantic vector search")
    p_vsearch.set_defaults(func=cmd_vsearch)
    p_vsearch.add_argument("query", nargs="+", help="Search terms")
    _add_result_limit_arg(p_vsearch, "Return at most N results (default: config embed.top_k)")
    _add_filter_args(p_vsearch)

    # --- usearch (unified) ---
    p_usearch = sub.add_parser("usearch", help="Unified search (keyword + semantic vectors)")
    p_usearch.set_defaults(func=cmd_usearch)
    p_usearch.add_argument("query", nargs="+", help="Search terms")
    _add_result_limit_arg(p_usearch, "Return at most N results (default: config search.top_k)")
    _add_filter_args(p_usearch)

    # --- enrich-toc ---
    p_toc = sub.add_parser("enrich-toc", help="Extract paper TOC with the LLM and write it to JSON")
    p_toc.set_defaults(func=cmd_enrich_toc)
    p_toc.add_argument("paper_id", nargs="?", help="Paper ID (omit only with --all)")
    p_toc.add_argument("--all", action="store_true", help="Process all papers in papers_dir")
    p_toc.add_argument("--force", action="store_true", help="Force extraction even when data already exists")
    p_toc.add_argument("--inspect", action="store_true", help="Show extraction details")

    # --- pipeline ---
    p_pipe = sub.add_parser("pipeline", help="Composable ingest/enrichment pipeline")
    p_pipe.set_defaults(func=cmd_pipeline)
    p_pipe.add_argument(
        "preset",
        nargs="?",
        help="Preset name: full | ingest | enrich | reindex",
    )
    p_pipe.add_argument("--steps", help="Custom comma-separated step list, for example toc,l3,index")
    p_pipe.add_argument("--list", dest="list_steps", action="store_true", help="List all steps and presets")
    p_pipe.add_argument("--dry-run", action="store_true", help="Preview actions without writing files")
    p_pipe.add_argument("--no-api", action="store_true", help="Offline mode; skip external APIs")
    p_pipe.add_argument("--force", action="store_true", help="Force reprocessing for toc/l3")
    p_pipe.add_argument("--inspect", action="store_true", help="Show processing details")
    p_pipe.add_argument("--max-retries", type=int, default=2, help="Maximum l3 retry count (default: 2)")
    p_pipe.add_argument("--rebuild", action="store_true", help="Rebuild indexes in the index step")
    p_pipe.add_argument("--inbox", help="Inbox directory (default from config; fresh layout uses data/spool/inbox)")
    p_pipe.add_argument("--papers", help="Papers directory (default from config)")

    # --- refetch ---
    p_refetch = sub.add_parser("refetch", help="Refetch API metadata such as citation counts and references")
    p_refetch.set_defaults(func=cmd_refetch)
    p_refetch.add_argument("paper_id", nargs="?", help="Paper ID (directory name / UUID / DOI; omit only with --all)")
    p_refetch.add_argument("--all", action="store_true", help="Refetch all papers missing citation counts")
    p_refetch.add_argument(
        "--force", action="store_true", help="Force refetch even for papers that already have citation counts"
    )
    p_refetch.add_argument(
        "--references-only",
        "--refs-only",
        action="store_true",
        help="Only fetch missing references for DOI papers; in single-paper mode only references are updated",
    )
    p_refetch.add_argument("--jobs", "-j", type=int, default=5, help="Concurrency (default: 5)")

    # --- top-cited ---
    p_tc = sub.add_parser("top-cited", help="List papers sorted by citation count")
    p_tc.set_defaults(func=cmd_top_cited)
    _add_result_limit_arg(p_tc, "Return at most N results (default: config search.top_k)")
    _add_filter_args(p_tc)

    # --- refs ---
    p_refs = sub.add_parser("refs", help="Show a paper's reference list")
    p_refs.set_defaults(func=cmd_refs)
    p_refs.add_argument("paper_id", help="Paper ID (directory name / UUID / DOI)")
    p_refs.add_argument("--ws", type=str, default=None, help="Limit to a workspace")

    # --- citing ---
    p_citing = sub.add_parser("citing", help="Show local papers that cite this paper")
    p_citing.set_defaults(func=cmd_citing)
    p_citing.add_argument("paper_id", help="Paper ID (directory name / UUID / DOI)")
    p_citing.add_argument("--ws", type=str, default=None, help="Limit to a workspace")

    # --- shared-refs ---
    p_sr = sub.add_parser("shared-refs", help="Analyze shared references")
    p_sr.set_defaults(func=cmd_shared_refs)
    p_sr.add_argument("paper_ids", nargs="+", help="Paper IDs (at least 2)")
    p_sr.add_argument("--min", type=int, default=None, help="Minimum shared reference count (default: 2)")
    p_sr.add_argument("--ws", type=str, default=None, help="Limit to a workspace")

    # --- topics ---
    p_topics = sub.add_parser("topics", help="BERTopic topic modeling and exploration")
    p_topics.set_defaults(func=cmd_topics)
    p_topics.add_argument("--build", action="store_true", help="Build the topic model")
    p_topics.add_argument(
        "--rebuild", action="store_true", help="Remove the old topic model directory before rebuilding"
    )
    p_topics.add_argument(
        "--reduce", type=int, default=None, metavar="N", help="Quickly reduce topics to N without reclustering"
    )
    p_topics.add_argument(
        "--merge",
        type=str,
        default=None,
        metavar="IDS",
        help="Manually merge topics, for example 1,6,14+3,5 (groups separated by +)",
    )
    p_topics.add_argument(
        "--topic", type=int, default=None, metavar="ID", help="Show papers in a topic (-1 shows outliers)"
    )
    _add_result_limit_arg(p_topics, "Number of results")
    p_topics.add_argument("--min-topic-size", type=int, default=None, help="Minimum cluster size (overrides config)")
    p_topics.add_argument(
        "--nr-topics", type=int, default=None, help="Target topic count (overrides config; 0=auto, -1=no merge)"
    )
    p_topics.add_argument("--viz", action="store_true", help="Generate HTML visualizations (6 charts)")

    # --- backfill-abstract ---
    p_bf = sub.add_parser("backfill-abstract", help="Backfill missing abstracts, including official DOI sources")
    p_bf.set_defaults(func=cmd_backfill_abstract)
    p_bf.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    p_bf.add_argument(
        "--doi-fetch",
        action="store_true",
        help="Fetch official abstracts from publisher pages and overwrite existing abstracts",
    )

    # --- rename ---
    p_rename = sub.add_parser("rename", help="Rename paper directories from JSON metadata")
    p_rename.set_defaults(func=cmd_rename)
    p_rename.add_argument("paper_id", nargs="?", help="Paper ID (omit only with --all)")
    p_rename.add_argument("--all", action="store_true", help="Rename all papers with noncanonical directory names")
    p_rename.add_argument("--dry-run", action="store_true", help="Preview without renaming")

    # --- audit ---
    p_audit = sub.add_parser("audit", help="Audit stored paper metadata quality")
    p_audit.set_defaults(func=cmd_audit)
    p_audit.add_argument("--severity", choices=["error", "warning", "info"], help="Only show issues at this severity")

    # --- repair ---
    p_repair = sub.add_parser("repair", help="Repair paper metadata manually without parsing Markdown")
    p_repair.set_defaults(func=cmd_repair)
    p_repair.add_argument("paper_id", help="Paper ID (directory name / UUID / DOI)")
    p_repair.add_argument("--title", required=True, help="Correct paper title")
    p_repair.add_argument("--doi", default="", help="Known DOI to speed up API lookup")
    p_repair.add_argument("--author", default="", help="First author's full name")
    p_repair.add_argument("--year", type=int, default=None, help="Publication year")
    p_repair.add_argument("--no-api", action="store_true", help="Skip API lookup and use only provided data")
    p_repair.add_argument("--dry-run", action="store_true", help="Preview without modifying files")

    # --- explore ---
    p_explore = sub.add_parser(
        "explore", help="Multi-dimensional literature exploration with OpenAlex, embeddings, and topics"
    )
    p_explore.set_defaults(func=cmd_explore)
    p_explore_sub = p_explore.add_subparsers(dest="explore_action", required=True)

    p_ef = p_explore_sub.add_parser("fetch", help="Fetch papers from OpenAlex with multi-dimensional filters")
    p_ef.add_argument("--issn", default=None, help="Journal ISSN, for example 0022-1120")
    p_ef.add_argument("--concept", default=None, help="OpenAlex concept ID, for example C62520636")
    p_ef.add_argument("--topic-id", default=None, help="OpenAlex topic ID")
    p_ef.add_argument("--author", default=None, help="OpenAlex author ID")
    p_ef.add_argument("--institution", default=None, help="OpenAlex institution ID")
    p_ef.add_argument("--keyword", default=None, help="Title/abstract keyword search")
    p_ef.add_argument("--source-type", default=None, help="Source type (journal/conference/repository)")
    p_ef.add_argument("--oa-type", default=None, help="OpenAlex work type (article/review/etc.)")
    p_ef.add_argument("--min-citations", type=int, default=None, help="Minimum citation count")
    p_ef.add_argument("--name", help="Explore library name (derived from filters by default)")
    p_ef.add_argument("--year-range", help="Year filter, for example 2020-2025")
    p_ef.add_argument("--incremental", action="store_true", help="Append only new papers")
    p_ef.add_argument(
        "--limit", type=int, default=None, help="Maximum number of papers to fetch (unlimited when omitted)"
    )

    p_ee = p_explore_sub.add_parser("embed", help="Generate semantic vectors for an explore library")
    p_ee.add_argument("--name", required=True, help="Explore library name")
    p_ee.add_argument("--rebuild", action="store_true", help="Clear and rebuild vectors")

    p_et = p_explore_sub.add_parser("topics", help="Topic modeling for an explore library")
    p_et.add_argument("--name", required=True, help="Explore library name")
    p_et.add_argument("--build", action="store_true", help="Build the topic model")
    p_et.add_argument("--rebuild", action="store_true", help="Rebuild the topic model")
    p_et.add_argument("--topic", type=int, default=None, help="Show papers in a topic")
    _add_result_limit_arg(p_et, "Number of results")
    p_et.add_argument("--min-topic-size", type=int, default=None, help="Minimum cluster size (default: 30)")
    p_et.add_argument("--nr-topics", type=int, default=None, help="Target topic count (default: natural clustering)")

    p_es = p_explore_sub.add_parser("search", help="Search an explore library (semantic/keyword/unified)")
    p_es.add_argument("--name", required=True, help="Explore library name")
    p_es.add_argument("query", nargs="+", help="Query text")
    _add_result_limit_arg(p_es, "Number of results")
    p_es.add_argument(
        "--mode", choices=["semantic", "keyword", "unified"], default="semantic", help="Search mode (default: semantic)"
    )

    p_ev = p_explore_sub.add_parser("viz", help="Generate all HTML visualizations")
    p_ev.add_argument("--name", required=True, help="Explore library name")

    p_el = p_explore_sub.add_parser("list", help="List all explore libraries")

    p_ei = p_explore_sub.add_parser("info", help="Show explore library information")
    p_ei.add_argument("--name", default=None, help="Explore library name (omit to list all)")

    # --- export ---
    p_export = sub.add_parser("export", help="Export papers or documents (BibTeX / RIS / Markdown / DOCX)")
    p_export.set_defaults(func=cmd_export)
    p_export_sub = p_export.add_subparsers(dest="export_action", required=True)

    p_eb = p_export_sub.add_parser("bibtex", help="Export BibTeX for LaTeX citations")
    p_eb.add_argument("paper_ids", nargs="*", help="Paper directory names")
    p_eb.add_argument("--all", action="store_true", help="Export all papers")
    p_eb.add_argument("--year", type=str, default=None, help="Year filter: 2023 / 2020-2024")
    p_eb.add_argument("--journal", type=str, default=None, help="Journal name filter (fuzzy match)")
    p_eb.add_argument("-o", "--output", type=str, default=None, help="Output file path (omit to print to stdout)")

    p_er = p_export_sub.add_parser("ris", help="Export RIS for Zotero / Endnote / Mendeley")
    p_er.add_argument("paper_ids", nargs="*", help="Paper directory names")
    p_er.add_argument("--all", action="store_true", help="Export all papers")
    p_er.add_argument("--year", type=str, default=None, help="Year filter: 2023 / 2020-2024")
    p_er.add_argument("--journal", type=str, default=None, help="Journal name filter (fuzzy match)")
    p_er.add_argument("-o", "--output", type=str, default=None, help="Output file path (omit to print to stdout)")

    p_em = p_export_sub.add_parser("markdown", help="Export a Markdown bibliography")
    p_em.add_argument("paper_ids", nargs="*", help="Paper directory names")
    p_em.add_argument("--all", action="store_true", help="Export all papers")
    p_em.add_argument("--year", type=str, default=None, help="Year filter: 2023 / 2020-2024")
    p_em.add_argument("--journal", type=str, default=None, help="Journal name filter (fuzzy match)")
    p_em.add_argument("--bullet", action="store_true", help="Use an unordered list instead of the default ordered list")
    p_em.add_argument(
        "--style",
        type=str,
        default="apa",
        help="Citation style: apa (default) / vancouver / chicago-author-date / mla / <custom>",
    )
    p_em.add_argument("-o", "--output", type=str, default=None, help="Output file path (omit to print to stdout)")

    p_ed = p_export_sub.add_parser("docx", help="Export Markdown text as a Word DOCX file")
    p_ed.add_argument(
        "--input", "-i", type=str, default=None, help="Input Markdown file path (omit to read from stdin)"
    )
    p_ed.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output .docx path (default: workspace_docx_output_path, usually <workspace>/_system/output/output.docx)",
    )
    p_ed.add_argument("--title", type=str, default=None, help="Optional document title inserted as a level-1 heading")

    # --- ws (workspace) ---
    p_ws = sub.add_parser("ws", help="Manage workspace paper subsets")
    p_ws.set_defaults(func=cmd_ws)
    p_ws_sub = p_ws.add_subparsers(dest="ws_action", required=True)

    p_ws_init = p_ws_sub.add_parser("init", help="Initialize a workspace")
    p_ws_init.add_argument("name", help="Workspace name (subdirectory under workspace/)")

    p_ws_add = p_ws_sub.add_parser("add", help="Add papers to a workspace")
    p_ws_add.add_argument("name", help="Workspace name")
    p_ws_add.add_argument("paper_refs", nargs="*", help="Paper references (UUID / directory name / DOI)")
    p_ws_add_batch = p_ws_add.add_mutually_exclusive_group()
    p_ws_add_batch.add_argument(
        "--search", dest="add_search", type=str, default=None, help="Add papers from search results"
    )
    p_ws_add_batch.add_argument("--topic", dest="add_topic", type=int, default=None, help="Add papers from a topic ID")
    p_ws_add_batch.add_argument(
        "--all", dest="add_all", action="store_true", default=False, help="Add all papers in the library"
    )
    _add_result_limit_arg(p_ws_add, "Limit --search result count")
    _add_filter_args(p_ws_add)

    p_ws_rm = p_ws_sub.add_parser("remove", help="Remove papers from a workspace")
    p_ws_rm.add_argument("name", help="Workspace name")
    p_ws_rm.add_argument("paper_refs", nargs="+", help="Paper references (UUID / directory name / DOI)")

    p_ws_list = p_ws_sub.add_parser("list", help="List all workspaces")

    p_ws_show = p_ws_sub.add_parser("show", help="Show papers in a workspace")
    p_ws_show.add_argument("name", help="Workspace name")

    p_ws_search = p_ws_sub.add_parser("search", help="Search within a workspace")
    p_ws_search.add_argument("name", help="Workspace name")
    p_ws_search.add_argument("query", nargs="+", help="Query text")
    _add_result_limit_arg(p_ws_search, "Number of results")
    p_ws_search.add_argument(
        "--mode", choices=["unified", "keyword", "semantic"], default="unified", help="Search mode (default: unified)"
    )
    _add_filter_args(p_ws_search)

    p_ws_rename = p_ws_sub.add_parser("rename", help="Rename a workspace")
    p_ws_rename.add_argument("old_name", help="Current workspace name")
    p_ws_rename.add_argument("new_name", help="New workspace name")

    p_ws_export = p_ws_sub.add_parser("export", help="Export workspace papers as BibTeX")
    p_ws_export.add_argument("name", help="Workspace name")
    p_ws_export.add_argument("-o", "--output", type=str, default=None, help="Output file path")
    _add_filter_args(p_ws_export)

    # --- import-endnote ---
    p_ie = sub.add_parser("import-endnote", help="Import paper metadata from Endnote XML/RIS")
    p_ie.set_defaults(func=cmd_import_endnote)
    p_ie.add_argument("files", nargs="+", help="Endnote export files (.xml or .ris)")
    p_ie.add_argument("--no-api", action="store_true", help="Skip API lookup and use only file metadata")
    p_ie.add_argument("--dry-run", action="store_true", help="Preview without importing")
    p_ie.add_argument("--no-convert", action="store_true", help="Skip PDF -> paper.md conversion")

    # --- import-zotero ---
    p_iz = sub.add_parser("import-zotero", help="Import paper metadata and PDFs from Zotero")
    p_iz.set_defaults(func=cmd_import_zotero)
    p_iz.add_argument("--local", metavar="SQLITE_PATH", help="Use a local zotero.sqlite database")
    p_iz.add_argument("--api-key", help="Zotero API key")
    p_iz.add_argument("--library-id", help="Zotero library ID")
    p_iz.add_argument("--library-type", choices=["user", "group"], help="Library type (default: user)")
    p_iz.add_argument("--collection", metavar="KEY", help="Only import a specific collection")
    p_iz.add_argument("--item-type", nargs="+", help="Limit item types, for example journalArticle conferencePaper")
    p_iz.add_argument("--list-collections", action="store_true", help="List all collections and exit")
    p_iz.add_argument("--no-pdf", action="store_true", help="Skip PDF download/copy")
    p_iz.add_argument("--no-api", action="store_true", help="Skip scholarly API lookup")
    p_iz.add_argument("--dry-run", action="store_true", help="Preview without importing")
    p_iz.add_argument("--no-convert", action="store_true", help="Skip PDF -> paper.md conversion")
    p_iz.add_argument("--import-collections", action="store_true", help="Create workspaces from Zotero collections")

    # --- attach-pdf ---
    p_ap = sub.add_parser("attach-pdf", help="Attach a PDF to an existing paper and generate paper.md")
    p_ap.set_defaults(func=cmd_attach_pdf)
    p_ap.add_argument("paper_id", help="Paper ID (directory name / UUID / DOI)")
    p_ap.add_argument("pdf_path", help="PDF file path")
    p_ap.add_argument("--dry-run", action="store_true", help="Preview planned actions without running them")
    p_ap.add_argument("--force", action="store_true", help="Replace an existing canonical PDF before conversion")

    # --- fetch-pdf ---
    p_pdf = sub.add_parser(
        "fetch-pdf",
        help="Download publisher PDFs through the current legal access context",
    )
    p_pdf.set_defaults(func=cmd_fetch_pdf)
    p_pdf.add_argument("locator", nargs="?", help="DOI, landing page URL, direct PDF URL, or title")
    p_pdf.add_argument("--paper", nargs="+", help="Refetch canonical PDFs for one or more existing papers")
    p_pdf.add_argument("--all", action="store_true", help="Refetch canonical PDFs for all library papers")
    p_pdf.add_argument(
        "--out-dir",
        help="Directory to keep a new downloaded PDF (default: configured inbox; --ingest stages temporarily)",
    )
    p_pdf.add_argument("--direct", action="store_true", help="Ignore proxy environment variables")
    p_pdf.add_argument("--force", action="store_true", help="Overwrite an existing PDF")
    p_pdf.add_argument("--ingest", action="store_true", help="Run the ingest pipeline after a new download")
    p_pdf.add_argument("--timeout", type=float, default=60.0, help="Network timeout in seconds (default: 60)")

    # --- citation-check ---
    p_cc = sub.add_parser("citation-check", help="Verify whether citations in text exist in the local library")
    p_cc.set_defaults(func=cmd_citation_check)
    p_cc.add_argument("file", nargs="?", default=None, help="File to check (omit to read from stdin)")
    p_cc.add_argument("--ws", type=str, default=None, help="Verify within a specific workspace")

    # --- migrate ---
    p_migrate = sub.add_parser(
        "migrate",
        help="Migration control panel (status / plan / run / verify / cleanup / finalize / upgrade / recover)",
    )
    p_migrate.set_defaults(func=cmd_migrate)
    p_migrate_sub = p_migrate.add_subparsers(dest="migrate_action", required=True)

    p_migrate_status = p_migrate_sub.add_parser("status", help="Show instance metadata and migration.lock status")
    p_migrate_status.set_defaults(func=cmd_migrate)

    p_migrate_plan = p_migrate_sub.add_parser("plan", help="Create a non-executing migration plan and write a journal")
    p_migrate_plan.add_argument("--migration-id", default=None, help="Journal ID; generated automatically by default")
    p_migrate_plan.set_defaults(func=cmd_migrate)

    p_migrate_recover = p_migrate_sub.add_parser("recover", help="Explicitly recover migration control state")
    p_migrate_recover.add_argument("--clear-lock", action="store_true", help="Explicitly clear migration.lock")
    p_migrate_recover.set_defaults(func=cmd_migrate)

    p_migrate_verify = p_migrate_sub.add_parser(
        "verify", help="Refresh verify.json and run minimal control-plane checks"
    )
    p_migrate_verify.add_argument("--migration-id", default=None, help="Journal ID; defaults to the latest journal")
    p_migrate_verify.set_defaults(func=cmd_migrate)

    p_migrate_cleanup = p_migrate_sub.add_parser("cleanup", help="Evaluate safe cleanup after verification passes")
    p_migrate_cleanup.add_argument("--migration-id", default=None, help="Journal ID; defaults to the latest journal")
    p_migrate_cleanup.add_argument(
        "--confirm",
        action="store_true",
        help="Explicitly confirm cleanup; this stage archives rather than deleting data",
    )
    p_migrate_cleanup.set_defaults(func=cmd_migrate)

    p_migrate_finalize = p_migrate_sub.add_parser(
        "finalize",
        help="Finalize migration with workspace index migration, cleanup, and verification",
    )
    p_migrate_finalize.add_argument(
        "--migration-id", default=None, help="Journal ID; generated automatically by default"
    )
    p_migrate_finalize.add_argument("--confirm", action="store_true", help="Confirm finalization")
    p_migrate_finalize.set_defaults(func=cmd_migrate)

    p_migrate_upgrade = p_migrate_sub.add_parser(
        "upgrade",
        help="Run the supported old-layout to fresh-layout migration, verification, and finalization",
    )
    p_migrate_upgrade.add_argument(
        "--migration-id", default=None, help="Journal ID; generated automatically by default"
    )
    p_migrate_upgrade.add_argument("--confirm", action="store_true", help="Confirm the full migration upgrade")
    p_migrate_upgrade.set_defaults(func=cmd_migrate)

    p_migrate_run = p_migrate_sub.add_parser("run", help="Run a supported explicit migration store")
    p_migrate_run.add_argument(
        "--store",
        required=True,
        choices=["citation_styles", "toolref", "explore", "proceedings", "spool", "papers", "workspace"],
        help="Store to migrate in this run",
    )
    p_migrate_run.add_argument("--migration-id", default=None, help="Journal ID; generated automatically by default")
    p_migrate_run.add_argument("--confirm", action="store_true", help="Confirm data copy into target directories")
    p_migrate_run.set_defaults(func=cmd_migrate)

    # --- setup ---
    p_setup = sub.add_parser(
        "setup",
        help="Environment diagnostics and setup wizard",
        description="Start the interactive setup wizard by default; use the `check` subcommand for diagnostics only.",
    )
    p_setup.set_defaults(func=cmd_setup)
    p_setup_sub = p_setup.add_subparsers(dest="setup_action")
    p_setup_check = p_setup_sub.add_parser("check", help="Check environment status")
    p_setup_check.add_argument(
        "--lang", choices=["en", "zh"], default="en", help="Output language (en or zh; default: en)"
    )

    # --- backup ---
    p_backup = sub.add_parser(
        "backup", help="Incremental backup with rsync", description="Incremental backup with rsync"
    )
    p_backup.set_defaults(func=cmd_backup)
    p_backup_sub = p_backup.add_subparsers(dest="backup_action", required=True)

    p_backup_list = p_backup_sub.add_parser("list", help="List configured backup targets")
    del p_backup_list  # no extra args needed

    p_backup_run = p_backup_sub.add_parser("run", help="Run a configured backup target")
    p_backup_run.add_argument("target", help="Backup target name from config backup.targets")
    p_backup_run.add_argument("--dry-run", action="store_true", help="Preview rsync actions without transferring files")

    # --- fsearch ---
    p_fsearch = sub.add_parser(
        "fsearch", help="Federated search across main library, proceedings, explore libraries, and arXiv"
    )
    p_fsearch.set_defaults(func=cmd_fsearch)
    p_fsearch.add_argument("query", nargs="+", help="Search terms")
    p_fsearch.add_argument(
        "--scope",
        type=str,
        default="main",
        help="Comma-separated scopes: main / proceedings / explore:NAME / explore:* / arxiv (default: main)",
    )
    _add_result_limit_arg(p_fsearch, "Return at most N results per source (default: 10)")

    # --- proceedings ---
    p_proc = sub.add_parser("proceedings", help="Proceedings helper commands such as apply-split")
    p_proc.set_defaults(func=cmd_proceedings)
    p_proc_sub = p_proc.add_subparsers(dest="proceedings_action", required=True)

    p_proc_apply = p_proc_sub.add_parser("apply-split", help="Apply split_plan.json to prepared proceedings")
    p_proc_apply.add_argument("proceeding_dir", help="Proceedings directory path")
    p_proc_apply.add_argument("split_plan", help="split_plan.json path")

    p_proc_clean_candidates = p_proc_sub.add_parser(
        "build-clean-candidates", help="Generate clean_candidates.json for split proceedings"
    )
    p_proc_clean_candidates.add_argument("proceeding_dir", help="Proceedings directory path")

    p_proc_apply_clean = p_proc_sub.add_parser("apply-clean", help="Apply clean_plan.json to split proceedings")
    p_proc_apply_clean.add_argument("proceeding_dir", help="Proceedings directory path")
    p_proc_apply_clean.add_argument("clean_plan", help="clean_plan.json path")

    # --- arxiv ---
    p_arxiv = sub.add_parser("arxiv", help="arXiv search and fetch tools")
    p_arxiv_sub = p_arxiv.add_subparsers(dest="arxiv_action", required=True)

    p_arxiv_search = p_arxiv_sub.add_parser("search", help="Search arXiv preprints")
    p_arxiv_search.set_defaults(func=cmd_arxiv_search)
    p_arxiv_search.add_argument("query", nargs="*", help="Search terms (may be omitted when using --category)")
    _add_result_limit_arg(p_arxiv_search, "Return at most N results (default: 10)")
    p_arxiv_search.add_argument("--category", type=str, default="", help="arXiv category, for example physics.flu-dyn")
    p_arxiv_search.add_argument(
        "--sort", choices=["relevance", "recent"], default="relevance", help="Sort order (default: relevance)"
    )

    p_arxiv_fetch = p_arxiv_sub.add_parser("fetch", help="Download an arXiv PDF, optionally ingesting it")
    p_arxiv_fetch.set_defaults(func=cmd_arxiv_fetch)
    p_arxiv_fetch.add_argument("arxiv_ref", help="arXiv ID, arXiv:ID, abs URL, or PDF URL")
    p_arxiv_fetch.add_argument("--ingest", action="store_true", help="Run the ingest pipeline after download")
    p_arxiv_fetch.add_argument(
        "--force", action="store_true", help="Overwrite existing PDF or force pipeline processing"
    )
    p_arxiv_fetch.add_argument("--dry-run", action="store_true", help="Preview planned actions")

    # --- websearch ---
    p_web = sub.add_parser("websearch", help="Real-time web search via GUILessBingSearch")
    p_web.set_defaults(func=cmd_websearch)
    p_web.add_argument("query", nargs="+", help="Search query terms")
    p_web.add_argument("--count", type=int, default=10, help="Number of results (default: 10)")

    # --- webextract ---
    p_wext = sub.add_parser("webextract", help="Extract web content with qt-web-extractor")
    p_wext.set_defaults(func=cmd_webextract)
    p_wext.add_argument("url", help="Web page URL to extract")
    p_wext.add_argument("--pdf", action="store_true", help="Treat the target as a PDF file")
    p_wext.add_argument("--full", action="store_true", help="Print the full extraction result without truncation")
    p_wext.add_argument("--max-chars", type=int, default=4000, help="Maximum preview characters (default: 4000)")

    # --- paper2any ---
    p_paper2any = sub.add_parser("paper2any", help="Paper2Any MCP sidecar integration")
    p_paper2any.set_defaults(func=cmd_paper2any)
    p_paper2any_sub = p_paper2any.add_subparsers(dest="paper2any_action", required=True)

    p_paper2any_setup = p_paper2any_sub.add_parser(
        "setup",
        help="Prepare the external Paper2Any runtime extension",
        description="Prepare the external Paper2Any runtime extension",
    )
    p_paper2any_setup.add_argument("--paper2any-root", default="", help="External OpenDCAI/Paper2Any checkout")
    p_paper2any_setup.add_argument(
        "--repo-url",
        default="https://github.com/OpenDCAI/Paper2Any.git",
        help="Upstream Paper2Any git URL",
    )
    p_paper2any_setup.add_argument("--ref", default="main", help="Upstream git branch, tag, or ref")
    p_paper2any_setup.add_argument("--update", action="store_true", help="Fetch and checkout the requested ref")
    p_paper2any_setup.add_argument(
        "--install-runtime",
        action="store_true",
        help="Install Paper2Any requirements into an isolated runtime venv",
    )
    p_paper2any_setup.add_argument("--python", default=None, help="Python executable used to create the runtime venv")
    p_paper2any_setup.add_argument("--dry-run", action="store_true", help="Show planned setup actions")

    p_paper2any_serve = p_paper2any_sub.add_parser(
        "mcp-serve",
        help="Start the lightweight Paper2Any MCP sidecar",
        description="Start the lightweight Paper2Any MCP sidecar",
    )
    p_paper2any_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_paper2any_serve.add_argument("--port", type=int, default=8770, help="Bind port (default: 8770)")
    p_paper2any_serve.add_argument("--paper2any-root", default="", help="External OpenDCAI/Paper2Any checkout")
    p_paper2any_serve.add_argument("--backend-url", default="", help="Running Paper2Any FastAPI backend URL")
    p_paper2any_serve.add_argument("--backend-api-key", default="", help="Paper2Any backend X-API-Key")
    p_paper2any_serve.add_argument("--bearer-token", default="", help="Optional MCP bearer token")
    p_paper2any_serve.add_argument("--timeout", type=int, default=120, help="Backend/CLI timeout in seconds")

    p_paper2any_backend = p_paper2any_sub.add_parser(
        "backend-serve",
        help="Start the real upstream Paper2Any FastAPI backend",
        description="Start the real upstream Paper2Any FastAPI backend",
    )
    p_paper2any_backend.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_paper2any_backend.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    p_paper2any_backend.add_argument("--paper2any-root", default="", help="External OpenDCAI/Paper2Any checkout")
    p_paper2any_backend.add_argument("--backend-api-key", default="", help="Paper2Any backend X-API-Key")
    p_paper2any_backend.add_argument("--python", default="", help="Python executable used to run uvicorn")

    p_paper2any_status = p_paper2any_sub.add_parser("status", help="Check the Paper2Any MCP sidecar")
    del p_paper2any_status

    p_paper2any_tools = p_paper2any_sub.add_parser("tools", help="List Paper2Any MCP tools")
    del p_paper2any_tools

    p_paper2any_call = p_paper2any_sub.add_parser(
        "call",
        help="Call a Paper2Any MCP tool",
        description="Call a Paper2Any MCP tool",
    )
    p_paper2any_call.add_argument("tool", help="MCP tool name, for example paper2any_capabilities")
    p_paper2any_call.add_argument(
        "--arguments-json",
        default="{}",
        help='Tool arguments as a JSON object (default: "{}")',
    )

    # --- ingest-link ---
    p_ingest_link = sub.add_parser(
        "ingest-link", help="Extract rendered web pages or online PDFs and ingest them as documents"
    )
    p_ingest_link.set_defaults(func=cmd_ingest_link)
    p_ingest_link.add_argument("urls", nargs="+", help="One or more web page or online PDF URLs")
    p_ingest_link.add_argument("--dry-run", action="store_true", help="Preview planned actions")
    p_ingest_link.add_argument("--force", action="store_true", help="Force reprocessing generated documents")
    p_ingest_link.add_argument(
        "--pdf", action="store_true", help="Hint webextract to use PDF mode when auto-detection is unreliable"
    )
    p_ingest_link.add_argument("--no-index", action="store_true", help="Ingest only; skip embed/index")
    p_ingest_link.add_argument("--json", action="store_true", help="Print extraction summary as JSON")

    # --- publish-site ---
    p_publish = sub.add_parser(
        "publish-site",
        help="Generate a static published-paper site",
        description="Generate a static published-paper site from published/*/metadata.json archives.",
    )
    p_publish.set_defaults(func=cmd_publish_site)
    p_publish.add_argument("--out-dir", default=None, help="Site output directory (default: publish.site_output_dir)")
    p_publish.add_argument("--symlink", action="store_true", help="Symlink assets for local preview instead of copying")

    # --- patent-fetch ---
    p_patent_fetch = sub.add_parser(
        "patent-fetch",
        help="Download patent PDFs into <patent inbox>",
        description="Download patent PDFs into <patent inbox>",
    )
    p_patent_fetch.set_defaults(func=cmd_patent_fetch)
    p_patent_fetch.add_argument(
        "id_or_url",
        help="Patent publication number, for example US20240176406A1, or a patent page URL",
    )

    # --- patent-search ---
    p_patent = sub.add_parser(
        "patent-search",
        help="USPTO patent search with PPUBS; no API key required",
        description="USPTO patent search with PPUBS; use --fetch to download PDFs into <patent inbox>",
    )
    p_patent.set_defaults(func=cmd_patent_search)
    p_patent.add_argument("query", nargs="*", help='Search query terms; PPUBS field syntax such as ("keyword").title.')
    p_patent.add_argument(
        "--application",
        "-a",
        type=str,
        default=None,
        help="Fetch details by application number, for example 17123456; requires --source odp",
    )
    p_patent.add_argument("--count", "-c", type=int, default=10, help="Number of results (default: 10)")
    p_patent.add_argument("--offset", "-o", type=int, default=0, help="Pagination offset (default: 0)")
    p_patent.add_argument(
        "--source",
        type=str,
        choices=["ppubs", "odp"],
        default="ppubs",
        help="Search source: ppubs (default, no API key) or odp (requires API key)",
    )
    p_patent.add_argument(
        "--fetch",
        "-f",
        action="store_true",
        help="Automatically download patent PDFs from all search results into <patent inbox>",
    )

    # --- insights ---
    p_insights = sub.add_parser(
        "insights", help="Research behavior analytics: hot search terms, most-read papers, and more"
    )
    p_insights.set_defaults(func=cmd_insights)
    p_insights.add_argument("--days", type=int, default=30, help="Analyze the last N days (default: 30)")

    # --- metrics ---
    p_metrics = sub.add_parser("metrics", help="Show LLM token usage and call statistics")
    p_metrics.set_defaults(func=cmd_metrics)
    p_metrics.add_argument("--last", type=int, default=20, help="Most recent N records")
    p_metrics.add_argument("--category", default="llm", help="Event category (llm/api/step; default: llm)")
    p_metrics.add_argument("--since", default=None, help="Start time in ISO format, for example 2026-03-01")
    p_metrics.add_argument("--summary", action="store_true", help="Only show aggregate statistics")

    # --- gui ---
    p_gui = sub.add_parser(
        "gui",
        help="Start the local read-only library WebUI",
        description="Start the local read-only library WebUI",
    )
    p_gui.set_defaults(func=cmd_gui)
    p_gui.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_gui.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    p_gui.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")

    # --- style ---
    p_style = sub.add_parser("style", help="Manage citation styles")
    p_style.set_defaults(func=cmd_style)
    p_style_sub = p_style.add_subparsers(dest="style_sub", required=True)

    p_style_list = p_style_sub.add_parser("list", help="List all available citation styles")
    del p_style_list  # no extra args needed

    p_style_show = p_style_sub.add_parser("show", help="Show citation-style formatter code")
    p_style_show.add_argument("name", help="Style name, for example jcp / apa / vancouver")

    # --- document ---
    p_doc = sub.add_parser("document", help="Office document tools such as inspect")
    p_doc.set_defaults(func=cmd_document)
    p_doc_sub = p_doc.add_subparsers(dest="doc_action", required=True)

    p_doc_inspect = p_doc_sub.add_parser("inspect", help="Inspect Office document structure (DOCX / PPTX / XLSX)")
    p_doc_inspect.add_argument("file", help="File path")
    p_doc_inspect.add_argument(
        "--format",
        choices=["docx", "pptx", "xlsx"],
        default=None,
        help="File format (inferred from extension by default)",
    )

    # --- diagram ---
    p_diagram = sub.add_parser("diagram", help="Convert a paper or text into editable scientific diagrams")
    p_diagram.set_defaults(func=cmd_diagram)
    p_diagram.add_argument(
        "paper_id",
        nargs="?",
        help="Paper ID (directory name / UUID / DOI); mutually exclusive with --from-ir/--from-text",
    )
    p_diagram.add_argument(
        "--type",
        choices=["model_arch", "tech_route", "exp_setup"],
        default="model_arch",
        help="Diagram type (default: model_arch)",
    )
    p_diagram.add_argument(
        "--format",
        choices=["svg", "drawio", "dot", "mermaid"],
        default="svg",
        help="Output format (default: svg)",
    )
    p_diagram.add_argument(
        "--dump-ir",
        action="store_true",
        help="Only extract and save IR JSON; do not render",
    )
    p_diagram.add_argument(
        "--from-ir",
        type=str,
        default=None,
        help="Render directly from an existing IR JSON file",
    )
    p_diagram.add_argument(
        "--from-text",
        type=str,
        default=None,
        help="Generate a diagram directly from text",
    )
    p_diagram.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output directory (default: workspace_figures_dir, usually <workspace>/_system/figures/)",
    )
    p_diagram.add_argument(
        "--critic",
        action="store_true",
        help="Enable Critic-Agent iterative self-review",
    )
    p_diagram.add_argument(
        "--critic-rounds",
        type=int,
        default=3,
        help="Maximum Critic iterations (default: 3; only used with --critic)",
    )

    # --- enrich-l3 ---
    p_l3 = sub.add_parser("enrich-l3", help="Extract conclusion sections with the LLM and write them to JSON")
    p_l3.set_defaults(func=cmd_enrich_l3)
    p_l3.add_argument("paper_id", nargs="?", help="Paper ID (omit only with --all)")
    p_l3.add_argument("--all", action="store_true", help="Process all papers in papers_dir")
    p_l3.add_argument("--force", action="store_true", help="Force extraction and overwrite existing results")
    p_l3.add_argument("--inspect", action="store_true", help="Show extraction details")
    p_l3.add_argument("--max-retries", type=int, default=2, help="Maximum retry count (default: 2)")

    # --- toolref ---
    p_tr = sub.add_parser("toolref", help="Scientific-computing tool reference lookup")
    p_tr.set_defaults(func=cmd_toolref)
    p_tr_sub = p_tr.add_subparsers(dest="toolref_action", required=True)

    p_trf = p_tr_sub.add_parser("fetch", help="Fetch tool documentation, extract it, and build the index")
    p_trf.add_argument("tool", help="Tool name (qe/lammps/gromacs/openfoam/bioinformatics)")
    p_trf.add_argument("--version", default=None, help="Version, for example 7.5 or 22Jul2025_update3")
    p_trf.add_argument("--force", action="store_true", help="Force refetch and overwrite local cache")

    p_trs = p_tr_sub.add_parser("show", help="Show documentation for a command or parameter")
    p_trs.add_argument("tool", help="Tool name")
    p_trs.add_argument("path", nargs="+", help="Lookup path, for example pw ecutwfc")

    p_trq = p_tr_sub.add_parser("search", help="Full-text search tool documentation")
    p_trq.add_argument("tool", help="Tool name")
    p_trq.add_argument("query", nargs="+", help="Search keywords")
    _add_result_limit_arg(p_trq, "Number of results (default: 20)")
    p_trq.add_argument("--program", default=None, help="Filter by program, for example pw.x")
    p_trq.add_argument("--section", default=None, help="Filter by namelist/section, for example SYSTEM")

    p_trl = p_tr_sub.add_parser("list", help="List fetched tool documentation and versions")
    p_trl.add_argument("tool", nargs="?", default=None, help="Tool name (omit to list all)")

    p_tru = p_tr_sub.add_parser("use", help="Switch the active documentation version for a tool")
    p_tru.add_argument("tool", help="Tool name")
    p_tru.add_argument("version", help="Target version")

    # --- translate ---
    p_trans = sub.add_parser("translate", help="Translate paper Markdown to a target language")
    p_trans.set_defaults(func=cmd_translate)
    p_trans.add_argument("paper_id", nargs="?", help="Paper ID (omit only with --all)")
    p_trans.add_argument("--all", action="store_true", help="Translate all papers")
    p_trans.add_argument(
        "--lang", type=str, default=None, help="Target language (default: config translate.target_lang)"
    )
    p_trans.add_argument("--force", action="store_true", help="Force retranslation and overwrite existing output")
    p_trans.add_argument(
        "--portable",
        action="store_true",
        help=(
            "Also export a portable translation bundle under translation_bundle_root "
            "(default: workspace/_system/translation-bundles/) and copy images"
        ),
    )

    return parser
