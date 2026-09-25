"""Ranked-search orchestration for the local library WebUI."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scholaraio.stores.library_state import library_records
from scholaraio.stores.papers import authors_text, normalize_paper_type

if TYPE_CHECKING:
    from scholaraio.core.config import Config

LIBRARY_SEARCH_MODES = frozenset({"keyword", "semantic", "unified"})
MAX_LIBRARY_SEARCH_RESULTS = 200
DEFAULT_LIBRARY_SEARCH_RESULTS = 100


class LibrarySearchRequestError(ValueError):
    """A stable, user-correctable WebUI search request error."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _parse_year(value: object, field: str) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise LibrarySearchRequestError(f"{field} must be a four-digit year", code="invalid_year")
    year = int(raw)
    if year < 1000 or year > 9999:
        raise LibrarySearchRequestError(f"{field} must be between 1000 and 9999", code="invalid_year")
    return year


@dataclass(frozen=True)
class LibrarySearchFilters:
    """Composable metadata filters applied before ranked retrieval."""

    title: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    journal: str = ""
    paper_type: str = ""
    doi: str = ""

    @classmethod
    def from_strings(
        cls,
        *,
        title: object = "",
        author: object = "",
        year_from: object = "",
        year_to: object = "",
        journal: object = "",
        paper_type: object = "",
        doi: object = "",
    ) -> LibrarySearchFilters:
        start = _parse_year(year_from, "year_from")
        end = _parse_year(year_to, "year_to")
        if start is not None and end is not None and start > end:
            raise LibrarySearchRequestError(
                "year_to must not be before year_from",
                code="invalid_year_range",
            )
        return cls(
            title=str(title or "").strip(),
            author=str(author or "").strip(),
            year_from=start,
            year_to=end,
            journal=str(journal or "").strip(),
            paper_type=str(paper_type or "").strip(),
            doi=str(doi or "").strip(),
        )

    @property
    def year_expression(self) -> str | None:
        if self.year_from is not None and self.year_to is not None:
            if self.year_from == self.year_to:
                return str(self.year_from)
            return f"{self.year_from}-{self.year_to}"
        if self.year_from is not None:
            return f"{self.year_from}-"
        if self.year_to is not None:
            return f"-{self.year_to}"
        return None


def _contains(value: object, needle: str) -> bool:
    return needle.casefold() in str(value or "").casefold()


