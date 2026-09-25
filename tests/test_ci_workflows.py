from __future__ import annotations

from pathlib import Path

import yaml


def test_macos_semantic_smoke_workflow_runs_issue_search_commands() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/macos-semantic-smoke.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["semantic-smoke"]["steps"]

    smoke_step = next(step for step in steps if step.get("name") == "Smoke test issue-65 explore search flow")
    run_script = smoke_step["run"]

    assert "scholaraio explore embed --name issue-65-smoke" in run_script
    assert 'scholaraio explore search --name issue-65-smoke "boundary layer turbulence" --mode semantic' in run_script
    assert 'scholaraio explore search --name issue-65-smoke "boundary layer turbulence" --mode unified' in run_script
    assert 'grep -q "score:" "$SMOKE_ROOT/semantic.out"' in run_script
    assert 'grep -q "score:" "$SMOKE_ROOT/unified.out"' in run_script
    assert "分数:" not in run_script


def test_macos_smoke_paths_cover_canonical_modules():
    import fnmatch

    workflow = yaml.safe_load(Path(".github/workflows/macos-semantic-smoke.yml").read_text())
    events = workflow.get("on", workflow.get(True))  # PyYAML YAML 1.1 parses on as True.
    for event in ("push", "pull_request"):
        paths = events[event]["paths"]
        for pattern in paths:
            if "*" not in pattern:
                assert Path(pattern).is_file(), pattern
        for canonical in (
            "scholaraio/services/index.py",
            "scholaraio/services/vectors.py",
            "scholaraio/stores/explore.py",
            "scholaraio/interfaces/cli/retrieval.py",
        ):
            assert any(fnmatch.fnmatch(canonical, pattern) for pattern in paths), canonical
