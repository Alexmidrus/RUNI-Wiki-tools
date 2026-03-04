"""Import Category Command."""

from __future__ import annotations

import argparse
from typing import Set

from core.api_client import MediaWikiClient
from core.config import AppConfig
from core.storage import DataStorage
from core.ui import ConsoleUI
from .base import BaseCommand


class ImportCategoryCommand(BaseCommand):
    """Import a category page markup from wiki into data/category."""

    def __init__(self) -> None:
        self.name = "category"
        self.help = "Импортирует разметку страницы категории с вики"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "category_name",
            help="Название категории (например: Фрегаты или Категория:Фрегаты)",
        )
        parser.add_argument(
            "--wiki-base-url",
            default="https://solarmeta.evecraft.ru",
            help="Базовый URL вики (по умолчанию: https://solarmeta.evecraft.ru)",
        )
        parser.add_argument(
            "--api-endpoint",
            help="Явный URL API, например https://example.org/w/api.php",
        )
        parser.add_argument(
            "--output-root",
            help="Папка вывода внутри data/ или абсолютный путь внутри data/ (по умолчанию: category)",
        )
        parser.add_argument(
            "--insecure",
            action="store_true",
            help="Отключить проверку SSL-сертификата (если у вики проблемы с TLS)",
        )

    def _get_category_siteinfo(self, client: MediaWikiClient) -> tuple[str, Set[str]]:
        general, query = client.get_siteinfo()
        namespaces = query.get("namespaces", {})
        if "14" not in namespaces:
            raise RuntimeError("На вики не найден namespace 14 (Category)")

        ns14 = namespaces["14"]
        namespace_aliases = query.get("namespacealiases", [])

        # Determine primary prefix
        primary_prefix = ""
        ns14_local = ns14.get("*")
        if isinstance(ns14_local, str) and ns14_local.strip():
            primary_prefix = ns14_local.strip()
        elif isinstance(ns14.get("canonical"), str) and ns14.get("canonical", "").strip():
            primary_prefix = ns14["canonical"].strip()
        else:
            primary_prefix = "Category"

        # Collect all lowercase prefixes
        prefixes: Set[str] = set()
        for key in ("*", "canonical", "name"):
            value = ns14.get(key)
            if isinstance(value, str) and value.strip():
                prefixes.add(value.strip().lower())
        for alias in namespace_aliases:
            if str(alias.get("id")) == "14":
                alias_name = alias.get("*")
                if isinstance(alias_name, str) and alias_name.strip():
                    prefixes.add(alias_name.strip().lower())
        prefixes.add("category")

        return primary_prefix, prefixes

    def _normalize_category_name(self, input_name: str, category_prefixes: Set[str]) -> str:
        value = input_name.strip().lstrip(":")
        prefix, sep, rest = value.partition(":")
        if sep and prefix.strip().lower() in category_prefixes:
            value = rest.strip()
        if not value:
            raise RuntimeError("Пустое имя категории после нормализации")
        return value

    def execute(
        self,
        args: argparse.Namespace,
        ui: ConsoleUI,
        storage: DataStorage,
        config: AppConfig,
    ) -> int:
        output_root = storage.resolve_path(args.output_root, "category")
        base_url = MediaWikiClient.normalize_base_url(args.wiki_base_url)

        ui.header(f"Импорт категории: {args.category_name}")
        client = MediaWikiClient(ui, insecure=args.insecure)
        try:
            # 1. API endpoint
            if args.api_endpoint:
                api_endpoint = args.api_endpoint.rstrip("/")
                client._api_endpoint = api_endpoint
                ui.step_done("API endpoint", api_endpoint)
            else:
                with ui.spinner("Поиск API endpoint"):
                    api_endpoint = client.detect_api_endpoint(base_url)
                ui.step_done("API endpoint", api_endpoint)

            # 2. Siteinfo — get category prefixes
            with ui.spinner("Загрузка siteinfo"):
                primary_prefix, prefixes = self._get_category_siteinfo(client)
            ui.step_done("Siteinfo", f"префикс: {primary_prefix}")

            # 3. Normalize name — strip prefix if given
            category_name = self._normalize_category_name(args.category_name, prefixes)
            full_title = f"{primary_prefix}:{category_name}"

            # 4. Fetch category markup
            with ui.spinner(f"Загрузка разметки {ui.dim}{full_title}{ui.reset}"):
                content_map = client.fetch_titles_content([full_title])
            category_content = content_map.get(full_title)
            if not category_content:
                ui.error(f"Категория не найдена или пуста: {full_title}")
                return 1
            ui.step_done("Разметка загружена")

            # 5. Prepare output directory
            safe_name = storage.sanitize_filename(category_name)
            target_dir = output_root / safe_name
            target_dir.mkdir(parents=True, exist_ok=True)

            # 6. Save category markup
            category_file = target_dir / f"{safe_name}_category"
            storage.write_text(category_file, category_content)
            ui.step_done("Сохранена разметка", category_file.name)

            # 7. If name has unsafe chars — write real_name file
            if storage.has_unsafe_chars(category_name):
                real_name_file = target_dir / "real_name"
                storage.write_text(real_name_file, category_name)
                ui.info(f"Создан real_name (оригинальное имя: {category_name})")

            ui.info(f"Папка: {target_dir}")
            ui.print_stdout(f"\nГотово: {full_title}")
            ui.print_stdout(f"Папка: {target_dir}")
            return 0
        finally:
            client.close()
