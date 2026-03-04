"""Application entrypoint encapsulating CLI routing and dependency injection."""

from __future__ import annotations

import argparse
import sys
from typing import Dict

from core.config import AppConfig
from core.storage import DataStorage
from core.ui import ConsoleUI

from commands.base import BaseCommand
from commands.cmd_article import ImportArticleCommand
from commands.cmd_category import ImportCategoryCommand
from commands.cmd_template import ImportTemplateCommand
from commands.cmd_urls import ImportUrlsCommand
from commands.cmd_push import PushPageCommand
from commands.cmd_push_templates import PushTemplatesCommand


class CLIApplication:
    """Main CLI Application manager routing commands to their handlers."""

    def __init__(self) -> None:
        self.ui = ConsoleUI()
        self.storage = DataStorage()
        self.config = AppConfig()

        # Instantiate commands
        self.commands: Dict[str, BaseCommand] = {}
        self._register_command(ImportArticleCommand())
        self._register_command(ImportCategoryCommand())
        self._register_command(ImportTemplateCommand())
        self._register_command(ImportUrlsCommand())
        self._register_command(PushPageCommand())
        self._register_command(PushTemplatesCommand())

    def _register_command(self, cmd: BaseCommand) -> None:
        self.commands[cmd.name] = cmd

    def run(self, args: list[str] | None = None) -> int:
        """Main execution method. Returns exit code."""
        parser = argparse.ArgumentParser(
            description="CLI инструменты для управления контентом RUNI Wiki (ООП версия)",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        
        subparsers = parser.add_subparsers(
            dest="command",
            required=True,
            title="Доступные команды",
        )

        # Setup all registered commands
        for cmd_name, cmd_obj in self.commands.items():
            subparser = subparsers.add_parser(
                cmd_obj.name,
                help=cmd_obj.help,
                description=cmd_obj.help,
            )
            cmd_obj.configure_parser(subparser)

        parsed_args = parser.parse_args(args)

        command_obj = self.commands.get(parsed_args.command)
        if not command_obj:
            self.ui.error(f"Неизвестная команда: {parsed_args.command}")
            return 1

        try:
            return command_obj.execute(parsed_args, self.ui, self.storage, self.config)
        except RuntimeError as exc:
            self.ui.error(str(exc))
            return 1
        except KeyboardInterrupt:
            self.ui.error("Операция прервана пользователем (Ctrl+C).")
            return 130
        except Exception as exc:
            self.ui.error(f"Непредвиденная системная ошибка: {exc}")
            import traceback
            traceback.print_exc()
            return 1

