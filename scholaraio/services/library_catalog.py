"""Bounded, disposable SQLite projection for WebUI metadata browsing."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass

from scholaraio.core.config import Config
from scholaraio.services import library_view as view
from scholaraio.stores.library_state import Manifest, library_manifest, library_stamp
from scholaraio.stores.papers import read_meta


@dataclass(frozen=True)
class PageQuery:
    offset: int = 0
    limit: int = 100
    sort: str = "year"
    descending: bool = True
    revision: str = ""

    @classmethod
    def parse(cls, params: Mapping[str, str]) -> PageQuery:
        offset, limit = int(params.get("offset", "0")), int(params.get("limit", "100"))
        sort = params.get("sort", "year")
        if offset < 0 or not 1 <= limit <= 200:
            raise ValueError("offset must be nonnegative; limit must be between 1 and 200")
        if sort not in {"year", "title", "authors_text", "paper_type", "citation_count", "relevance"}:
            raise ValueError("Unsupported sort field")
        if params.get("direction", "desc") not in {"asc", "desc"}:
            raise ValueError("Unsupported sort direction")
        for key in ("year_from", "year_to"):
            if params.get(key) and (not params[key].isdigit() or not 1000 <= int(params[key]) <= 9999):
                raise ValueError("Year filters must be four-digit years")
        if params.get("year_from") and params.get("year_to") and int(params["year_from"]) > int(params["year_to"]):
            raise ValueError("year_to must not precede year_from")
        return cls(offset, limit, sort, params.get("direction", "desc") == "desc", params.get("revision", ""))


class LibraryCatalog:
    """One per server and source; serializes scan/publication/query as one snapshot.

    Only changed records are parsed. The entire projection is disposable and is
    rebuilt after a server restart; it never writes paper metadata.
    """

    def __init__(self, cfg: Config, source: str, *, background: bool = True) -> None:
        self.background = background
        self.cfg, self.source = cfg, source
        self.root = cfg.papers_dir if source == "main" else cfg.proceedings_dir
        self.lock = threading.Lock()
        self.manifest: Manifest | None = None
        self.revision = 0
        self.audit_revision = ""
        self.root_stamp = (0, 0)
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        self.scan_error = ""
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.create_function("fold", 1, lambda value: str(value or "").casefold(), deterministic=True)
        self.db.execute("""CREATE TABLE records (
            path TEXT PRIMARY KEY, paper_id TEXT, title TEXT, authors_text TEXT,
            year INTEGER, journal TEXT, doi TEXT, paper_type TEXT, volume TEXT,
            citation_count INTEGER, haystack TEXT, payload TEXT)""")
        self.db.execute("CREATE INDEX record_year ON records(year, paper_id)")
        self.db.execute("CREATE INDEX record_title ON records(title, paper_id)")

    def close(self) -> None:
        self.stop.set()
        if self.worker is not None:
            self.worker.join()
        with self.lock:
            self.db.close()

    def _scan_loop(self) -> None:
        delay = 5.0
        while not self.stop.wait(delay):
            started = time.monotonic()
            try:
                stamp = library_stamp(self.root)
                manifest = library_manifest(self.root, force=True) if self.root.is_dir() else {}
                with self.lock:
                    current = library_stamp(self.root)
                    if current != stamp:
                        continue
                    self._refresh(manifest=manifest)
                    self.scan_error = ""
            except (OSError, ValueError, sqlite3.Error):
                self.scan_error = "Library refresh failed; showing the last published snapshot. Try Refresh."
                logging.getLogger(__name__).exception("Background library scan failed")
            delay = max(0.1, 5.0 - (time.monotonic() - started))

    def _refresh(self, *, force: bool = False, manifest: Manifest | None = None) -> None:
        stamp = library_stamp(self.root)
        if manifest is None:
            if self.manifest is not None and stamp == self.root_stamp and not force:
                return
            manifest = library_manifest(self.root, force=force) if self.root.is_dir() else {}
        self.root_stamp = stamp
        audit = view.main_audit_status(self.root) if self.source == "main" else {}
        audit_revision = str(audit.get("completed_at", ""))
        old = self.manifest or {}
        changed = {path for path, signature in manifest.items() if old.get(path) != signature}
        if audit_revision != self.audit_revision:
            changed.update(manifest)
        if self.source == "proceedings":
            volumes = {path for path in changed if "/papers/" not in path}
            changed.update(path for path in manifest if path.split("/")[0] in volumes)
        if self.manifest is not None and not changed and old.keys() == manifest.keys():
            return
        issue_map = view._AUDIT_CACHE.get(str(self.root.resolve()), (0, {}))[1]
        modified = self.manifest is None
        with self.db:
            for path in old.keys() - manifest.keys():
                modified |= self.db.execute("DELETE FROM records WHERE path=?", (path,)).rowcount > 0
            for path in changed:
                directory = self.root / path
                if not any(name == "meta.json" for name, _signature in manifest[path]):
                    modified |= self.db.execute("DELETE FROM records WHERE path=?", (path,)).rowcount > 0
                    continue
                if self.source == "proceedings":
                    if "/papers/" not in path:
                        continue
                    records = list(view._iter_proceedings_view_records(self.cfg, only=directory))
                    row = records[0][0] if records else None
                else:
                    try:
                        meta = read_meta(directory)
                        issues = issue_map.get(directory.name, [])
                    except (ValueError, OSError) as exc:
                        meta = {"id": directory.name, "title": directory.name}
                        issues = view._metadata_read_issues(directory.name, exc)
                    if meta.get("id") and not isinstance(meta["id"], str):
                        issues = [
                            *issues,
                            {
                                "severity": "warning",
                                "code": "invalid_metadata_type",
                                "field": "id",
                                "message": "id must be text",
                            },
                        ]
                        meta = {**meta, "id": directory.name}
                    row = view._main_row(directory, meta, issues)
                    paths = view._paper_paths(self.root.resolve())
                    paths[str(row["paper_id"])] = directory
                if row is None:
                    modified |= self.db.execute("DELETE FROM records WHERE path=?", (path,)).rowcount > 0
                    continue

                def number(value: object) -> int:
                    try:
                        return int(str(value or "0"))
                    except ValueError:
                        return 0

                for key in ("paper_id", "title", "authors_text", "journal", "doi", "paper_type", "proceeding_title"):
                    value = row.get(key, "")
                    if not isinstance(value, str):
                        row[key] = str(value or "")
                        row["issues"] = [
                            *row.get("issues", []),
                            {
                                "code": "invalid_metadata_type",
                                "severity": "warning",
                                "message": f"{key} must be text",
                                "field": key,
                            },
                        ]
                        row["issue_counts"] = view._issue_counts(row["issues"])
                payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
                previous = self.db.execute("SELECT payload FROM records WHERE path=?", (path,)).fetchone()
                if previous is not None and previous[0] == payload:
                    continue
                modified = True
                self.db.execute(
                    "INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        path,
                        row["paper_id"],
                        row["title"],
                        row["authors_text"],
                        number(row["year"]),
                        " ".join([str(row.get("journal") or ""), str(row.get("proceeding_title") or "")]),
                        row.get("doi", ""),
                        row["paper_type"],
                        row.get("proceeding_title", ""),
                        number(row.get("citation_count")),
                        " ".join(
                            str(row.get(key) or "")
                            for key in (
                                "title",
                                "authors_text",
                                "journal",
                                "doi",
                                "paper_id",
                                "dir_name",
                                "proceeding_title",
                            )
                        ).casefold(),
                        payload,
                    ),
                )
        self.manifest = manifest
        self.audit_revision = audit_revision
        if modified:
            self.revision += 1

    def page(self, params: Mapping[str, str]) -> dict:
        query = PageQuery.parse(params)
        ids = json.loads(params["ids"]) if "ids" in params else None
        if ids is not None and (
            not isinstance(ids, list) or len(ids) > 200 or any(not isinstance(x, str) for x in ids)
        ):
            raise ValueError("ids must be an array of at most 200 paper IDs")
        with self.lock:
            self._refresh(force=params.get("refresh") == "1")
            if self.background and self.worker is None:
                self.worker = threading.Thread(target=self._scan_loop, name="scholaraio-catalog", daemon=True)
                self.worker.start()
            clauses: list[str] = []
            values: list[str | int] = []
            for key, column in [
                ("q", "haystack"),
                ("title", "title"),
                ("author", "authors_text"),
                ("journal", "journal"),
                ("doi", "doi"),
            ]:
                if params.get(key):
                    clauses.append(f"instr(fold({column}), ?) > 0")
                    values.append(params[key].casefold())
            for key, column in [("paper_type", "paper_type"), ("volume", "volume")]:
                if params.get(key):
                    clauses.append(f"{column} = ?")
                    values.append(params[key])
            for key, operator in [("year_from", ">="), ("year_to", "<=")]:
                if params.get(key):
                    clauses.append(f"year {operator} ?")
                    values.append(int(params[key]))
            if ids is not None:
                clauses.append("paper_id IN (" + ",".join("?" for _ in ids) + ")")
                values.extend(ids)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            matched = self.db.execute("SELECT COUNT(*) FROM records" + where, values).fetchone()[0]
            revision = str(self.revision)
            offset = query.offset if not query.revision or query.revision == revision else 0
            if offset >= matched:
                offset = max(0, ((matched - 1) // query.limit) * query.limit)
            order_values: list[str] = []
            if query.sort == "relevance" and ids:
                order = "CASE paper_id " + " ".join(f"WHEN ? THEN {i}" for i in range(len(ids))) + " END"
                order_values = ids
            else:
                column = "year" if query.sort == "relevance" else query.sort
                order = column + (" DESC" if query.descending else " ASC")
            rows = self.db.execute(
                "SELECT payload FROM records"
                + where
                + " ORDER BY "
                + order
                + ", paper_id ASC, path ASC LIMIT ? OFFSET ?",
                [*values, *order_values, query.limit, offset],
            ).fetchall()
            total = self.db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            types = [
                r[0]
                for r in self.db.execute(
                    "SELECT DISTINCT paper_type FROM records WHERE paper_type != '' ORDER BY paper_type"
                )
            ]
            volumes = [
                r[0] for r in self.db.execute("SELECT DISTINCT volume FROM records WHERE volume != '' ORDER BY volume")
            ]
        if self.source == "main":
            view._background_issue_map(self.root)
        return {
            "source": self.source,
            "root": str(self.root),
            "generated_at": view._now_iso(),
            "total": total,
            "matched": matched,
            "offset": offset,
            "limit": query.limit,
            "revision": revision,
            "refresh_error": self.scan_error,
            "types": types,
            "volumes": volumes,
            "audit": view.main_audit_status(self.root) if self.source == "main" else {},
            "papers": [json.loads(row[0]) for row in rows],
        }
