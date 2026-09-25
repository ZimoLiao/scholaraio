from __future__ import annotations

import json
from pathlib import Path

import scholaraio.core.log as target_log
from scholaraio.core.config import _build_config
from scholaraio.interfaces.cli import compat as cli
from scholaraio.services.index import build_proceedings_index, search_proceedings
from scholaraio.services.ingest import pipeline
from scholaraio.services.ingest.pipeline import run_pipeline
from scholaraio.services.ingest.proceedings_volume import (
    apply_proceedings_clean_plan,
    apply_proceedings_split_plan,
    build_proceedings_clean_candidates,
    ingest_proceedings_markdown,
)
from scholaraio.stores.proceedings import iter_proceedings_dirs, iter_proceedings_papers, proceedings_db_path


def _write_proceedings_fixture(root: Path) -> Path:
    proceedings_root = root / "proceedings"
    proceedings_dir = proceedings_root / "Zheng-2024-IUTAM"
    papers_dir = proceedings_dir / "papers"
    papers_dir.mkdir(parents=True)

    (proceedings_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "proc-1",
                "title": "Example Proceedings",
                "year": 2024,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    paper_a = papers_dir / "Alpha-2024-Waves"
    paper_a.mkdir()
    (paper_a / "meta.json").write_text(
        json.dumps(
            {
                "id": "proc-paper-1",
                "title": "Wave propagation in porous media",
                "authors": ["Alice Zheng"],
                "year": 2024,
                "doi": "10.1000/example.1",
                "abstract": "Wave propagation in porous media with granular damping.",
                "paper_type": "conference-paper",
                "proceeding_title": "Example Proceedings",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (paper_a / "paper.md").write_text("# Wave propagation in porous media", encoding="utf-8")

    paper_b = papers_dir / "Beta-2024-Shocks"
    paper_b.mkdir()
    (paper_b / "meta.json").write_text(
        json.dumps(
            {
                "id": "proc-paper-2",
                "title": "Shock response of cellular materials",
                "authors": ["Bo Li"],
                "year": 2024,
                "doi": "10.1000/example.2",
                "abstract": "Shock response and granular collapse under impact.",
                "paper_type": "conference-paper",
                "proceeding_title": "Example Proceedings",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (paper_b / "paper.md").write_text("# Shock response of cellular materials", encoding="utf-8")

    return proceedings_root


def _first_proceeding_dir(proceedings_root: Path) -> Path:
    return next(iter_proceedings_dirs(proceedings_root))


def test_iter_proceedings_papers_yields_child_rows(tmp_path: Path):
    proceedings_root = _write_proceedings_fixture(tmp_path)

    papers = list(iter_proceedings_papers(proceedings_root))

    assert len(papers) == 2
    assert {p["proceeding_title"] for p in papers} == {"Example Proceedings"}
    assert {p["paper_id"] for p in papers} == {"proc-paper-1", "proc-paper-2"}


def test_build_and_search_proceedings_index_returns_matching_child_rows(tmp_path: Path):
    proceedings_root = _write_proceedings_fixture(tmp_path)
    db_path = tmp_path / "proceedings.db"

    count = build_proceedings_index(proceedings_root, db_path, rebuild=True)
    results = search_proceedings("granular", db_path, top_k=10)

    assert count == 2
    assert len(results) == 2
    assert {r["proceeding_title"] for r in results} == {"Example Proceedings"}
    assert {r["paper_id"] for r in results} == {"proc-paper-1", "proc-paper-2"}


def test_proceedings_db_path_defaults_to_durable_library_only(tmp_path: Path):
    assert (
        proceedings_db_path(tmp_path) == (tmp_path / "data" / "libraries" / "proceedings" / "proceedings.db").resolve()
    )

    target_db = tmp_path / "data" / "libraries" / "proceedings" / "proceedings.db"
    target_db.parent.mkdir(parents=True)
    target_db.write_text("", encoding="utf-8")

    assert proceedings_db_path(tmp_path) == target_db.resolve()


def test_build_proceedings_index_incremental_mode_replaces_existing_rows(tmp_path: Path):
    proceedings_root = _write_proceedings_fixture(tmp_path)
    db_path = tmp_path / "proceedings.db"

    first = build_proceedings_index(proceedings_root, db_path, rebuild=True)
    second = build_proceedings_index(proceedings_root, db_path, rebuild=False)
    results = search_proceedings("granular", db_path, top_k=10)

    assert first == 2
    assert second == 2
    assert len(results) == 2


def test_build_proceedings_index_incremental_mode_replaces_rows_after_paper_id_changes(tmp_path: Path):
    proceedings_root = _write_proceedings_fixture(tmp_path)
    db_path = tmp_path / "proceedings.db"
    papers_dir = proceedings_root / "Zheng-2024-IUTAM" / "papers"

    first = build_proceedings_index(proceedings_root, db_path, rebuild=True)

    alpha_meta_path = papers_dir / "Alpha-2024-Waves" / "meta.json"
    alpha_meta = json.loads(alpha_meta_path.read_text(encoding="utf-8"))
    alpha_meta["id"] = "proc-paper-1-rebuilt"
    alpha_meta_path.write_text(json.dumps(alpha_meta, ensure_ascii=False), encoding="utf-8")

    second = build_proceedings_index(proceedings_root, db_path, rebuild=False)
    results = search_proceedings("granular", db_path, top_k=10)

    assert first == 2
    assert second == 2
    assert len(results) == 2
    assert {r["paper_id"] for r in results} == {"proc-paper-1-rebuilt", "proc-paper-2"}


def test_build_proceedings_index_incremental_mode_removes_deleted_volume_rows(tmp_path: Path):
    proceedings_root = _write_proceedings_fixture(tmp_path)
    db_path = tmp_path / "proceedings.db"

    first = build_proceedings_index(proceedings_root, db_path, rebuild=True)

    volume_dir = proceedings_root / "Zheng-2024-IUTAM"
    for path in sorted((volume_dir / "papers").rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    (volume_dir / "papers").rmdir()
    (volume_dir / "meta.json").unlink()
    volume_dir.rmdir()

    second = build_proceedings_index(proceedings_root, db_path, rebuild=False)
    results = search_proceedings("granular", db_path, top_k=10)

    assert first == 2
    assert second == 0
    assert results == []


def test_ingest_proceedings_markdown_writes_volume_and_child_papers(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "## Paper: Wave propagation in porous media\n"
        "Alice Zheng\n"
        "10.1000/example.1\n"
        "Wave propagation in porous media with granular damping.\n\n"
        "## Paper: Shock response of cellular materials\n"
        "Bo Li\n"
        "10.1000/example.2\n"
        "Shock response and collapse under granular impact.\n",
        encoding="utf-8",
    )

    proceeding_dir = ingest_proceedings_markdown(
        proceedings_root,
        md_path,
        source_name="Zheng-2024-Proceedings of the IUTAM Symposium.pdf",
    )

    meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))

    assert proceeding_dir.exists()
    assert meta["child_paper_count"] == 0
    assert meta["split_status"] == "pending_review"
    assert (proceeding_dir / "split_candidates.json").exists()


def test_apply_proceedings_split_plan_writes_child_papers(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Wave propagation in porous media\n"
        "Alice Zheng\n"
        "Abstract. Wave propagation in porous media with granular damping.\n\n"
        "# 1 Introduction\nBody A\n\n"
        "# Shock response of cellular materials\n"
        "Bo Li\n"
        "Abstract. Shock response and collapse under granular impact.\n\n"
        "# 1 Introduction\nBody B\n",
        encoding="utf-8",
    )

    proceeding_dir = ingest_proceedings_markdown(
        proceedings_root,
        md_path,
        source_name="Zheng-2024-Proceedings of the IUTAM Symposium.pdf",
    )
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [
                {"title": "Wave propagation in porous media", "start_line": 3, "end_line": 8},
                {"title": "Shock response of cellular materials", "start_line": 9, "end_line": 14},
            ],
        },
    )

    meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
    child_dirs = sorted((proceeding_dir / "papers").iterdir())
    child_meta = json.loads((child_dirs[0] / "meta.json").read_text(encoding="utf-8"))

    assert meta["child_paper_count"] == 2
    assert meta["split_status"] == "applied"
    assert child_meta["proceeding_title"] == meta["title"]
    assert len(child_dirs) == 2


def test_apply_proceedings_split_plan_skips_affiliation_lines_before_abstract(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Snow settling in turbulence\n"
        "Jiaqi Li and Jiarong Hong\n\n"
        "Saint Anthony Falls Laboratory, University of Minnesota\n\n"
        "Abstract. This paper studies snow settling in atmospheric turbulence.\n\n"
        "# 1 Introduction\nBody\n",
        encoding="utf-8",
    )

    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [{"title": "Snow settling in turbulence", "start_line": 3, "end_line": 9}],
        },
    )

    paper_dir = next((proceeding_dir / "papers").iterdir())
    meta = json.loads((paper_dir / "meta.json").read_text(encoding="utf-8"))

    assert meta["authors"] == ["Jiaqi Li and Jiarong Hong"]
    assert meta["abstract"] == "This paper studies snow settling in atmospheric turbulence."


def test_apply_proceedings_split_plan_skips_comment_label_and_case_variant_heading(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# CAN DYNAMICAL SYSTEMS APPROACH TURBULENCE?\n"
        "Comment 2.\n"
        "Philip Holmes\n"
        "Abstract. This paper reviews dynamical systems ideas for turbulence.\n",
        encoding="utf-8",
    )

    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [{"title": "Can Dynamical Systems Approach Turbulence?", "start_line": 3, "end_line": 6}],
        },
    )

    paper_dir = next((proceeding_dir / "papers").iterdir())
    meta = json.loads((paper_dir / "meta.json").read_text(encoding="utf-8"))

    assert meta["authors"] == ["Philip Holmes"]
    assert meta["abstract"] == "This paper reviews dynamical systems ideas for turbulence."


