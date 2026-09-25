"""Exercise real cross-process record transactions, including lost updates."""

import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from scholaraio.projects.workspace import add, create
from scholaraio.stores.papers import modify_meta, read_meta, update_meta, write_meta


def _increment(path: str) -> None:
    for _ in range(10):
        modify_meta(Path(path), lambda meta: meta.update(count=meta["count"] + 1))


def _add_reference(args: tuple[str, int]) -> None:
    path, number = args
    add(Path(path), [], Path(path) / "unused.db", resolved=[{"id": str(number), "dir_name": str(number)}])


def test_metadata_processes_do_not_lose_updates(tmp_path):
    write_meta(tmp_path, {"id": "test", "count": 0, "title": "Preserved"})
    with ProcessPoolExecutor(4, mp_context=multiprocessing.get_context("spawn")) as pool:
        list(pool.map(_increment, [str(tmp_path)] * 4))
    assert read_meta(tmp_path)["count"] == 40
    update_meta(tmp_path, abstract="New abstract")
    assert read_meta(tmp_path)["title"] == "Preserved"
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_workspace_processes_do_not_lose_added_references(tmp_path):
    create(tmp_path)
    with ProcessPoolExecutor(4, mp_context=multiprocessing.get_context("spawn")) as pool:
        list(pool.map(_add_reference, [(str(tmp_path), n) for n in range(16)]))
    entries = json.loads((tmp_path / "refs" / "papers.json").read_text())
    assert {entry["id"] for entry in entries} == {str(n) for n in range(16)}


def test_metadata_writer_does_not_recreate_a_missing_paper_directory(tmp_path):
    import pytest

    missing = tmp_path / "renamed-away"
    with pytest.raises(FileNotFoundError):
        write_meta(missing, {"id": "stale"})
    assert not missing.exists()


def test_rename_waits_for_an_active_metadata_transaction(tmp_path):
    import threading
    import time

    from scholaraio.core.fileio import file_lock
    from scholaraio.services.ingest_metadata import rename_paper

    paper = tmp_path / "Original"
    paper.mkdir()
    write_meta(paper, {"id": "paper", "title": "Renamed", "year": 2026})
    started = threading.Event()
    result = []

    def rename():
        started.set()
        result.append(rename_paper(paper / "meta.json"))

    with file_lock(paper / "meta.json"):
        thread = threading.Thread(target=rename)
        thread.start()
        assert started.wait(2)
        time.sleep(0.05)
        assert paper.exists()
        assert result == []
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(result) == 1
    assert result[0].exists()


def test_workspace_refresh_serializes_with_add(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from scholaraio.projects.workspace import show
    from scholaraio.services import index

    create(tmp_path)
    add(tmp_path, [], tmp_path / "unused.db", resolved=[{"id": "A", "dir_name": "old"}])
    refreshing = threading.Event()
    release = threading.Event()

    def lookup(*_args):
        refreshing.set()
        assert release.wait(5)
        return {"dir_name": "new"}

    monkeypatch.setattr(index, "lookup_paper", lookup)
    with ThreadPoolExecutor(2) as pool:
        refresh = pool.submit(show, tmp_path, tmp_path / "unused.db")
        assert refreshing.wait(5)
        adding = pool.submit(_add_reference, (str(tmp_path), 2))
        try:
            import concurrent.futures

            with pytest.raises(concurrent.futures.TimeoutError):
                adding.result(timeout=0.1)
        finally:
            release.set()
        refresh.result(timeout=5)
        adding.result(timeout=5)
    entries = json.loads((tmp_path / "refs" / "papers.json").read_text())
    assert {entry["id"] for entry in entries} == {"A", "2"}
    assert entries[0]["dir_name"] == "new"


def test_rename_new_path_waits_for_registry_commit(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor, TimeoutError

    import pytest

    from scholaraio.services.ingest_metadata import _writer

    paper = tmp_path / "Original"
    paper.mkdir()
    write_meta(paper, {"id": "paper", "title": "First", "year": 2026})
    moved = threading.Event()
    release = threading.Event()
    commits = []

    def commit(_db, _id, directory):
        if not commits:
            moved.set()
            assert release.wait(5)
        commits.append(directory)

    monkeypatch.setattr(_writer, "_update_registry_dir_name", commit)
    first_path = tmp_path / "Unknown-2026-First"

    def second_rename():
        update_meta(first_path, title="Second")
        return _writer.rename_paper(first_path / "meta.json")

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(_writer.rename_paper, paper / "meta.json")
        assert moved.wait(5)
        second = pool.submit(second_rename)
        try:
            with pytest.raises(TimeoutError):
                second.result(timeout=0.1)
        finally:
            release.set()
        first.result(timeout=5)
        final = second.result(timeout=5)
    assert final.exists()
    assert commits[-1] == final.parent
    assert [p.name for p in commits] == ["Unknown-2026-First", "Unknown-2026-Second"]
