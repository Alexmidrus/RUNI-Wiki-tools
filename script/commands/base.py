"""Base Command Interface."""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod

from core.api_client import MediaWikiClient
from core.config import AppConfig
from core.storage import DataStorage
from core.ui import ConsoleUI


class BaseCommand(ABC):
    """Abstract base class for all CLI commands."""

    def __init__(self) -> None:
        self.name = ""
        self.help = ""

    @abstractmethod
    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add arguments to the command's parser."""
        pass

    @abstractmethod
    def execute(
        self,
        args: argparse.Namespace,
        ui: ConsoleUI,
        storage: DataStorage,
        config: AppConfig,
    ) -> int:
        """Execute the command. Needs to return an integer exit code (0 for success)."""
        pass