def test_apply_proceedings_split_plan_tolerates_minor_heading_spacing_noise(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# CAN DYNAMICAL SYSTEMSAPPROACH TURBULENCE?\n"
        "Philip Holmes\n"
        "Abstract. This paper reviews dynamical systems ideas for turbulence.\n",
        encoding="utf-8",
    )

    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [{"title": "Can Dynamical Systems Approach Turbulence?", "start_line": 3, "end_line": 5}],
        },
    )

    paper_dir = next((proceeding_dir / "papers").iterdir())
    meta = json.loads((paper_dir / "meta.json").read_text(encoding="utf-8"))

    assert meta["authors"] == ["Philip Holmes"]


def test_apply_proceedings_split_plan_skips_comment_label_variant_and_heading_abstract(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Cellular Automata and Massively Parallel Physics\n"
        "Comment 2. +\n"
        "C.E.Leith\n"
        "# Abstract\n"
        "This paper discusses cellular automata for turbulence simulations.\n",
        encoding="utf-8",
    )

    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [{"title": "Cellular Automata and Massively Parallel Physics", "start_line": 3, "end_line": 7}],
        },
    )

    paper_dir = next((proceeding_dir / "papers").iterdir())
    meta = json.loads((paper_dir / "meta.json").read_text(encoding="utf-8"))

    assert meta["authors"] == ["C.E.Leith"]
    assert meta["abstract"] == "This paper discusses cellular automata for turbulence simulations."


