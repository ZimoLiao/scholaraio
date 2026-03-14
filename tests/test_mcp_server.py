"""Contract tests for the build_topics MCP tool.

Verifies: the nr_topics parameter mapping from integer sentinel values
(0 → "auto", -1 → None, positive → unchanged) to the values forwarded to
topics.build_topics.  The BERTopic model itself is not exercised here.

Does NOT test: BERTopic internals, model persistence, or MCP transport.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal MCP stub so mcp_server can be imported without the `mcp` package.
# The @mcp.tool() decorator must be a pass-through so the original functions
# are preserved as callables.
# ---------------------------------------------------------------------------


class _FakeFastMCP:
    """Lightweight stand-in for mcp.server.fastmcp.FastMCP."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def tool(self, *args: object, **kwargs: object):
        """Return an identity decorator so decorated functions remain callable."""

        def decorator(fn):
            return fn

        return decorator


def _install_mcp_stub() -> None:
    """Insert minimal `mcp.*` stubs into sys.modules if not already present."""
    if "mcp.server.fastmcp" in sys.modules:
        return
    mcp_mod = ModuleType("mcp")
    server_mod = ModuleType("mcp.server")
    fastmcp_mod = ModuleType("mcp.server.fastmcp")
    fastmcp_mod.FastMCP = _FakeFastMCP  # type: ignore[attr-defined]
    sys.modules.setdefault("mcp", mcp_mod)
    sys.modules.setdefault("mcp.server", server_mod)
    sys.modules.setdefault("mcp.server.fastmcp", fastmcp_mod)


def _fake_cfg(tmp_path: Path) -> MagicMock:
    """Minimal config object with the paths used by build_topics."""
    cfg = MagicMock()
    cfg.topics_model_dir = tmp_path / "topic_model"
    cfg.index_db = tmp_path / "index.db"
    cfg.papers_dir = tmp_path / "papers"
    return cfg


class TestBuildTopicsNrTopicsMapping:
    """Contract: nr_topics sentinel values map correctly to build_topics kwargs."""

    @pytest.fixture(autouse=True)
    def _stub_mcp_and_reload(self) -> None:
        # Ensure the mcp stub is in place before mcp_server is imported.
        _install_mcp_stub()
        # Drop any cached import so our stubs take effect cleanly.
        sys.modules.pop("scholaraio.mcp_server", None)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _run(
        self,
        nr_topics: int,
        tmp_path: Path,
    ) -> tuple[str, MagicMock]:
        """Call mcp_server.build_topics with mocked internals.

        Returns (json_result_string, mock_build_topics_call).
        """
        import scholaraio.mcp_server as srv

        fake_model = MagicMock()
        fake_model._topics = []
        mock_bt = MagicMock(return_value=fake_model)

        with (
            patch.object(srv, "_get_cfg", return_value=_fake_cfg(tmp_path)),
            patch("scholaraio.topics.build_topics", mock_bt),
            patch("scholaraio.topics.get_topic_overview", return_value=[]),
        ):
            result = srv.build_topics(rebuild=True, nr_topics=nr_topics)

        return result, mock_bt

    # ------------------------------------------------------------------
    # Mapping tests
    # ------------------------------------------------------------------

    def test_nr_topics_zero_maps_to_auto(self, tmp_path: Path) -> None:
        """nr_topics=0 (the default) must forward nr_topics='auto'."""
        _, mock_bt = self._run(0, tmp_path)
        assert mock_bt.call_args.kwargs["nr_topics"] == "auto"

    def test_nr_topics_minus_one_maps_to_none(self, tmp_path: Path) -> None:
        """nr_topics=-1 must forward nr_topics=None (no reduction)."""
        _, mock_bt = self._run(-1, tmp_path)
        assert mock_bt.call_args.kwargs["nr_topics"] is None

    def test_nr_topics_positive_passed_through(self, tmp_path: Path) -> None:
        """A positive nr_topics value is forwarded to build_topics unchanged."""
        _, mock_bt = self._run(10, tmp_path)
        assert mock_bt.call_args.kwargs["nr_topics"] == 10

    # ------------------------------------------------------------------
    # Response structure
    # ------------------------------------------------------------------

    def test_result_is_valid_json_with_required_fields(self, tmp_path: Path) -> None:
        """build_topics returns JSON containing topics, outliers, total_papers."""
        result, _ = self._run(0, tmp_path)
        data = json.loads(result)
        for key in ("topics", "outliers", "total_papers"):
            assert key in data, f"Missing key: {key}"
