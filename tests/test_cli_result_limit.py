from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace

import pytest

import scholaraio.core.log as target_log
from scholaraio.interfaces.cli import compat as cli


class TestResultLimitCli:
    def test_search_help_promotes_limit_and_keeps_top_alias(self):
        parser = cli._build_parser()
        search_help = parser._subparsers._group_actions[0].choices["search"].format_help()

        assert "--limit" in search_help
        assert "--top" in search_help
        assert search_help.index("--limit") < search_help.index("--top")

    def test_search_parser_accepts_limit(self):
        parser = cli._build_parser()

        args = parser.parse_args(["search", "drag", "--limit", "7"])

        assert args.result_limit == 7

    def test_search_parser_accepts_top_alias(self):
        parser = cli._build_parser()

        args = parser.parse_args(["search", "drag", "--top", "7"])

        assert args.result_limit == 7

    def test_search_parser_rejects_conflicting_limit_and_top(self):
        parser = cli._build_parser()

        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["search", "drag", "--limit", "7", "--top", "3"])

        assert exc.value.code == 2

    def test_explore_fetch_limit_keeps_fetch_cap_semantics(self):
        parser = cli._build_parser()

        args = parser.parse_args(["explore", "fetch", "--name", "demo", "--limit", "50"])

        assert args.explore_action == "fetch"
        assert args.limit == 50
        assert not hasattr(args, "result_limit")


class TestResultLimitResolution:
    def test_resolve_result_limit_prefers_new_namespace_field(self):
        args = Namespace(result_limit=5, top=3)

        assert cli._resolve_result_limit(args, 10) == 5

    def test_resolve_result_limit_falls_back_to_legacy_top_field(self):
        args = Namespace(top=4)

        assert cli._resolve_result_limit(args, 10) == 4


class TestResultLimitCommands:
    def test_toolref_search_uses_limit_result_count(self, monkeypatch):
        seen: dict[str, object] = {}
        messages: list[str] = []

        monkeypatch.setattr(target_log, "ui", lambda msg="": messages.append(msg))
        monkeypatch.setattr(
            "scholaraio.stores.toolref.toolref_search",
            lambda tool, query, **kwargs: seen.update({"tool": tool, "query": query, **kwargs}) or [],
        )

        args = Namespace(
            toolref_action="search",
            tool="qe",
            query=["ecutwfc"],
            result_limit=9,
            top=None,
            program=None,
            section=None,
        )

        cli.cmd_toolref(args, SimpleNamespace())

        assert seen["top_k"] == 9