def test_apply_proceedings_split_plan_handles_second_level_abstract_heading(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Cellular Automata and Massively Parallel Physics\n"
        "C.E.Leith\n"
        "## Abstract\n"
        "This paper discusses cellular automata for turbulence simulations.\n",
        encoding="utf-8",
    )

    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [{"title": "Cellular Automata and Massively Parallel Physics", "start_line": 3, "end_line": 6}],
        },
    )

    paper_dir = next((proceeding_dir / "papers").iterdir())
    meta = json.loads((paper_dir / "meta.json").read_text(encoding="utf-8"))

    assert meta["abstract"] == "This paper discusses cellular automata for turbulence simulations."


def test_ingest_proceedings_markdown_prepares_realistic_contents_style_volume(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Editors Name\n\n"
        "# Proceedings of the IUTAM Symposium on Turbulent Structure and Particles-Turbulence Interaction\n\n"
        "# Contents\n\n"
        "Two-Phase Structures in High-Reynolds-Number Sand-Laden Wall-Bounded Turbulence 1 "
        "Xiaojing Zheng, Yanxiong Shi, and Hongyou Liu\n\n"
        "Wake of a Finite-Size Particle in Wall Turbulence Over a Rough Bed 16 "
        "Xing Li, S. Balachandar, Hyungoo Lee, and Bofeng Bai\n\n"
        "# Two-Phase Structures in High-Reynolds-Number Sand-Laden Wall-Bounded Turbulence\n\n"
        "Xiaojing Zheng, Yanxiong Shi, and Hongyou Liu\n\n"
        "Abstract. Sandstorms are a gas-solid two-phase wall turbulence.\n\n"
        "# 1 Introduction\n\n"
        "Body A\n\n"
        "# References\n\n"
        "10.1000/example.1\n\n"
        "# Wake of a Finite-Size Particle in Wall Turbulence Over a Rough Bed\n\n"
        "Xing Li, S. Balachandar, Hyungoo Lee, and Bofeng Bai\n\n"
        "Abstract. This paper studies the wake of a finite-size particle.\n\n"
        "# 1 Introduction\n\n"
        "Body B\n\n"
        "# References\n\n"
        "10.1000/example.2\n",
        encoding="utf-8",
    )

    proceeding_dir = ingest_proceedings_markdown(
        proceedings_root,
        md_path,
        source_name="realistic.pdf",
    )

    meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))

    assert (
        meta["title"]
        == "Proceedings of the IUTAM Symposium on Turbulent Structure and Particles-Turbulence Interaction"
    )
    assert meta["child_paper_count"] == 0
    assert meta["split_status"] == "pending_review"
    assert (proceeding_dir / "split_candidates.json").exists()


