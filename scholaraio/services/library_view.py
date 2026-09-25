"""Read-only view models for the local library WebUI."""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING
from urllib.parse import quote

from scholaraio.services.audit import Issue, audit_papers
from scholaraio.services.export import meta_to_bibtex
from scholaraio.stores.papers import (
    authors_text,
    best_citation,
    find_pdf,
    iter_paper_dirs,
    normalize_paper_type,
    read_meta,
)
from scholaraio.stores.proceedings import iter_proceedings_dirs

if TYPE_CHECKING:
    from scholaraio.core.config import Config
    from scholaraio.stores.pdf_edit_mirror import PdfEditMirrorRecord

_AUDIT_CACHE_TTL_SECONDS = 30.0
_AUDIT_CACHE: dict[str, tuple[float, dict[str, list[dict]]]] = {}
_AUDIT_CACHE_LOCK = threading.Lock()
_BACKGROUND_AUDIT_LOCK = threading.Lock()
_BACKGROUND_AUDITS: set[str] = set()
_AUDIT_STATUS: dict[str, dict] = {}
_LOG = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _paper_paths(root: Path) -> dict[str, Path]:
    # These are hints only: always validate current metadata before using one.
    return {}


def main_audit_status(papers_dir: Path) -> dict:
    with _BACKGROUND_AUDIT_LOCK:
        return dict(_AUDIT_STATUS.get(str(papers_dir.resolve()), {"state": "pending", "completed_at": ""}))


def _background_issue_map(papers_dir: Path) -> dict[str, list[dict]]:
    key = str(papers_dir.resolve())
    cached = _AUDIT_CACHE.get(key)
    now = monotonic()
    if cached and cached[0] > now:
        return cached[1]
    with _BACKGROUND_AUDIT_LOCK:
        status = _AUDIT_STATUS.get(key, {})
        if key not in _BACKGROUND_AUDITS and status.get("retry_at", 0) <= now:
            _BACKGROUND_AUDITS.add(key)
            _AUDIT_STATUS[key] = {"state": "running", "completed_at": status.get("completed_at", "")}

            def refresh() -> None:
                try:
                    _main_issue_map(papers_dir)
                except Exception:
                    _LOG.exception("Background library audit failed")
                    with _BACKGROUND_AUDIT_LOCK:
                        _AUDIT_STATUS[key] = {
                            "state": "failed",
                            "completed_at": status.get("completed_at", ""),
                            "retry_at": monotonic() + _AUDIT_CACHE_TTL_SECONDS,
                        }
                finally:
                    with _BACKGROUND_AUDIT_LOCK:
                        _BACKGROUND_AUDITS.discard(key)

            threading.Thread(target=refresh, name="scholaraio-library-audit", daemon=True).start()
    return cached[1] if cached else {}


class LibraryPaperNotFoundError(KeyError):
    """Raised when a requested stable paper ID is not in the library."""


