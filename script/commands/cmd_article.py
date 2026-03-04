"""Import Article Command."""

from __future__ import annotations

import argparse

from core.api_client import MediaWikiClient
from core.config import AppConfig
from core.storage import DataStorage
from core.ui import ConsoleUI
from .base import BaseCommand


class ImportArticleCommand(BaseCommand):
    """Import an article page (and optionally its images) from wiki into data/article."""

    def __init__(self) -> None:
        self.name = "article"
        self.help = "Импортирует разметку статьи (и, опционально, изображения) с вики"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("article_name", help="Название статьи (например: Imperial Navy Slicer)")
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
            help="Папка вывода внутри data/ или абсолютный путь внутри data/ (по умолчанию: article)",
        )
        parser.add_argument(
            "--include-images",
            action="store_true",
            help="Скачать изображения, используемые в статье",
        )
        parser.add_argument(
            "--insecure",
            action="store_true",
            help="Отключить проверку SSL-сертификата (если у вики проблемы с TLS)",
        )

    def execute(
        self,
        args: argparse.Namespace,
        ui: ConsoleUI,
        storage: DataStorage,
        config: AppConfig,
    ) -> int:
        output_root = storage.resolve_path(args.output_root, "article")
        base_url = MediaWikiClient.normalize_base_url(args.wiki_base_url)
        article_name = args.article_name.strip()

        ui.header(f"Импорт статьи: {article_name}")

        client = MediaWikiClient(ui, insecure=args.insecure)
        try:
            # 1. API endpoint
            if args.api_endpoint:
                api_endpoint = args.api_endpoint.rstrip("/")
                client._api_endpoint = api_endpoint  # Hack to set it manually for the client
                ui.step_done("API endpoint", api_endpoint)
            else:
                with ui.spinner("Поиск API endpoint"):
                    api_endpoint = client.detect_api_endpoint(base_url)
                ui.step_done("API endpoint", api_endpoint)

            # 2. Fetch article markup
            with ui.spinner(f"Загрузка разметки {ui.dim}{article_name}{ui.reset}"):
                content_map = client.fetch_titles_content([article_name])
            
            article_content = content_map.get(article_name)
            if not article_content:
                ui.error(f"Статья не найдена или пуста: {article_name}")
                return 1
            ui.step_done("Разметка загружена")

            # 3. Prepare output directory
            safe_name = storage.sanitize_filename(article_name)
            target_dir = output_root / safe_name
            target_dir.mkdir(parents=True, exist_ok=True)

            # 4. Save article markup
            article_file = target_dir / f"{safe_name}_article"
            storage.write_text(article_file, article_content)
            ui.step_done("Сохранена разметка", article_file.name)

            # 5. If name has unsafe chars — write real_name file
            if storage.has_unsafe_chars(article_name):
                real_name_file = target_dir / "real_name"
                storage.write_text(real_name_file, article_name)
                ui.info(f"Создан real_name (оригинальное имя: {article_name})")

            # 6. Download images (only with --include-images)
            if args.include_images:
                with ui.spinner("Получение списка изображений"):
                    image_titles = client.fetch_page_images(article_name)
                ui.step_done("Изображения", f"{len(image_titles)} найдено")

                image_urls = {}
                if image_titles:
                    with ui.spinner("Получение URL изображений"):
                        image_urls = client.fetch_image_urls(image_titles)

                downloaded = 0
                failed = 0
                if image_urls:
                    with ui.spinner("Скачивание изображений") as sp:
                        for file_title, url in image_urls.items():
                            filename = file_title.split(":", 1)[-1] if ":" in file_title else file_title
                            safe_img = storage.sanitize_filename(filename)
                            sp.update(f"{downloaded + 1}/{len(image_urls)}  {safe_img}")
                            try:
                                data = client.fetch_binary(url)
                                storage.write_binary(target_dir / safe_img, data)
                                downloaded += 1
                            except Exception as exc:
                                failed += 1
                                ui.info(f"Не удалось скачать {filename}: {exc}")
                    detail = f"{downloaded} скачано"
                    if failed:
                        detail += f", {failed} ошибок"
                    ui.step_done("Изображения", detail)

            ui.info(f"Папка: {target_dir}")
            ui.print_stdout(f"\nГотово: {article_name}")
            ui.print_stdout(f"Папка: {target_dir}")
            return 0
        finally:
            client.close()