def _safe_year(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _matches_filters(meta: dict, filters: LibrarySearchFilters) -> bool:
    if filters.title and not _contains(meta.get("title"), filters.title):
        return False
    if filters.author and not _contains(authors_text(meta.get("authors")), filters.author):
        return False
    if filters.journal and not _contains(meta.get("journal") or meta.get("source"), filters.journal):
        return False
    if filters.paper_type and normalize_paper_type(
        meta.get("paper_type"), meta.get("journal"), meta.get("doi")
    ) != normalize_paper_type(filters.paper_type):
        return False
    if filters.doi and not _contains(meta.get("doi"), filters.doi):
        return False
    if filters.year_from is not None or filters.year_to is not None:
        year = _safe_year(meta.get("year"))
        if year is None:
            return False
        if filters.year_from is not None and year < filters.year_from:
            return False
        if filters.year_to is not None and year > filters.year_to:
            return False
    return True


def _candidate_records(cfg: Config, filters: LibrarySearchFilters) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for directory, meta in library_records(cfg.papers_dir).items():
        paper_dir = cfg.papers_dir / directory
        if not _matches_filters(meta, filters):
            continue
        paper_id = str(meta.get("id") or paper_dir.name)
        records[paper_id] = {"dir_name": paper_dir.name, "meta": meta}
    return records


def _action(command: str, label: str) -> dict[str, str]:
    return {"command": command, "label": label}


def _diagnostics(
    *,
    status: str,
    message: str,
    keyword: str,
    semantic: str,
    actions: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "status": status,
        "message": message,
        "keyword": keyword,
        "semantic": semantic,
        "actions": actions or [],
    }


def _unavailable_diagnostics(mode: str) -> dict:
    if mode == "keyword":
        return _diagnostics(
            status="unavailable",
            message="Keyword search index is unavailable.",
            keyword="unavailable",
            semantic="not_used",
            actions=[_action("scholaraio index --rebuild", "Rebuild the keyword index")],
        )
    return _diagnostics(
        status="unavailable",
        message="Semantic search index or embedding provider is unavailable.",
        keyword="not_used",
        semantic="unavailable",
        actions=[_action("scholaraio embed", "Build semantic embeddings")],
    )


def _normalize_results(raw_results: list[dict], mode: str, candidates: dict[str, dict], limit: int) -> list[dict]:
    results: list[dict] = []
    match_names = {"fts": "keyword", "vec": "semantic", "both": "both"}
    for raw in raw_results:
        paper_id = str(raw.get("paper_id") or "")
        if not paper_id or paper_id not in candidates:
            continue
        rank = len(results) + 1
        raw_score = raw.get("score")
        try:
            score = float(raw_score) if raw_score is not None else 1.0 / rank
        except (TypeError, ValueError):
            score = 1.0 / rank
        candidate = candidates[paper_id]
        meta = candidate["meta"]
        raw_match = str(raw.get("match") or mode)
        results.append(
            {
                "paper_id": paper_id,
                "rank": rank,
                "score": score,
                "match": match_names.get(raw_match, raw_match),
                "title": meta.get("title") or "",
                "authors": authors_text(meta.get("authors")),
                "year": str(meta.get("year") or ""),
                "journal": meta.get("journal") or "",
                "dir_name": candidate["dir_name"],
            }
        )
        if len(results) >= limit:
            break
    return results


def _unified_diagnostics(raw: Mapping[str, object]) -> dict:
    keyword_degraded = bool(raw.get("keyword_degraded"))
    vector_degraded = bool(raw.get("vector_degraded"))
    actions: list[dict[str, str]] = []
    if keyword_degraded:
        actions.append(_action("scholaraio index --rebuild", "Rebuild the keyword index"))
    if vector_degraded:
        actions.append(_action("scholaraio embed", "Build semantic embeddings"))
    if keyword_degraded and vector_degraded:
        return _diagnostics(
            status="unavailable",
            message="Keyword and semantic search indexes are unavailable.",
            keyword="unavailable",
            semantic="unavailable",
            actions=actions,
        )
    if keyword_degraded:
        return _diagnostics(
            status="degraded",
            message="Keyword search is unavailable; results use semantic retrieval only.",
            keyword="unavailable",
            semantic="available",
            actions=actions,
        )
    if vector_degraded:
        return _diagnostics(
            status="degraded",
            message="Semantic search is unavailable; results use keyword retrieval only.",
            keyword="available",
            semantic="unavailable",
            actions=actions,
        )
    return _diagnostics(
        status="ok",
        message="Keyword and semantic retrieval are active.",
        keyword="available",
        semantic="available",
    )


def search_main_library(
    cfg: Config,
    *,
    query: str,
    mode: str,
    filters: LibrarySearchFilters | None = None,
    limit: int = DEFAULT_LIBRARY_SEARCH_RESULTS,
) -> dict:
    """Run a validated ranked search over main-library papers."""
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in LIBRARY_SEARCH_MODES:
        raise LibrarySearchRequestError(
            f"Unsupported search mode: {mode!r}",
            code="invalid_search_mode",
        )
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise LibrarySearchRequestError(
            "A search query is required for ranked search",
            code="missing_search_query",
        )
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise LibrarySearchRequestError(
            "Search limit must be a positive integer",
            code="invalid_search_limit",
        )
    bounded_limit = min(limit, MAX_LIBRARY_SEARCH_RESULTS)
    active_filters = filters or LibrarySearchFilters()
    candidates = _candidate_records(cfg, active_filters)

    if not candidates:
        diagnostics = _diagnostics(
            status="ok",
            message="No library records match the structured filters.",
            keyword="not_checked",
            semantic="not_checked",
        )
        return {
            "mode": normalized_mode,
            "query": normalized_query,
            "total": 0,
            "results": [],
            "diagnostics": diagnostics,
        }

    year = active_filters.year_expression
    journal = active_filters.journal or None
    paper_type = normalize_paper_type(active_filters.paper_type) or None
    paper_ids = set(candidates)
    try:
        if normalized_mode == "keyword":
            from scholaraio.services.index import search

            raw_results = search(
                normalized_query,
                cfg.index_db,
                top_k=bounded_limit,
                cfg=cfg,
                year=year,
                journal=journal,
                paper_type=paper_type,
                paper_ids=paper_ids,
            )
            diagnostics = _diagnostics(
                status="ok",
                message="Keyword retrieval is active.",
                keyword="available",
                semantic="not_used",
            )
        elif normalized_mode == "semantic":
            from scholaraio.services.vectors import vsearch

            raw_results = vsearch(
                normalized_query,
                cfg.index_db,
                top_k=bounded_limit,
                cfg=cfg,
                paper_ids=paper_ids,
            )
            diagnostics = _diagnostics(
                status="ok",
                message="Semantic retrieval is active.",
                keyword="not_used",
                semantic="available",
            )
        else:
            from scholaraio.services.index import unified_search

            raw_results, raw_diagnostics = unified_search(
                normalized_query,
                cfg.index_db,
                top_k=bounded_limit,
                cfg=cfg,
                paper_ids=paper_ids,
                return_diagnostics=True,
            )
            diagnostics = _unified_diagnostics(raw_diagnostics)
    except (FileNotFoundError, ImportError, sqlite3.Error, OSError, RuntimeError, ValueError):
        raw_results = []
        diagnostics = _unavailable_diagnostics(normalized_mode)

    if normalized_mode in {"semantic", "unified"} and diagnostics.get("semantic") == "available":
        from scholaraio.services.vectors import _content_hash

        try:
            with sqlite3.connect(cfg.index_db) as connection:
                hashes = dict(connection.execute("SELECT paper_id, content_hash FROM paper_vectors"))
            pending = sum(
                hashes.get(paper_id) != _content_hash(row["meta"].get("title") or "", row["meta"].get("abstract") or "")
                for paper_id, row in candidates.items()
            )
            diagnostics["semantic_index"] = {
                "state": "stale" if pending else "current",
                "pending": pending,
                "scope": "filtered_records",
            }
            if pending:
                diagnostics["message"] += f" {pending} matching records need embedding updates; run scholaraio embed."
                diagnostics["actions"].append(_action("scholaraio embed", "Update semantic embeddings"))
        except sqlite3.Error:
            diagnostics["semantic_index"] = {"state": "unknown", "scope": "filtered_records"}

    results = _normalize_results(raw_results, normalized_mode, candidates, bounded_limit)
    return {
        "mode": normalized_mode,
        "query": normalized_query,
        "total": len(results),
        "results": results,
        "diagnostics": diagnostics,
    }
