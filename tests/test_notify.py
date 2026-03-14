"""Tests for notify.py — paper notification digest system."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scholaraio.notify import (
    _cron_to_systemd_calendar,
    _filter_seen,
    _mark_seen,
    _render_digest,
    generate_systemd_units,
    get_digest_history,
    init_notify,
    list_notify_tasks,
)


# ============================================================================
#  init_notify
# ============================================================================


class TestInitNotify:
    def test_creates_notify_json(self, tmp_path):
        ws_dir = tmp_path / "my-watch"
        init_notify(ws_dir, query="diffusion model protein structure")
        assert (ws_dir / "notify.json").exists()

    def test_notify_json_content(self, tmp_path):
        ws_dir = tmp_path / "my-watch"
        config = init_notify(
            ws_dir,
            query="protein folding",
            schedule="0 9 * * *",
            channels=["tgram://TOKEN/CHAT"],
            max_papers=5,
            relevance_threshold=0.7,
        )
        assert config["interest_query"] == "protein folding"
        assert config["schedule"] == "0 9 * * *"
        assert config["channels"] == ["tgram://TOKEN/CHAT"]
        assert config["max_papers"] == 5
        assert config["relevance_threshold"] == 0.7
        assert config["last_run"] is None

    def test_creates_workspace_dir(self, tmp_path):
        ws_dir = tmp_path / "nested" / "watch"
        init_notify(ws_dir, query="test query")
        assert ws_dir.is_dir()

    def test_idempotent_update(self, tmp_path):
        ws_dir = tmp_path / "my-watch"
        init_notify(ws_dir, query="original query")
        config = init_notify(ws_dir, query="updated query", max_papers=20)
        assert config["interest_query"] == "updated query"
        assert config["max_papers"] == 20
        # last_run preserved (still None since never set)
        assert config["last_run"] is None

    def test_preserves_last_run_on_update(self, tmp_path):
        ws_dir = tmp_path / "my-watch"
        init_notify(ws_dir, query="q1")
        # Manually set last_run
        notify_json = ws_dir / "notify.json"
        data = json.loads(notify_json.read_text())
        data["last_run"] = "2026-03-01"
        notify_json.write_text(json.dumps(data))
        # Re-init should preserve last_run
        config = init_notify(ws_dir, query="q2")
        assert config["last_run"] == "2026-03-01"


# ============================================================================
#  list_notify_tasks
# ============================================================================


class TestListNotifyTasks:
    def test_empty_workspace_root(self, tmp_path):
        tasks = list_notify_tasks(tmp_path / "workspace")
        assert tasks == []

    def test_lists_only_notify_tasks(self, tmp_path):
        ws_root = tmp_path / "workspace"
        # Create one regular workspace (no notify.json)
        (ws_root / "regular").mkdir(parents=True)
        (ws_root / "regular" / "papers.json").write_text("[]")
        # Create one notify task
        notify_dir = ws_root / "my-watch"
        init_notify(notify_dir, query="diffusion")

        tasks = list_notify_tasks(ws_root)
        assert len(tasks) == 1
        assert tasks[0]["name"] == "my-watch"
        assert tasks[0]["query"] == "diffusion"

    def test_returns_sorted_by_name(self, tmp_path):
        ws_root = tmp_path / "workspace"
        for name in ["z-watch", "a-watch", "m-watch"]:
            init_notify(ws_root / name, query=f"query {name}")
        tasks = list_notify_tasks(ws_root)
        names = [t["name"] for t in tasks]
        assert names == sorted(names)


# ============================================================================
#  State management: _filter_seen / _mark_seen
# ============================================================================


class TestNotifySeen:
    def _make_db(self, tmp_path) -> Path:
        db_path = tmp_path / "index.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notify_seen (
                    doi TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL,
                    workspace TEXT
                )
                """
            )
        return db_path

    def test_filter_seen_empty_db(self, tmp_path):
        db_path = self._make_db(tmp_path)
        papers = [{"doi": "10.1000/abc"}, {"doi": "10.1000/def"}]
        result = _filter_seen(papers, db_path, "ws")
        assert result == papers

    def test_filter_seen_removes_known_dois(self, tmp_path):
        db_path = self._make_db(tmp_path)
        papers = [{"doi": "10.1000/abc"}, {"doi": "10.1000/def"}]
        _mark_seen([papers[0]], db_path, "ws")

        result = _filter_seen(papers, db_path, "ws")
        assert len(result) == 1
        assert result[0]["doi"] == "10.1000/def"

    def test_mark_seen_idempotent(self, tmp_path):
        db_path = self._make_db(tmp_path)
        paper = {"doi": "10.1000/abc"}
        _mark_seen([paper], db_path, "ws")
        _mark_seen([paper], db_path, "ws")  # should not raise
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM notify_seen WHERE doi = ?", ("10.1000/abc",)).fetchone()[0]
        assert count == 1

    def test_filter_seen_no_doi_papers_pass_through(self, tmp_path):
        db_path = self._make_db(tmp_path)
        papers = [{"doi": ""}, {"title": "no doi paper"}]
        result = _filter_seen(papers, db_path, "ws")
        assert len(result) == 2

    def test_new_db_created_and_returns_all(self, tmp_path):
        # DB doesn't exist yet — should be created, all papers pass through (none seen)
        papers = [{"doi": "10.1/x"}]
        result = _filter_seen(papers, tmp_path / "new.db", "ws")
        assert result == papers
        assert (tmp_path / "new.db").exists()