def test_split_candidates_include_case_insensitive_normalized_titles(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Contents\n\n"
        "Wake of a Finite-Size Particle in WALL Turbulence Over a Rough Bed 16 Xing Li\n\n"
        "# Wake of a Finite-Size Particle in Wall Turbulence Over a Rough Bed\n\n"
        "Xing Li\n\n"
        "Abstract. Example.\n",
        encoding="utf-8",
    )

    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    candidates = json.loads((proceeding_dir / "split_candidates.json").read_text(encoding="utf-8"))
    heading = next(
        item
        for item in candidates["headings"]
        if item["text"] == "Wake of a Finite-Size Particle in Wall Turbulence Over a Rough Bed"
    )

    assert candidates["normalized_contents_titles"][0] == heading["normalized_text"]


def test_split_candidates_extract_titles_from_table_of_contents_heading_variant(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Table of Contents\n\n"
        "Wake of a Finite-Size Particle in Wall Turbulence Over a Rough Bed 16 Xing Li\n\n"
        "# Wake of a Finite-Size Particle in Wall Turbulence Over a Rough Bed\n\n"
        "Xing Li\n\n"
        "Abstract. Example.\n",
        encoding="utf-8",
    )

    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    candidates = json.loads((proceeding_dir / "split_candidates.json").read_text(encoding="utf-8"))

    assert candidates["contents_titles"] == ["Wake of a Finite-Size Particle in Wall Turbulence Over a Rough Bed"]


