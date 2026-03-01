#!/usr/bin/env python3
"""Unified entrypoint for RUNI Wiki import tools."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, List, Sequence


def _load_commands() -> Dict[str, Callable[[Sequence[str] | None], int]]:
    script_dir = Path(__file__).resolve().parent / "script"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    import import_article_bundle
    import import_category_bundle
    import import_page_urls
    import import_template_bundle
    import push_page_via_api

    return {
        "template": import_template_bundle.main,
        "article": import_article_bundle.main,
        "category": import_category_bundle.main,
        "urls": import_page_urls.main,
        "push": push_page_via_api.main,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Единая точка входа RUNI Wiki. "
            "Все создаваемые файлы сохраняются внутри папки data/."
        )
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["template", "article", "category", "urls", "push"],
        help="Команда: template | article | category | urls | push",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Аргументы команды (используйте '<command> --help' для справки)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(argv)
    if not ns.command:
        parser.print_help()
        return 1

    commands = _load_commands()
    handler = commands[ns.command]
    forwarded: List[str] = list(ns.args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    return handler(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