# ============================================================================
#  _render_digest
# ============================================================================


class TestRenderDigest:
    def test_empty_papers(self):
        md = _render_digest([], "protein folding", "test-ws", "2026-03-14")
        assert "0" in md
        assert "protein folding" in md

    def test_paper_title_in_output(self):
        papers = [
            {
                "title": "A Great Paper on Proteins",
                "authors": ["Alice", "Bob"],
                "year": 2026,
                "venue": "Nature",
                "doi": "10.1000/test",
                "cited_by_count": 42,
                "abstract": "We studied proteins.",
                "relevance_score": 0.88,
            }
        ]
        md = _render_digest(papers, "protein folding", "test-ws", "2026-03-14")
        assert "A Great Paper on Proteins" in md
        assert "10.1000/test" in md
        assert "42" in md
        assert "We studied proteins." in md

    def test_star_rating_high_score(self):
        papers = [{"title": "T", "relevance_score": 0.9, "authors": [], "doi": "x", "abstract": ""}]
        md = _render_digest(papers, "q", "ws", "2026-03-14")
        assert "⭐⭐⭐" in md

    def test_star_rating_medium_score(self):
        papers = [{"title": "T", "relevance_score": 0.76, "authors": [], "doi": "x", "abstract": ""}]
        md = _render_digest(papers, "q", "ws", "2026-03-14")
        assert "⭐⭐" in md

    def test_abstract_truncated(self):
        long_abstract = "word " * 100  # ~500 chars
        papers = [{"title": "T", "relevance_score": 0.8, "authors": [], "doi": "x", "abstract": long_abstract}]
        md = _render_digest(papers, "q", "ws", "2026-03-14")
        assert "..." in md


# ============================================================================
#  get_digest_history
# ============================================================================


class TestGetDigestHistory:
    def test_empty_history(self, tmp_path):
        db_path = tmp_path / "index.db"
        result = get_digest_history(db_path, "ws")
        assert result == []

    def test_empty_new_db(self, tmp_path):
        # DB doesn't exist yet — auto-created, returns empty history
        result = get_digest_history(tmp_path / "new.db", "ws")
        assert result == []

    def test_records_returned(self, tmp_path):
        db_path = tmp_path / "index.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE notify_digests (
                    id TEXT PRIMARY KEY, workspace TEXT, generated_at TEXT,
                    sent_at TEXT, channel TEXT, n_papers INTEGER, digest_path TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO notify_digests VALUES (?,?,?,?,?,?,?)",
                ("id1", "test-ws", "2026-03-14T08:00:00Z", None, "tgram://x", 5, "/path/digest.md"),
            )

        records = get_digest_history(db_path, "test-ws")
        assert len(records) == 1
        assert records[0]["n_papers"] == 5
        assert records[0]["workspace"] == "test-ws"


# ============================================================================
#  Systemd generation
# ============================================================================


class TestSystemd:
    def test_cron_weekly_monday(self):
        result = _cron_to_systemd_calendar("0 8 * * 1")
        assert result == "Mon *-*-* 08:00:00"

    def test_cron_daily(self):
        result = _cron_to_systemd_calendar("0 9 * * *")
        assert result == "*-*-* 09:00:00"

    def test_cron_sunday(self):
        result = _cron_to_systemd_calendar("30 7 * * 0")
        assert result == "Sun *-*-* 07:30:00"

    def test_cron_invalid_fallback(self):
        result = _cron_to_systemd_calendar("@weekly")
        assert result == "weekly"

    def test_generate_units_content(self, tmp_path):
        ws_dir = tmp_path / "protein-watch"
        init_notify(ws_dir, query="protein folding", schedule="0 8 * * 1")
        cfg_path = tmp_path / "config.yaml"

        service, timer = generate_systemd_units(ws_dir, cfg_path)

        assert "scholaraio notify run protein-watch" in service
        assert "Mon *-*-* 08:00:00" in timer
        assert "scholaraio-notify-protein-watch.service" in timer
        assert str(cfg_path) in service