def test_pipeline_routes_manual_proceedings_inbox_to_proceedings_library(tmp_path: Path):
    cfg = _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
    cfg.ensure_dirs()
    md_path = cfg.proceedings_inbox_dir / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "## Paper: Wave propagation in porous media\nAlice Zheng\n10.1000/example.1\nBody\n",
        encoding="utf-8",
    )

    run_pipeline(["extract", "dedup", "ingest"], cfg, {"no_api": True})

    assert any(iter_proceedings_dirs(cfg.proceedings_dir))
    assert not any(cfg.papers_dir.iterdir())
    proceeding_dir = _first_proceeding_dir(cfg.proceedings_dir)
    meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["split_status"] == "pending_review"


def test_pipeline_routes_manual_proceedings_inbox_to_configured_proceedings_library(tmp_path: Path):
    cfg = _build_config(
        {
            "ingest": {"extractor": "regex"},
            "paths": {
                "proceedings_inbox_dir": "queues/inbox-proceedings",
                "proceedings_dir": "libraries/proceedings",
            },
        },
        tmp_path,
    )
    cfg.ensure_dirs()
    md_path = cfg.proceedings_inbox_dir / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "## Paper: Wave propagation in porous media\nAlice Zheng\n10.1000/example.1\nBody\n",
        encoding="utf-8",
    )

    run_pipeline(["extract", "dedup", "ingest"], cfg, {"no_api": True})

    assert any(iter_proceedings_dirs(cfg.proceedings_dir))
    assert not any(cfg.papers_dir.iterdir())
    proceeding_dir = _first_proceeding_dir(cfg.proceedings_dir)
    meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["split_status"] == "pending_review"


def test_pipeline_routes_forced_proceedings_pdf_right_after_mineru(tmp_path: Path, monkeypatch):
    cfg = _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
    cfg.ensure_dirs()
    pdf_path = cfg.proceedings_inbox_dir / "volume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake proceedings")

    def fake_mineru(ctx: pipeline.InboxCtx) -> pipeline.StepResult:
        md_path = ctx.inbox_dir / (ctx.pdf_path.stem + ".md")
        md_path.write_text(
            "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
            "# Contents\n\n"
            "Wave propagation in porous media 1 Alice Zheng\n\n"
            "# Wave propagation in porous media\n"
            "Alice Zheng\n"
            "Abstract. Granular damping in porous waves.\n",
            encoding="utf-8",
        )
        ctx.md_path = md_path
        return pipeline.StepResult.OK

    def fail_if_called(_ctx: pipeline.InboxCtx) -> pipeline.StepResult:
        raise AssertionError("regular paper flow should not continue after forced proceedings routing")

    from scholaraio.providers import mineru as mineru_mod

    monkeypatch.setattr(mineru_mod, "check_server", lambda _endpoint: True)
    monkeypatch.setattr(pipeline.STEPS["mineru"], "fn", fake_mineru)
    monkeypatch.setattr(pipeline.STEPS["extract"], "fn", fail_if_called)
    monkeypatch.setattr(pipeline.STEPS["dedup"], "fn", fail_if_called)
    monkeypatch.setattr(pipeline.STEPS["ingest"], "fn", fail_if_called)

    run_pipeline(["mineru", "extract", "dedup", "ingest"], cfg, {"no_api": True})

    assert any(iter_proceedings_dirs(cfg.proceedings_dir))
    assert not any(cfg.papers_dir.iterdir())
    proceeding_dir = _first_proceeding_dir(cfg.proceedings_dir)
    meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["split_status"] == "pending_review"


def test_pipeline_regular_inbox_never_auto_routes_to_proceedings(tmp_path: Path):
    cfg = _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
    cfg.ensure_dirs()
    md_path = cfg.inbox_dir / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "Alice Zheng\n\n"
        "10.1000/example.1\n\n"
        "## Table of Contents\n10.1000/example.1\n10.1000/example.2\n\n"
        "This regular inbox item should stay on the normal paper path unless it is placed in inbox-proceedings.\n",
        encoding="utf-8",
    )

    run_pipeline(["extract", "dedup", "ingest"], cfg, {"no_api": True, "include_aux_inboxes": False})

    assert any(cfg.papers_dir.iterdir())
    assert not any(cfg.proceedings_dir.iterdir())


