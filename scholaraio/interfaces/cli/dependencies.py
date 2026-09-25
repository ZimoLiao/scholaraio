"""Shared CLI optional dependency diagnostics."""

from __future__ import annotations

import logging
import sys

_log = logging.getLogger(__name__)

_INSTALL_HINTS: dict[str, str] = {
    "sentence_transformers": "pip install scholaraio[embed]",
    "faiss": "pip install scholaraio[embed]",
    "numpy": "pip install scholaraio[embed]",
    "bertopic": "pip install scholaraio[topics]",
    "pandas": "pip install scholaraio[topics]",
    "endnote_utils": "pip install scholaraio[import]",
    "pyzotero": "pip install scholaraio[import]",
    "docx": "pip install scholaraio[office]",
    "pptx": "pip install scholaraio[office]",
    "openpyxl": "pip install scholaraio[office]",
    "markitdown": "pip install scholaraio[office]",
    "fitz": "pip install scholaraio[pdf]",
}


def _check_import_error(e: ImportError) -> None:
    """Log a user-friendly message for missing optional dependencies, then exit."""
    mod = getattr(e, "name", "") or ""
    # Match the top-level package name.
    top = mod.split(".")[0] if mod else ""
    hints = _INSTALL_HINTS
    logger = _log
    hint = hints.get(top, "")
    if hint:
        logger.error("Missing dependency: %s\n  Install: %s", mod, hint)
    else:
        logger.error("Missing dependency: %s\n  Please install the required Python packages", e)
    sys.exit(1)
