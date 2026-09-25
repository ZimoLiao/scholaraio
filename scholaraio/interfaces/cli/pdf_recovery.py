"""Inspectable PDF recovery for agents, using the same service as the WebUI."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from scholaraio.core.config import Config
from scholaraio.core.log import ui
from scholaraio.services.pdf_conflicts import inspect_conflict, resolve_conflict, version_path
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
        if args.action == "inspect":
            result = inspect_conflict(reconciler, record.sync_id)
        elif args.action == "export":
            source = version_path(reconciler, record.sync_id, args.version, args.token)
            # Never replace a user output file.
            with source.open("rb") as src, Path(args.output).open("xb") as dst:
                shutil.copyfileobj(src, dst)
            result = {"exported": str(args.output)}
        else:
            if not args.readers_closed:
                raise ValueError("Close PDF readers and pass --readers-closed before resolving")
            result = resolve_conflict(reconciler, record.sync_id, token=args.token, version=args.version)
        ui(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        ui(str(exc))
        raise SystemExit(1) from exc
