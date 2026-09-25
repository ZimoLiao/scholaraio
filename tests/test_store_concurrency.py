"""Exercise real cross-process record transactions, including lost updates."""

import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

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