def test_pipeline_does_not_auto_route_thesis_inbox_to_proceedings(tmp_path: Path):
    cfg = _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
    cfg.ensure_dirs()
    md_path = cfg.thesis_inbox_dir / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "## Table of Contents\n10.1000/example.1\n10.1000/example.2\n\n"
        "Alice Zheng\n\n"
        "This thesis-like item should stay in the thesis flow.\n",
        encoding="utf-8",
    )

    run_pipeline(["extract", "dedup", "ingest"], cfg, {"no_api": True})

    assert any(cfg.papers_dir.iterdir())
    assert not any(cfg.proceedings_dir.iterdir())


def test_pipeline_does_not_auto_route_patent_inbox_to_proceedings(tmp_path: Path):
    cfg = _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
    cfg.ensure_dirs()
    md_path = cfg.patent_inbox_dir / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "Publication Number: CN112345678A\n\n"
        "## Table of Contents\n10.1000/example.1\n10.1000/example.2\n",
        encoding="utf-8",
    )

    run_pipeline(["extract", "dedup", "ingest"], cfg, {"no_api": True})

    assert any(cfg.papers_dir.iterdir())
    assert not any(cfg.proceedings_dir.iterdir())


def test_pipeline_keeps_regular_paper_in_main_library(tmp_path: Path):
    cfg = _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
    cfg.ensure_dirs()
    md_path = cfg.inbox_dir / "paper.md"
    md_path.write_text(
        "# Boundary layer instability in compressible flow\n\n"
        "Alice Smith\n\n"
        "10.1000/example.single\n\n"
        "This paper studies a single wave packet.\n",
        encoding="utf-8",
    )

    run_pipeline(["extract", "dedup", "ingest"], cfg, {"no_api": True, "include_aux_inboxes": False})

    assert any(cfg.papers_dir.iterdir())
    assert not any(cfg.proceedings_dir.iterdir())


def test_fsearch_proceedings_scope_returns_proceedings_results(tmp_path: Path, monkeypatch):
    cfg = _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
    cfg.ensure_dirs()
    proceedings_root = cfg.proceedings_dir
    proceedings_root.mkdir(parents=True, exist_ok=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Wave propagation in porous media\nAlice Zheng\nAbstract. Granular damping in porous waves.\n\n# 1 Introduction\nBody\n",
        encoding="utf-8",
    )
    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [{"title": "Wave propagation in porous media", "start_line": 3, "end_line": 6}],
        },
    )

    messages: list[str] = []
    monkeypatch.setattr(target_log, "ui", lambda message="": messages.append(message))

    cli.cmd_fsearch(type("Args", (), {"query": ["granular"], "scope": "proceedings", "top": 10})(), cfg)

    joined = "\n".join(messages)
    assert "-- [Proceedings] --" in joined
    assert "proceedings:" in joined
    assert "Wave propagation in porous media" in joined


def test_fsearch_main_scope_excludes_proceedings_results(tmp_path: Path, monkeypatch):
    cfg = _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
    cfg.ensure_dirs()

    messages: list[str] = []
    monkeypatch.setattr(target_log, "ui", lambda message="": messages.append(message))

    cli.cmd_fsearch(type("Args", (), {"query": ["granular"], "scope": "main", "top": 10})(), cfg)

    joined = "\n".join(messages)
    assert "-- [Main library] --" in joined
    assert "proceedings:" not in joined


