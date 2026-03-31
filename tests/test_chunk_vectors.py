from __future__ import annotations

import json
import sqlite3
from argparse import Namespace
from types import SimpleNamespace

from scholaraio import cli
from scholaraio.vectors import build_chunk_vectors, chunk_search


class TestBuildChunkVectors:
    def test_build_chunk_vectors_from_toc(self, tmp_path, monkeypatch):
        papers_dir = tmp_path / "papers"
        pdir = papers_dir / "Smith-2023-Turbulence"
        pdir.mkdir(parents=True)
        (pdir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "aaaa-1111",
                    "title": "Turbulence modeling",
                    "toc": [
                        {"line": 1, "level": 1, "title": "Introduction"},
                        {"line": 5, "level": 1, "title": "Method"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (pdir / "paper.md").write_text(
            "\n".join(
                [
                    "# Introduction",
                    "Line 2",
                    "Line 3",
                    "Line 4",
                    "# Method",
                    "Line 6",
                    "Line 7",
                ]
            ),
            encoding="utf-8",
        )

        db = tmp_path / "index.db"
        monkeypatch.setattr("scholaraio.vectors._embed_batch", lambda texts, cfg=None: [[float(i + 1), 0.0] for i in range(len(texts))])

        count = build_chunk_vectors(papers_dir, db, cfg=None)

        assert count == 2
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, paper_id, section_title, start_line, end_line
                FROM chunk_vectors
                ORDER BY chunk_id
                """
            ).fetchall()
        assert rows == [
            ("aaaa-1111:1", "aaaa-1111", "Introduction", 1, 4),
            ("aaaa-1111:2", "aaaa-1111", "Method", 5, 7),
        ]


class TestChunkSearch:
    def test_chunk_search_returns_line_and_section(self, tmp_path, monkeypatch):
        db = tmp_path / "index.db"
        with sqlite3.connect(db) as conn:
            conn.execute(
                """
                CREATE TABLE chunk_vectors (
                    chunk_id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL,
                    section_title TEXT,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding BLOB NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE TABLE papers (paper_id TEXT, title TEXT, authors TEXT, year TEXT, journal TEXT, citation_count TEXT)"
            )
            conn.execute("CREATE TABLE papers_registry (id TEXT, dir_name TEXT)")
            conn.execute(
                """
                INSERT INTO chunk_vectors
                (chunk_id, paper_id, section_title, start_line, end_line, content_hash, embedding)
                VALUES ('aaaa-1111:1', 'aaaa-1111', 'Method', 10, 22, 'h1', x'00000000')
                """
            )
            conn.execute(
                "INSERT INTO papers (paper_id, title, authors, year, journal, citation_count) VALUES (?, ?, ?, ?, ?, ?)",
                ("aaaa-1111", "Turbulence", "John Smith", "2023", "JFM", "12"),
            )
            conn.execute("INSERT INTO papers_registry (id, dir_name) VALUES (?, ?)", ("aaaa-1111", "Smith-2023-Turbulence"))
            conn.commit()

        monkeypatch.setattr("scholaraio.vectors._build_chunk_faiss_index", lambda db_path: (SimpleNamespace(ntotal=1), ["aaaa-1111:1"]))
        monkeypatch.setattr("scholaraio.vectors._vsearch_faiss", lambda query, index, paper_ids, top_k, cfg=None: [("aaaa-1111:1", 0.91)])

        results = chunk_search("method details", db, top_k=1)

        assert len(results) == 1
        first = results[0]
        assert first["paper_id"] == "aaaa-1111"
        assert first["section_title"] == "Method"
        assert first["start_line"] == 10
        assert first["end_line"] == 22
        assert first["title"] == "Turbulence"
        assert first["dir_name"] == "Smith-2023-Turbulence"


class TestCliChunkFlags:
    def test_cmd_index_with_chunks_builds_chunk_vectors(self, tmp_papers, tmp_db, monkeypatch):
        monkeypatch.setattr("scholaraio.index.build_index", lambda papers_dir, db_path, rebuild=False: 2)
        called = {}

        def _fake_build_chunk_vectors(papers_dir, db_path, rebuild=False, cfg=None):
            called["ok"] = (papers_dir, db_path, rebuild)
            return 5

        monkeypatch.setattr("scholaraio.vectors.build_chunk_vectors", _fake_build_chunk_vectors)
        messages: list[str] = []
        monkeypatch.setattr(cli, "ui", messages.append)

        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = Namespace(rebuild=False, chunks=True)
        cli.cmd_index(args, cfg)

        assert called["ok"] == (tmp_papers, tmp_db, False)
        assert any("段落向量索引" in m for m in messages)

    def test_cmd_search_chunk_uses_chunk_search(self, tmp_db, monkeypatch):
        monkeypatch.setattr("scholaraio.metrics.get_store", lambda: None)
        monkeypatch.setattr("scholaraio.vectors.chunk_search", lambda *a, **k: [{"paper_id": "aaaa-1111", "dir_name": "P1", "title": "T", "authors": "A", "year": "2023", "journal": "J", "section_title": "Intro", "start_line": 1, "end_line": 3, "score": 0.7}])

        printed: list[tuple[int, dict, str]] = []
        monkeypatch.setattr(cli, "_print_search_result", lambda idx, r, extra="": printed.append((idx, r, extra)))
        monkeypatch.setattr(cli, "_print_search_next_steps", lambda include_ws_add=True: None)
        monkeypatch.setattr(cli, "ui", lambda msg="": None)

        cfg = SimpleNamespace(index_db=tmp_db, search=SimpleNamespace(top_k=5))
        args = Namespace(
            query=["test"],
            top=1,
            year=None,
            journal=None,
            paper_type=None,
            chunk=True,
            aggregate=False,
        )
        cli.cmd_search(args, cfg)

        assert printed
        assert "L1-3" in printed[0][2]
