"""Static published-paper site CLI command handler."""

from __future__ import annotations

import argparse
from pathlib import Path


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def cmd_publish_site(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.publish_site import generate_site

    out_dir = _resolve_out_dir(getattr(args, "out_dir", None), cfg)
    if out_dir is None:
        _ui("Output directory is required. Pass --out-dir or set publish.site_output_dir in config.yaml.")
        raise SystemExit(1)

    copy_assets = not bool(getattr(args, "symlink", False))
    result = generate_site(published_dir=cfg.published_dir, out_dir=out_dir, copy_assets=copy_assets)
    _ui(f"Generated site for {result.paper_count} published papers: {out_dir}")


def _resolve_out_dir(out_dir_arg: str | None, cfg) -> Path | None:
    if out_dir_arg:
        return Path(out_dir_arg).expanduser().resolve()
    return getattr(cfg, "site_output_dir", None)
