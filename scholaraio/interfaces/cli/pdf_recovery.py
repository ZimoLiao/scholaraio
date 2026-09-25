"""Inspectable PDF recovery for agents, using the same service as the WebUI."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from scholaraio.core.config import Config
from scholaraio.core.log import ui
from scholaraio.services.pdf_conflicts import export_version, inspect_conflict, resolve_conflict
from scholaraio.services.pdf_edit_mirror import PdfEditMirrorPaths, PdfEditMirrorReconciler
from scholaraio.stores.pdf_edit_mirror import PdfEditMirrorStore


def cmd_pdf_recovery(args: argparse.Namespace, cfg: Config) -> None:
    try:
        store = PdfEditMirrorStore(cfg.pdf_edit_mirror_state_dir / "sync.db")
        record = store.get_by_paper(args.source, args.paper_id)
        if record is None:
            raise ValueError("No editable mirror exists for this paper")
        reconciler = PdfEditMirrorReconciler(
            store=store,
            paths=PdfEditMirrorPaths(
                mirror_root=record.mirror_path.parents[2], state_root=cfg.pdf_edit_mirror_state_dir
            ),
        )
        from scholaraio.services.library_view import resolve_pdf_edit_mirror_target

        def resolver(current):
            return resolve_pdf_edit_mirror_target(cfg, current.library_kind, current.paper_id, record=current)

        if args.action == "inspect":
            result = inspect_conflict(reconciler, record.sync_id, resolver=resolver)
        elif args.action == "export":
            # Never replace a user output file.
            with (
                export_version(reconciler, record.sync_id, args.version, args.token, resolver=resolver) as source,
                source.open("rb") as src,
                Path(args.output).open("xb") as dst,
            ):
                shutil.copyfileobj(src, dst)
            result = {"exported": str(args.output)}
        else:
            if not args.readers_closed:
                raise ValueError("Close PDF readers and pass --readers-closed before resolving")
            result = resolve_conflict(
                reconciler, record.sync_id, token=args.token, version=args.version, resolver=resolver
            )
        ui(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        ui(str(exc))
        raise SystemExit(1) from exc
