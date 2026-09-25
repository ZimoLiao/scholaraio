"""Migration-control CLI command handler."""

from __future__ import annotations

import argparse
import logging
import sys


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def _log_error(msg: str, *args) -> None:
    logging.getLogger(__name__).error(msg, *args)


def cmd_migrate(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.migration_control import (
        clear_migration_lock,
        describe_migration_lock,
        ensure_instance_metadata,
        list_migration_journals,
        mark_instance_layout_state,
        read_instance_metadata,
        read_latest_cleanup_step,
        read_migration_verify,
        resolve_migration_journal,
        run_migration_cleanup,
        run_migration_finalize,
        run_migration_plan,
        run_migration_store,
        run_migration_upgrade,
        run_migration_verification,
    )

    action = getattr(args, "migrate_action", None)
    if action == "plan":
        result = run_migration_plan(cfg, getattr(args, "migration_id", None))
        journal_dir = cfg.migration_journals_root / result["migration_id"]
        _ui(f"Plan completed: {result['migration_id']}")
        _ui(f"  plan_json: {journal_dir / 'plan.json'}")
        _ui(f"  blockers: {len(result['blockers'])}")
        _ui(f"  papers: {result['stores']['papers']['item_count']}")
        _ui(f"  workspace: {result['stores']['workspace']['item_count']}")
        _ui(f"  planned_legacy_moves: {len(result.get('planned_cleanup_candidates', []))}")
        if result["blockers"]:
            _ui(f"  blocker_codes: {', '.join(blocker['code'] for blocker in result['blockers'])}")
        return

    if action == "status":
        meta = ensure_instance_metadata(cfg)
        lock_status = describe_migration_lock(cfg)
        journal_dirs = list_migration_journals(cfg)
        _ui("Migration control status")
        _ui(f"  instance.json: {cfg.instance_meta_path}")
        _ui(f"  layout_state: {meta.get('layout_state')}")
        _ui(f"  layout_version: {meta.get('layout_version')}")
        _ui(f"  instance_id: {meta.get('instance_id')}")
        _ui(f"  journal_root: {cfg.migration_journals_root}")
        _ui(f"  journal_count: {len(journal_dirs)}")
        if journal_dirs:
            _ui(f"  latest_journal: {journal_dirs[-1].name}")
            latest_verify = read_migration_verify(cfg, journal_dirs[-1].name)
            if latest_verify is not None:
                _ui(f"  latest_verify_status: {latest_verify.get('status')}")
            latest_cleanup = read_latest_cleanup_step(cfg, journal_dirs[-1].name)
            if latest_cleanup is not None:
                details = latest_cleanup.get("details") or {}
                cleanup_status = details.get("cleanup_status") or latest_cleanup.get("status")
                _ui(f"  latest_cleanup_status: {cleanup_status}")
        _ui(f"Migration lock status: {lock_status['status']}")
        if lock_status["lock"]:
            lock = lock_status["lock"]
            _ui(f"  migration_id: {lock.get('migration_id')}")
            _ui(f"  pid: {lock.get('pid')}")
            _ui(f"  hostname: {lock.get('hostname')}")
            _ui(f"  started_at: {lock.get('started_at')}")
        else:
            _ui(f"  lock_path: {cfg.migration_lock_path} (absent)")
        return

    if action == "recover":
        if not getattr(args, "clear_lock", False):
            _ui("Pass --clear-lock explicitly before clearing migration.lock.")
            raise SystemExit(2)

        cleared = clear_migration_lock(cfg)
        if not cleared:
            _ui(f"No migration.lock found: {cfg.migration_lock_path}")
            return

        _ui(f"Cleared migration.lock: {cfg.migration_lock_path}")
        meta = read_instance_metadata(cfg) or ensure_instance_metadata(cfg)
        if meta.get("layout_state") == "migrating":
            updated = mark_instance_layout_state(cfg, "needs_recovery")
            _ui(f"Marked instance layout_state as {updated['layout_state']}")
        return

    if action == "verify":
        requested_id = getattr(args, "migration_id", None)
        journal_dir = resolve_migration_journal(cfg, requested_id)
        if journal_dir is None:
            if requested_id:
                _ui(f"Migration journal not found: {requested_id}")
            else:
                _ui("No migration journal found; create a journal scaffold first.")
            raise SystemExit(2)

        result = run_migration_verification(cfg, journal_dir.name)
        _ui(f"Verification completed: {journal_dir.name}")
        _ui(f"  verify_json: {journal_dir / 'verify.json'}")
        _ui(f"  status: {result['status']}")
        _ui(f"  checks: {result['summary']['passed']}/{result['summary']['total']} passed")
        if result["summary"]["failed"]:
            failed_checks = [check["name"] for check in result["checks"] if check["status"] != "passed"]
            _ui(f"  failed_checks: {', '.join(failed_checks)}")
        return

    if action == "cleanup":
        requested_id = getattr(args, "migration_id", None)
        journal_dir = resolve_migration_journal(cfg, requested_id)
        if journal_dir is None:
            if requested_id:
                _ui(f"Migration journal not found: {requested_id}")
            else:
                _ui("No migration journal found; create a journal scaffold first.")
            raise SystemExit(2)

        try:
            result = run_migration_cleanup(cfg, journal_dir.name, confirm=getattr(args, "confirm", False))
        except RuntimeError as exc:
            _ui(str(exc))
            raise SystemExit(2) from exc

        _ui(f"Cleanup evaluation completed: {journal_dir.name}")
        _ui(f"  status: {result['status']}")
        _ui(f"  candidate_count: {result['candidate_count']}")
        if "archived_count" in result:
            _ui(f"  archived_count: {result['archived_count']}")
        _ui(f"  removed_count: {result['removed_count']}")
        if result.get("blocked_reason"):
            _ui(f"  blocked_reason: {result['blocked_reason']}")
        elif result.get("confirm_required"):
            _ui("  confirm_required: true")
        return

    if action == "finalize":
        try:
            result = run_migration_finalize(
                cfg,
                migration_id=getattr(args, "migration_id", None),
                confirm=getattr(args, "confirm", False),
            )
        except RuntimeError as exc:
            _ui(str(exc))
            raise SystemExit(2) from exc

        _ui(f"Finalize completed: {result['migration_id']}")
        _ui(f"  status: {result['status']}")
        _ui(f"  workspace_status: {result['workspace_migration']['status']}")
        _ui(f"  workspace_output_status: {result['workspace_output_migration']['status']}")
        _ui(f"  workspace_output_conflict_count: {result['workspace_output_migration'].get('conflict_count', 0)}")
        _ui(f"  cleanup_status: {result['cleanup']['status']}")
        _ui(f"  cleanup_candidate_count: {result['cleanup']['candidate_count']}")
        _ui(f"  verify_before_cleanup: {result['verify_before_cleanup']['status']}")
        _ui(f"  verify_after_cleanup: {result['verify_after_cleanup']['status']}")
        return

    if action == "upgrade":
        try:
            result = run_migration_upgrade(
                cfg,
                migration_id=getattr(args, "migration_id", None),
                confirm=getattr(args, "confirm", False),
            )
        except RuntimeError as exc:
            _ui(str(exc))
            raise SystemExit(2) from exc

        _ui(f"Upgrade completed: {result['migration_id']}")
        _ui(f"  status: {result['status']}")
        _ui(f"  source_layout_version: {result.get('source_layout_version')}")
        _ui(f"  target_layout_version: {result.get('target_layout_version')}")
        _ui(f"  store_run_count: {len(result['store_runs'])}")
        if result["store_runs"]:
            _ui(f"  stores: {', '.join(item['store'] for item in result['store_runs'])}")
        _ui(f"  finalize_status: {result['finalize']['status']}")
        _ui(f"  cleanup_status: {result['finalize']['cleanup']['status']}")
        _ui(f"  verify_after_cleanup: {result['finalize']['verify_after_cleanup']['status']}")
        return

    if action == "run":
        try:
            result = run_migration_store(
                cfg,
                store=getattr(args, "store", ""),
                migration_id=getattr(args, "migration_id", None),
                confirm=getattr(args, "confirm", False),
            )
        except RuntimeError as exc:
            _ui(str(exc))
            raise SystemExit(2) from exc

        _ui(f"Migration run completed: {result['migration_id']}")
        _ui(f"  store: {result['store']}")
        _ui(f"  status: {result['status']}")
        _ui(f"  copied_count: {result['copied_count']}")
        _ui(f"  skipped_count: {result['skipped_count']}")
        _ui(f"  cleanup_candidate_count: {result['cleanup_candidate_count']}")
        _ui(f"  verify_status: {result['verify_status']}")
        return

    _log_error("Unknown migrate subcommand: %s", action)
    sys.exit(1)