def test_cli_proceedings_apply_split_applies_plan_and_reports_success(tmp_path: Path, monkeypatch):
    cfg = _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
    cfg.ensure_dirs()
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True, exist_ok=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Wave propagation in porous media\n"
        "Alice Zheng\n"
        "Abstract. Granular damping in porous waves.\n\n"
        "# 1 Introduction\n"
        "Body\n",
        encoding="utf-8",
    )
    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    split_plan_path = tmp_path / "split_plan.json"
    split_plan_path.write_text(
        json.dumps(
            {
                "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
                "papers": [{"title": "Wave propagation in porous media", "start_line": 3, "end_line": 8}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    parser = cli._build_parser()
    args = parser.parse_args(["proceedings", "apply-split", str(proceeding_dir), str(split_plan_path)])
    messages: list[str] = []
    monkeypatch.setattr(target_log, "ui", lambda message="": messages.append(message))

    args.func(args, cfg)

    meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
    child_dirs = sorted((proceeding_dir / "papers").iterdir())
    joined = "\n".join(messages)

    assert meta["split_status"] == "applied"
    assert meta["child_paper_count"] == 1
    assert len(child_dirs) == 1
    assert "Applied proceedings split plan" in joined


def test_apply_proceedings_split_plan_rejects_empty_result_without_deleting_existing_papers(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True, exist_ok=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Wave propagation in porous media\nAlice Zheng\nAbstract. Granular damping in porous waves.\n",
        encoding="utf-8",
    )
    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [{"title": "Wave propagation in porous media", "start_line": 3, "end_line": 4}],
        },
    )

    existing_dirs = sorted((proceeding_dir / "papers").iterdir())

    try:
        apply_proceedings_split_plan(
            proceeding_dir,
            {
                "volume_title": "Broken Plan",
                "papers": [{"title": "Missing paper", "start_line": 999, "end_line": 1001}],
            },
        )
    except ValueError as exc:
        assert "did not produce any child papers" in str(exc)
    else:
        raise AssertionError("expected ValueError for empty split plan result")

    assert sorted((proceeding_dir / "papers").iterdir()) == existing_dirs


def test_build_proceedings_clean_candidates_flags_structural_issues(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True, exist_ok=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Discussion of Large Eddy Simulation\n"
        "Reporter Laurence Keefe\n"
        "Question and answer transcript.\n\n"
        "# Wave propagation in porous media\n"
        "Alice Zheng\n"
        "Abstract. Granular damping in porous waves.\n",
        encoding="utf-8",
    )
    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [
                {"title": "Discussion of Large Eddy Simulation", "start_line": 3, "end_line": 5},
                {"title": "Wave propagation in porous media", "start_line": 6, "end_line": 8},
            ],
        },
    )

    candidates_path = build_proceedings_clean_candidates(proceeding_dir)
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    discussion = next(item for item in candidates["papers"] if item["title"] == "Discussion of Large Eddy Simulation")
    regular = next(item for item in candidates["papers"] if item["title"] == "Wave propagation in porous media")

    assert "discussion_title" in discussion["signals"]
    assert "missing_abstract" in discussion["signals"]
    assert "missing_authors" not in regular["signals"]
    assert regular["paper_type"] == "conference-paper"


def test_apply_proceedings_clean_plan_renames_drops_and_reclassifies(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True, exist_ok=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Discussion of Large Eddy Simulation\n"
        "Reporter Laurence Keefe\n"
        "Question and answer transcript.\n\n"
        "# Wave propagation in porous media\n"
        "Alice Zheng\n"
        "Abstract. Granular damping in porous waves.\n",
        encoding="utf-8",
    )
    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [
                {"title": "Discussion of Large Eddy Simulation", "start_line": 3, "end_line": 5},
                {"title": "Wave propagation in porous media", "start_line": 6, "end_line": 8},
            ],
        },
    )

    apply_proceedings_clean_plan(
        proceeding_dir,
        {
            "volume_title": "Granular Flow Workshop",
            "papers": [
                {"paper": "Discussion of Large Eddy Simulation", "action": "drop"},
                {
                    "paper": "wave propagation in porous media",
                    "action": "rename",
                    "title": "Wave Propagation in Porous Media (Position Paper)",
                    "paper_type": "position-paper",
                },
            ],
        },
    )

    meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
    child_dirs = sorted((proceeding_dir / "papers").iterdir())
    child_meta = json.loads((child_dirs[0] / "meta.json").read_text(encoding="utf-8"))
    results = search_proceedings("porous", proceedings_root / "proceedings.db", top_k=10)

    assert meta["title"] == "Granular Flow Workshop"
    assert meta["child_paper_count"] == 1
    assert child_meta["title"] == "Wave Propagation in Porous Media (Position Paper)"
    assert child_meta["paper_type"] == "position-paper"
    assert child_meta["proceeding_title"] == "Granular Flow Workshop"
    assert child_dirs[0].name == "Wave-Propagation-in-Porous-Media-Position-Paper"
    assert {row["proceeding_title"] for row in results} == {"Granular Flow Workshop"}


