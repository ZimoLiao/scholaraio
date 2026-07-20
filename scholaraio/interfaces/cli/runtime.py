"""CLI runtime entrypoint."""

from __future__ import annotations

import sys

from scholaraio.core.log import ui as _default_ui


def _ensure_utf8_stdout() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows cp1252 consoles.

    The logging StreamHandler writes to sys.stdout using its current encoding.
    On Western-European Windows the default is cp1252, which cannot encode CJK
    characters or many Unicode symbols used in setup check output.  Calling
    reconfigure() here — before the root logger is created — makes every
    subsequent handler.emit() safe for the full Unicode range.

    reconfigure() is available on Python 3.7+ TextIOWrapper objects (the
    normal sys.stdout/stderr).  We guard with hasattr so the call is a no-op
    on streams that don't support it (e.g. redirected pipes with a custom
    wrapper).
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _ui(message: str = "") -> None:
    try:
        from scholaraio.interfaces.cli import compat as cli_mod
    except ImportError:
        _default_ui(message)
        return
    cli_mod.ui(message)


def main() -> None:
    _ensure_utf8_stdout()

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
