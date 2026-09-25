"""Prepare/check an isolated library for a real WSL/Windows PDF annotation test.

This script never launches a viewer. Use the printed command when ready to
interact with the Windows desktop, then run check after saving annotations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scholaraio.core.config import _build_config
from scholaraio.stores.papers import write_meta
from scholaraio.stores.pdf_edit_mirror import PdfEditMirrorStore


def pdf_bytes(label: str, megabytes: int) -> bytes:
    stream = f"BT /F1 16 Tf 72 720 Td ({label}: add a visible annotation and save.) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    # Legal comments before the xref make a large, valid one-page fixture.
    data.extend((b"%" + b" " * 1022 + b"\n") * (megabytes * 1024))
    xref = len(data)
    data.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def prepare(root: Path, large_mib: int) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "config.yaml").write_text("{}\n", encoding="utf-8")
    cfg = _build_config({}, root)
    cfg.ensure_dirs()
    fixtures = []
    for label, size in [("small", 1), ("large", large_mib)]:
        paper = cfg.papers_dir / label
        paper.mkdir()
        paper_id = str(uuid.uuid4())
        write_meta(
            paper,
            {"id": paper_id, "title": f"Desktop acceptance {label}", "year": 2026, "authors": ["Synthetic fixture"]},
        )
        pdf = paper / "paper.pdf"
        pdf.write_bytes(pdf_bytes(label, size))
        fixtures.append({"id": paper_id, "label": label, "pdf": str(pdf), "baseline": digest(pdf)})
    (root / "acceptance.json").write_text(json.dumps(fixtures, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "config": str(root / "config.yaml"),
                "fixtures": fixtures,
                "next": "Set SCHOLARAIO_CONFIG to this config, then run python -m scholaraio.cli gui. "
                "Open each PDF with the default viewer, annotate, save and close it. "
                "After synchronization, run this script with check.",
            },
            indent=2,
        )
    )


def check(root: Path) -> bool:
    cfg = _build_config({}, root)
    db = cfg.pdf_edit_mirror_state_dir / "sync.db"
    if not db.is_file():
        raise ValueError("No mirror session exists yet. Open the fixtures in the WebUI first.")
    store = PdfEditMirrorStore(db)
    results = []
    for item in json.loads((root / "acceptance.json").read_text(encoding="utf-8")):
        record = store.get_by_paper("main", item["id"])
        canonical = digest(Path(item["pdf"]))
        mirror = digest(record.mirror_path) if record and record.mirror_path.is_file() else ""
        results.append(
            {
                "label": item["label"],
                "annotation_saved": canonical != item["baseline"],
                "copies_equal": canonical == mirror,
                "state": record.state if record else "not_opened",
                "passed": bool(
                    record and record.state == "in_sync" and canonical == mirror and canonical != item["baseline"]
                ),
            }
        )
    (root / "acceptance-result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return all(item["passed"] for item in results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "check"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--large-mib", type=int, default=128)
    args = parser.parse_args()
    if not 1 <= args.large_mib <= 1024:
        parser.error("--large-mib must be between 1 and 1024")
    root = args.root.resolve()
    if args.action == "prepare":
        prepare(root, args.large_mib)
    else:
        raise SystemExit(0 if check(root) else 1)