def test_apply_proceedings_clean_plan_removes_bogus_heading_tags_without_touching_body(tmp_path: Path):
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True, exist_ok=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Cellular Automata and Massively Parallel Physics\n"
        "C.E.Leith\n"
        "Abstract. This paper discusses cellular automata for turbulence simulations.\n\n"
        "# Comment 2.\n"
        "# Reporter Laurence Keefe\n"
        "Body paragraph.\n",
        encoding="utf-8",
    )
    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [{"title": "Cellular Automata and Massively Parallel Physics", "start_line": 3, "end_line": 9}],
        },
    )

    apply_proceedings_clean_plan(
        proceeding_dir,
        {
            "papers": [
                {
                    "paper": "Cellular Automata and Massively Parallel Physics",
                    "action": "keep",
                    "remove_headings": ["Comment 2.", "Reporter Laurence Keefe"],
                }
            ]
        },
    )

    paper_dir = next((proceeding_dir / "papers").iterdir())
    paper_md = (paper_dir / "paper.md").read_text(encoding="utf-8")

    assert "# Comment 2." not in paper_md
    assert "# Reporter Laurence Keefe" not in paper_md
    assert "Body paragraph." in paper_md
    assert "Abstract. This paper discusses cellular automata for turbulence simulations." in paper_md


def test_cli_proceedings_clean_commands_build_and_apply(tmp_path: Path, monkeypatch):
    cfg = _build_config({"ingest": {"extractor": "regex"}}, tmp_path)
    cfg.ensure_dirs()
    proceedings_root = tmp_path / "data" / "proceedings"
    proceedings_root.mkdir(parents=True, exist_ok=True)
    md_path = tmp_path / "volume.md"
    md_path.write_text(
        "# Proceedings of the IUTAM Symposium on Granular Flow\n\n"
        "# Discussion of Large Eddy Simulation\n"
        "Reporter Laurence Keefe\n"
        "Question and answer transcript.\n",
        encoding="utf-8",
    )
    proceeding_dir = ingest_proceedings_markdown(proceedings_root, md_path, source_name="volume.pdf")
    apply_proceedings_split_plan(
        proceeding_dir,
        {
            "volume_title": "Proceedings of the IUTAM Symposium on Granular Flow",
            "papers": [{"title": "Discussion of Large Eddy Simulation", "start_line": 3, "end_line": 5}],
        },
    )

    parser = cli._build_parser()
    messages: list[str] = []
    monkeypatch.setattr(target_log, "ui", lambda message="": messages.append(message))

    args = parser.parse_args(["proceedings", "build-clean-candidates", str(proceeding_dir)])
    args.func(args, cfg)
    candidates_path = proceeding_dir / "clean_candidates.json"
    assert candidates_path.exists()

    clean_plan_path = tmp_path / "clean_plan.json"
    clean_plan_path.write_text(
        json.dumps(
            {"papers": [{"paper": "discussion of large eddy simulation", "action": "drop"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args = parser.parse_args(["proceedings", "apply-clean", str(proceeding_dir), str(clean_plan_path)])
    args.func(args, cfg)

    joined = "\n".join(messages)
    meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))

    assert "Generated proceedings clean candidates" in joined
    assert "Applied proceedings clean plan" in joined
    assert meta["child_paper_count"] == 0