class LibraryPdfNotFoundError(KeyError):
    """Raised when a known paper does not have a local PDF."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool_has_text(value: object) -> bool:
    return bool(str(value or "").strip())


def _pdf_url(source: str, paper_id: str) -> str:
    return f"/api/{source}/pdf?id={quote(paper_id)}"


def _pdf_fields(source: str, paper_dir: Path, paper_id: str) -> dict:
    pdf = find_pdf(paper_dir)
    return {
        "has_pdf": pdf is not None,
        "pdf_filename": pdf.name if pdf else "",
        "pdf_url": _pdf_url(source, paper_id) if pdf else "",
    }


def _issue_dict(issue: Issue) -> dict:
    return {
        "paper_id": issue.paper_id,
        "severity": issue.severity,
        "rule": issue.rule,
        "message": issue.message,
    }


def _empty_issue_counts() -> dict[str, int]:
    return {"error": 0, "warning": 0, "info": 0}


def _issue_counts(issues: list[dict]) -> dict[str, int]:
    counts = Counter(issue["severity"] for issue in issues)
    result = _empty_issue_counts()
    result.update({key: int(counts.get(key, 0)) for key in result})
    return result


def _main_issue_map(papers_dir: Path) -> dict[str, list[dict]]:
    cache_key = str(papers_dir.resolve())
    now = monotonic()
    with _AUDIT_CACHE_LOCK:
        cached = _AUDIT_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

        by_dir: dict[str, list[dict]] = defaultdict(list)
        for issue in audit_papers(papers_dir):
            by_dir[issue.paper_id].append(_issue_dict(issue))
        issue_map = dict(by_dir)
        _AUDIT_CACHE[cache_key] = (monotonic() + _AUDIT_CACHE_TTL_SECONDS, issue_map)
        with _BACKGROUND_AUDIT_LOCK:
            _AUDIT_STATUS[cache_key] = {"state": "ready", "completed_at": _now_iso()}
        return issue_map


def _invalid_json_issues(paper_id: str, exc: Exception) -> list[dict]:
    return [
        {
            "paper_id": paper_id,
            "severity": "error",
            "rule": "invalid_json",
            "message": f"Failed to parse JSON: {exc}",
        }
    ]


def _metadata_read_issues(paper_id: str, exc: Exception) -> list[dict]:
    if isinstance(exc, ValueError):
        return _invalid_json_issues(paper_id, exc)
    return [
        {
            "paper_id": paper_id,
            "severity": "error",
            "rule": "metadata_unreadable",
            "message": f"Failed to read metadata: {exc}",
        }
    ]


def _main_row(paper_dir: Path, meta: dict, issues: list[dict]) -> dict:
    paper_id = meta.get("id") or paper_dir.name
    toc = meta.get("toc") or []
    md_file = paper_dir / "paper.md"
    raw_type = meta.get("paper_type") or ""
    return {
        "paper_id": paper_id,
        "dir_name": paper_dir.name,
        "title": meta.get("title") or "",
        "authors": meta.get("authors") or [],
        "authors_text": authors_text(meta.get("authors") or []),
        "year": meta.get("year") or "",
        "journal": meta.get("journal") or "",
        "doi": meta.get("doi") or "",
        "paper_type": normalize_paper_type(raw_type, meta.get("journal"), meta.get("doi")),
        "paper_type_raw": raw_type,
        "citation_count": best_citation(meta),
        "has_md": md_file.exists(),
        "has_abstract": _bool_has_text(meta.get("abstract")),
        "has_l3": _bool_has_text(meta.get("l3_conclusion")),
        "toc_count": len(toc) if isinstance(toc, list) else 0,
        "issue_counts": _issue_counts(issues),
        "issues": issues,
        **_pdf_fields("main", paper_dir, paper_id),
    }


def build_main_library_view(cfg: Config, *, background_audit: bool = False) -> dict:
    """Return a live read-only table view for the configured main paper library."""
    papers_dir = cfg.papers_dir
    if background_audit:
        cached = _AUDIT_CACHE.get(str(papers_dir.resolve()))
        issue_map = cached[1] if cached else {}
    else:
        issue_map = _main_issue_map(papers_dir)
    rows: list[dict] = []
    totals = _empty_issue_counts()
    for paper_dir in iter_paper_dirs(papers_dir):
        try:
            meta = read_meta(paper_dir)
        except (ValueError, OSError) as exc:
            issues = _metadata_read_issues(paper_dir.name, exc)
            meta = {"id": paper_dir.name, "title": paper_dir.name}
        else:
            issues = issue_map.get(paper_dir.name, [])
        paths = _paper_paths(papers_dir.resolve())
        paths[str(meta.get("id") or paper_dir.name)] = paper_dir
        paths[paper_dir.name] = paper_dir
        row = _main_row(paper_dir, meta, issues)
        for key, value in row["issue_counts"].items():
            totals[key] += value
        rows.append(row)

    rows.sort(key=lambda row: (str(row.get("year") or ""), row.get("title") or ""), reverse=True)
    if background_audit:
        # Build the first useful view before starting CPU-heavy audit work.
        _background_issue_map(papers_dir)
    return {
        "source": "main",
        "root": str(papers_dir),
        "generated_at": _now_iso(),
        "total": len(rows),
        "issue_totals": totals,
        "audit": main_audit_status(papers_dir),
        "papers": rows,
    }


def _find_main_paper(
    cfg: Config, paper_id: str, *, include_issues: bool = True, background_audit: bool = False
) -> tuple[Path, dict, list[dict]]:
    issue_map = {}
    if include_issues:
        issue_map = _background_issue_map(cfg.papers_dir) if background_audit else _main_issue_map(cfg.papers_dir)
    paths = _paper_paths(cfg.papers_dir.resolve())
    cached = paths.get(paper_id)
    if cached is not None:
        try:
            meta = read_meta(cached)
        except (ValueError, OSError):
            paths.pop(paper_id, None)
        else:
            if paper_id in {meta.get("id") or cached.name, cached.name}:
                return cached, meta, issue_map.get(cached.name, [])
            paths.pop(paper_id, None)
    for paper_dir in iter_paper_dirs(cfg.papers_dir):
        try:
            meta = read_meta(paper_dir)
        except (ValueError, OSError) as exc:
            if paper_id == paper_dir.name:
                return (
                    paper_dir,
                    {"id": paper_dir.name, "title": paper_dir.name},
                    _metadata_read_issues(paper_dir.name, exc),
                )
            continue
        current_id = meta.get("id") or paper_dir.name
        paths[current_id] = paper_dir
        paths[paper_dir.name] = paper_dir
        if paper_id in {current_id, paper_dir.name}:
            return paper_dir, meta, issue_map.get(paper_dir.name, [])
    raise KeyError(paper_id)


def get_main_paper_detail(cfg: Config, paper_id: str, *, background_audit: bool = False) -> dict:
    """Return detailed read-only metadata for one main-library paper."""
    paper_dir, meta, issues = _find_main_paper(cfg, paper_id, background_audit=background_audit)
    row = _main_row(paper_dir, meta, issues)
    return {
        **row,
        "audit": main_audit_status(cfg.papers_dir),
        "abstract": meta.get("abstract") or "",
        "l3_conclusion": meta.get("l3_conclusion") or "",
        "toc": meta.get("toc") or [],
        "ids": meta.get("ids") or {},
        "source_path": str(paper_dir),
    }


def _proceedings_row(cfg: Config, row: dict, *, meta: dict | None = None, issues: list[dict] | None = None) -> dict:
    paper_dir = cfg.proceedings_dir / row["proceeding_dir"] / "papers" / row["dir_name"]
    meta_path = paper_dir / "meta.json"
    paper_id = row.get("paper_id") or row.get("dir_name") or ""
    row_issues = list(issues or [])
    if meta is None:
        try:
            meta = read_meta(paper_dir) if meta_path.exists() else {}
        except (ValueError, OSError) as exc:
            meta = {"id": paper_id, "title": paper_id}
            row_issues.extend(_metadata_read_issues(paper_id, exc))
    toc = meta.get("toc") or []
    raw_type = row.get("paper_type") or meta.get("paper_type") or ""
    return {
        "paper_id": paper_id,
        "dir_name": row.get("dir_name") or "",
        "title": row.get("title") or meta.get("title") or "",
        "authors": meta.get("authors") or [],
        "authors_text": row.get("authors") or authors_text(meta.get("authors") or []),
        "year": row.get("year") or "",
        "journal": row.get("journal") or "",
        "doi": row.get("doi") or "",
        "paper_type": normalize_paper_type(raw_type),
        "paper_type_raw": raw_type,
        "proceeding_id": row.get("proceeding_id") or "",
        "proceeding_dir": row.get("proceeding_dir") or "",
        "proceeding_title": row.get("proceeding_title") or "",
        "has_md": bool(row.get("md_path")),
        "has_abstract": _bool_has_text(row.get("abstract")),
        "has_l3": _bool_has_text(row.get("conclusion")),
        "toc_count": len(toc) if isinstance(toc, list) else 0,
        "issue_counts": _issue_counts(row_issues),
        "issues": row_issues,
        **_pdf_fields("proceedings", paper_dir, paper_id),
    }


def _iter_proceedings_view_records(cfg: Config, *, only: Path | None = None):
    volumes = [only.parent.parent] if only is not None else iter_proceedings_dirs(cfg.proceedings_dir)
    for proceeding_dir in volumes:
        meta_path = proceeding_dir / "meta.json"
        papers_dir = proceeding_dir / "papers"
        if not meta_path.exists() or not papers_dir.is_dir():
            continue

        proceeding_issues: list[dict] = []
        try:
            proceeding_meta = read_meta(proceeding_dir)
        except (ValueError, OSError) as exc:
            proceeding_meta = {"id": proceeding_dir.name, "title": proceeding_dir.name}
            proceeding_issues = _metadata_read_issues(proceeding_dir.name, exc)
        proceeding_title = proceeding_meta.get("title") or proceeding_dir.name
        proceeding_id = proceeding_meta.get("id") or proceeding_dir.name

        try:
            paper_dirs = [only] if only is not None else sorted(papers_dir.iterdir())
        except OSError:
            continue
        for paper_dir in paper_dirs:
            if not paper_dir.is_dir():
                continue
            paper_meta_path = paper_dir / "meta.json"
            if not paper_meta_path.exists():
                continue
            issues = list(proceeding_issues)
            try:
                paper_meta = read_meta(paper_dir)
            except (ValueError, OSError) as exc:
                paper_meta = {"id": paper_dir.name, "title": paper_dir.name}
                issues.extend(_metadata_read_issues(paper_dir.name, exc))
            paper_id = paper_meta.get("id") or paper_dir.name
            if not isinstance(paper_id, str):
                issues.append(
                    {
                        "rule": "invalid_metadata_type",
                        "severity": "warning",
                        "field": "id",
                        "message": "id must be text",
                    }
                )
                paper_id = paper_dir.name
            row = {
                "paper_id": paper_id,
                "title": paper_meta.get("title") or "",
                "authors": authors_text(paper_meta.get("authors") or []),
                "year": str(paper_meta.get("year") or ""),
                "journal": paper_meta.get("journal") or "",
                "abstract": paper_meta.get("abstract") or "",
                "conclusion": paper_meta.get("l3_conclusion") or "",
                "doi": paper_meta.get("doi") or "",
                "paper_type": paper_meta.get("paper_type") or "",
                "citation_count": "",
                "md_path": str((paper_dir / "paper.md").resolve()) if (paper_dir / "paper.md").exists() else "",
                "dir_name": paper_dir.name,
                "proceeding_id": proceeding_id,
                "proceeding_dir": proceeding_dir.name,
                "proceeding_title": paper_meta.get("proceeding_title") or proceeding_title,
            }
            paths = _paper_paths(cfg.proceedings_dir.resolve())
            paths[row["paper_id"]] = paper_dir
            paths[paper_dir.name] = paper_dir
            yield _proceedings_row(cfg, row, meta=paper_meta, issues=issues), paper_dir, paper_meta


def build_proceedings_library_view(cfg: Config) -> dict:
    """Return a live read-only table view for configured proceedings child papers."""
    rows = [row for row, _paper_dir, _meta in _iter_proceedings_view_records(cfg)]
    rows.sort(key=lambda row: (str(row.get("year") or ""), row.get("title") or ""), reverse=True)
    volumes = sorted({row["proceeding_title"] for row in rows if row.get("proceeding_title")})
    totals = _empty_issue_counts()
    for row in rows:
        for key, value in row["issue_counts"].items():
            totals[key] += value
    return {
        "source": "proceedings",
        "root": str(cfg.proceedings_dir),
        "generated_at": _now_iso(),
        "total": len(rows),
        "issue_totals": totals,
        "volumes": volumes,
        "papers": rows,
    }


def _find_proceedings_row(cfg: Config, paper_id: str) -> tuple[dict, Path, dict]:
    paths = _paper_paths(cfg.proceedings_dir.resolve())
    cached = paths.get(paper_id)
    if cached is not None:
        for row, paper_dir, meta in _iter_proceedings_view_records(cfg, only=cached):
            if paper_id in {row["paper_id"], row["dir_name"]}:
                return row, paper_dir, meta
        paths.pop(paper_id, None)
    for row, paper_dir, meta in _iter_proceedings_view_records(cfg):
        if paper_id in {row["paper_id"], row["dir_name"]}:
            return row, paper_dir, meta
    raise KeyError(paper_id)


def get_proceedings_paper_detail(cfg: Config, paper_id: str) -> dict:
    """Return detailed read-only metadata for one proceedings child paper."""
    row, paper_dir, meta = _find_proceedings_row(cfg, paper_id)
    return {
        **row,
        "abstract": meta.get("abstract") or "",
        "l3_conclusion": meta.get("l3_conclusion") or "",
        "toc": meta.get("toc") or [],
        "ids": meta.get("ids") or {},
        "source_path": str(paper_dir),
    }


def get_main_paper_bibtex(cfg: Config, paper_id: str) -> str:
    """Return canonical BibTeX for one main-library paper."""
    _paper_dir, meta, _issues = _find_main_paper(cfg, paper_id, include_issues=False)
    return meta_to_bibtex(meta)


def get_proceedings_paper_bibtex(cfg: Config, paper_id: str) -> str:
    """Return canonical BibTeX for one proceedings child paper."""
    row, _paper_dir, meta = _find_proceedings_row(cfg, paper_id)
    bib_meta = dict(meta)
    for field in ("title", "authors", "year", "journal", "doi"):
        if not bib_meta.get(field) and row.get(field):
            bib_meta[field] = row[field]
    bib_meta["paper_type"] = bib_meta.get("paper_type") or row.get("paper_type") or "conference-paper"
    bib_meta["booktitle"] = (
        bib_meta.get("booktitle") or bib_meta.get("proceeding_title") or row.get("proceeding_title") or ""
    )
    return meta_to_bibtex(bib_meta)


def get_main_paper_pdf(cfg: Config, paper_id: str) -> Path:
    """Return the local PDF path for one main-library paper."""
    try:
        paper_dir, _meta, _issues = _find_main_paper(cfg, paper_id, include_issues=False)
    except KeyError as exc:
        raise LibraryPaperNotFoundError(paper_id) from exc
    pdf = find_pdf(paper_dir)
    if pdf is None:
        raise LibraryPdfNotFoundError(paper_id)
    return pdf


def get_proceedings_paper_pdf(cfg: Config, paper_id: str) -> Path:
    """Return the local PDF path for one proceedings child paper."""
    try:
        _row, paper_dir, _meta = _find_proceedings_row(cfg, paper_id)
    except KeyError as exc:
        raise LibraryPaperNotFoundError(paper_id) from exc
    pdf = find_pdf(paper_dir)
    if pdf is None:
        raise LibraryPdfNotFoundError(paper_id)
    return pdf


def _pdf_sync_identity(meta: dict) -> str:
    doi = str(meta.get("doi") or "").strip().casefold()
    if doi:
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if doi.startswith(prefix):
                doi = doi[len(prefix) :]
                break
        return f"doi:{doi}"
    raw_ids = meta.get("ids")
    ids = raw_ids if isinstance(raw_ids, dict) else {}
    for key in ("arxiv", "pmid", "openalex", "semantic_scholar"):
        value = str(ids.get(key) or meta.get(f"{key}_id") or "").strip().casefold()
        if value:
            return f"{key}:{value}"
    return ""


def _pdf_sync_hash_matches(path: Path | None, expected_hash: str) -> bool:
    if path is None or not expected_hash:
        return False
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_hash


def _pdf_sync_target(
    cfg: Config,
    *,
    source: str,
    paper_dir: Path,
    meta: dict,
    record: PdfEditMirrorRecord | None,
):
    from scholaraio.services.pdf_edit_mirror import PdfMirrorTarget

    pdf = find_pdf(paper_dir)
    if pdf is None:
        stored = record.canonical_path if record is not None else None
        if stored is not None and stored.parent.resolve() == paper_dir.resolve() and stored.suffix.casefold() == ".pdf":
            pdf = stored
        else:
            pdf = paper_dir / f"{paper_dir.name}.pdf"
    paper_id = str(meta.get("id") or paper_dir.name)
    return PdfMirrorTarget(
        library_kind=source,
        paper_id=paper_id,
        canonical_path=pdf.resolve(),
        library_root=cfg.papers_dir if source == "main" else cfg.proceedings_dir,
        display_name=pdf.name,
        identity=_pdf_sync_identity(meta),
    )


def resolve_pdf_edit_mirror_target(
    cfg: Config,
    source: str,
    paper_id: str,
    *,
    record: PdfEditMirrorRecord | None = None,
):
    """Resolve a mirror target by current ID, then unambiguous durable identity."""
    from scholaraio.services.pdf_edit_mirror import PdfTargetResolution

    if source == "main":
        try:
            paper_dir, meta, _issues = _find_main_paper(cfg, paper_id, include_issues=False)
        except KeyError:
            candidates: list[tuple[Path, dict]] = []
            for candidate_dir in iter_paper_dirs(cfg.papers_dir):
                try:
                    candidate_meta = read_meta(candidate_dir)
                except (OSError, ValueError):
                    continue
                candidate_pdf = find_pdf(candidate_dir)
                same_file = bool(
                    record is not None
                    and candidate_pdf is not None
                    and candidate_pdf.resolve() == record.canonical_path.resolve()
                )
                same_identity = bool(
                    record is not None and record.identity and _pdf_sync_identity(candidate_meta) == record.identity
                )
                same_hash = bool(
                    not (same_file or same_identity)
                    and record is not None
                    and record.base_hash
                    and _pdf_sync_hash_matches(candidate_pdf, record.base_hash)
                )
                if same_file or same_identity or same_hash:
                    candidates.append((candidate_dir, candidate_meta))
        else:
            return PdfTargetResolution(
                target=_pdf_sync_target(cfg, source=source, paper_dir=paper_dir, meta=meta, record=record)
            )
    elif source == "proceedings":
        try:
            _row, paper_dir, meta = _find_proceedings_row(cfg, paper_id)
        except KeyError:
            candidates = []
            for _row, candidate_dir, candidate_meta in _iter_proceedings_view_records(cfg):
                candidate_pdf = find_pdf(candidate_dir)
                same_file = bool(
                    record is not None
                    and candidate_pdf is not None
                    and candidate_pdf.resolve() == record.canonical_path.resolve()
                )
                same_identity = bool(
                    record is not None and record.identity and _pdf_sync_identity(candidate_meta) == record.identity
                )
                same_hash = bool(
                    not (same_file or same_identity)
                    and record is not None
                    and record.base_hash
                    and _pdf_sync_hash_matches(candidate_pdf, record.base_hash)
                )
                if same_file or same_identity or same_hash:
                    candidates.append((candidate_dir, candidate_meta))
        else:
            return PdfTargetResolution(
                target=_pdf_sync_target(cfg, source=source, paper_dir=paper_dir, meta=meta, record=record)
            )
    else:
        raise ValueError(f"Unsupported library source: {source}")

    if len(candidates) == 1:
        paper_dir, meta = candidates[0]
        return PdfTargetResolution(
            target=_pdf_sync_target(cfg, source=source, paper_dir=paper_dir, meta=meta, record=record)
        )
    return PdfTargetResolution(target=None, ambiguous=len(candidates) > 1)
