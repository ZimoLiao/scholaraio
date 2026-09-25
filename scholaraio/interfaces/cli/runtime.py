"""CLI runtime entrypoint."""

from __future__ import annotations

import os
import sys

_UNICODE_OUTPUT_PROBE = "中文✓→"


def _is_windows() -> bool:
    return os.name == "nt"


def _configure_windows_stdio() -> None:
    """Prevent Unicode output crashes on legacy Windows text streams.

    Modern Windows consoles already use UTF-8, while redirected streams and
    legacy console mode may use an ANSI code page. Preserve Python's selected
    encoding and relax only the error handler for streams that cannot encode
    ScholarAIO's localized output. An explicit ``PYTHONIOENCODING`` remains
    authoritative.
    """
    if not _is_windows() or "PYTHONIOENCODING" in os.environ:
        return

    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None)
        errors = getattr(stream, "errors", None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not isinstance(encoding, str) or not callable(reconfigure):
            continue
        if not isinstance(errors, str):
            errors = "strict"

        try:
            _UNICODE_OUTPUT_PROBE.encode(encoding, errors)
        except LookupError:
            continue
        except UnicodeEncodeError:
            try:
                reconfigure(errors="replace")
            except (OSError, TypeError, ValueError):
                continue


def _ui(message: str = "") -> None:
    from scholaraio.core import log

    log.ui(message)


def main() -> None:
    _configure_windows_stdio()

    from scholaraio.interfaces.cli import compat as cli_mod

    parser = cli_mod._build_parser()
    args = parser.parse_args()
    cfg = cli_mod.load_config()
    cfg.ensure_dirs()

    from scholaraio.core import log as _log
    from scholaraio.services import metrics as _metrics
    from scholaraio.services.ingest_metadata._models import configure_s2_session, configure_session
    from scholaraio.services.migration_control import (
        SUPPORTED_LAYOUT_VERSION,
        describe_migration_lock,
        ensure_instance_metadata,
        layout_version_is_supported,
    )

    meta = ensure_instance_metadata(cfg)
    session_id = _log.setup(cfg)
    if args.command == "migrate":
        args.func(args, cfg)
        return

    layout_version = meta.get("layout_version")
    if not layout_version_is_supported(layout_version):
        _ui(f"Detected a newer runtime layout: layout_version={layout_version}.")
        _ui(f"This program supports up to layout version {SUPPORTED_LAYOUT_VERSION}; please upgrade ScholarAIO first.")
        _ui("You can still run `scholaraio migrate status` to inspect the control-plane state.")
        raise SystemExit(2)

    lock_status = describe_migration_lock(cfg)
    if lock_status["status"] != "absent":
        _ui(f"Detected an active migration.lock: {cfg.migration_lock_path}")
        _ui("Only `scholaraio migrate status` or `scholaraio migrate recover --clear-lock` is allowed now.")
        raise SystemExit(2)

    is_setup_cmd = args.command == "setup"
    try:
        _metrics.init(cfg.metrics_db_path, session_id)
    except Exception as exc:
        if not is_setup_cmd:
            raise
        _ui(f"Warning: metrics initialization failed and was skipped; setup is unaffected: {exc}")
    configure_session(cfg.ingest.contact_email)
    configure_s2_session(cfg.resolved_s2_api_key())

    args.func(args, cfg)
