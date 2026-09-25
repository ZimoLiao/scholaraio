"""Setup CLI command handler."""

from __future__ import annotations

import argparse


def _ui(msg: str = "") -> None:
    from scholaraio.core import log

    log.ui(msg)


def cmd_setup(args: argparse.Namespace, cfg) -> None:
    from scholaraio.services.setup import format_check_results, run_check, run_wizard

    action = getattr(args, "setup_action", None)
    if action == "check":
        lang = getattr(args, "lang", "zh")
        results = run_check(cfg, lang)
        _ui(format_check_results(results))
    elif action == "agent":
        from pathlib import Path

        from scholaraio.services.agent_setup import (
            apply_agent_setup_plan,
            build_agent_setup_plan,
            format_agent_setup_plan,
        )

        lang = getattr(args, "lang", "en")
        plan = build_agent_setup_plan(
            cfg,
            agents=getattr(args, "agent", None),
            all_agents=bool(getattr(args, "setup_agent_all", False)),
            target_project=Path(args.target_project) if args.target_project else None,
            shell_path=Path(args.shell) if args.shell else None,
            include_shell=not bool(getattr(args, "no_shell", False)),
        )
        setup_agent_action = getattr(args, "setup_agent_action", None)
        if setup_agent_action == "check":
            _ui(format_agent_setup_plan(plan, lang=lang, mode="check"))
        elif getattr(args, "apply", False):
            applied = apply_agent_setup_plan(plan, force=bool(getattr(args, "force", False)))
            _ui(format_agent_setup_plan(applied, lang=lang, mode="apply"))
        else:
            _ui(format_agent_setup_plan(plan, lang=lang, mode="preview"))
    else:
        run_wizard(cfg)
