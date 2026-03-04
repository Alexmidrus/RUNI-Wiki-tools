"""Import Template Command."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import List, Set, Tuple

from core.api_client import MediaWikiClient
from core.config import AppConfig
from core.storage import DataStorage
from core.ui import ConsoleUI
from .base import BaseCommand

SERVICE_SUBPAGE_SUFFIXES = (
    "/doc",
    "/documentation",
    "/styles.css",
    "/testcases",
    "/sandbox",
)

RETRYABLE_ERROR_SUBSTRINGS = (
    "unexpected_eof_while_reading",
    "eof occurred in violation of protocol",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection refused",
    "temporary failure",
    "temporarily unavailable",
    "remote end closed connection",
    "http error 429",
    "http error 502",
    "http error 503",
    "http error 504",
)

class ImportTemplateCommand(BaseCommand):
    """Import template pages from wiki into data/templates."""

    def __init__(self) -> None:
        self.name = "template"
        self.help = "Импортирует код шаблона, шаблона/doc и шаблона/styles.css с вики"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "template_name",
            nargs="?",
            help="Имя шаблона (например: ShipArticle)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Импортировать все шаблоны из namespace 10",
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
            help="Папка вывода внутри data/ или абсолютный путь внутри data/ (по умолчанию: templates)",
        )
        parser.add_argument(
            "--insecure",
            action="store_true",
            help="Отключить проверку SSL-сертификата (если у вики проблемы с TLS)",
        )

    def _get_template_siteinfo(self, client: MediaWikiClient) -> Tuple[str, List[str]]:
        general, query = client.get_siteinfo()
        namespaces = query.get("namespaces", {})
        if "10" not in namespaces:
            raise RuntimeError("На вики не найден namespace 10 (Template)")

        ns10 = namespaces.get("10", {})
        namespace_aliases = query.get("namespacealiases", [])

        primary_prefix = ""
        ns10_local = ns10.get("*")
        if isinstance(ns10_local, str) and ns10_local.strip():
            primary_prefix = ns10_local.strip()
        elif isinstance(ns10.get("canonical"), str) and ns10.get("canonical", "").strip():
            primary_prefix = ns10["canonical"].strip()
        elif isinstance(ns10.get("name"), str) and ns10.get("name", "").strip():
            primary_prefix = ns10["name"].strip()
        else:
            primary_prefix = "Template"

        prefixes: Set[str] = set()
        for key in ("*", "canonical", "name"):
            value = ns10.get(key)
            if isinstance(value, str) and value.strip():
                prefixes.add(value.strip().lower())
        for alias in namespace_aliases:
            if str(alias.get("id")) == "10":
                alias_name = alias.get("*")
                if isinstance(alias_name, str) and alias_name.strip():
                    prefixes.add(alias_name.strip().lower())
        prefixes.add("template")
        return primary_prefix, sorted(prefixes)

    def _normalize_template_name(self, input_name: str, template_prefixes: Set[str]) -> str:
        value = input_name.strip().lstrip(":")
        prefix, sep, rest = value.partition(":")
        if sep and prefix.strip().lower() in template_prefixes:
            value = rest.strip()

        if "/" in value:
            value = value.split("/", 1)[0].strip()
        if not value:
            raise RuntimeError("Пустое имя шаблона после нормализации")
        return value

    def _split_namespace_title(self, title: str) -> Tuple[str, str]:
        prefix, sep, rest = title.partition(":")
        if not sep:
            return "", ""
        return prefix.strip().lower(), rest

    def _is_importable_template_title(self, title: str, template_prefixes: Set[str]) -> bool:
        prefix, short_name = self._split_namespace_title(title)
        if not short_name or prefix not in template_prefixes:
            return False

        lower = short_name.lower()
        if "/" in short_name:
            return False
        if any(lower.endswith(suffix) for suffix in SERVICE_SUBPAGE_SUFFIXES):
            return False
        if "/doc/" in lower or "/documentation/" in lower:
            return False

        return True

    def _collect_template_names(self, client: MediaWikiClient, ui: ConsoleUI, prefixes: Set[str]) -> List[str]:
        names: Set[str] = set()
        scanned = 0
        with ui.spinner("Получение списка шаблонов") as sp:
            for title in client.iter_allpages(10):
                scanned += 1
                if scanned % 100 == 0:
                    sp.update(f"проверено {scanned}")
                if not self._is_importable_template_title(title, prefixes):
                    continue
                names.add(self._normalize_template_name(title, prefixes))
            sp.update(f"проверено {scanned}")
        return sorted(names)

    def _import_template(
        self,
        client: MediaWikiClient,
        storage: DataStorage,
        output_root: Path,
        primary_prefix: str,
        template_prefixes: Set[str],
        input_name: str,
    ) -> Tuple[str, Path, bool, bool]:
        template_name = self._normalize_template_name(input_name, template_prefixes)
        main_title = f"{primary_prefix}:{template_name}"
        doc_title = f"{primary_prefix}:{template_name}/doc"
        css_title = f"{primary_prefix}:{template_name}/styles.css"

        content_map = client.fetch_titles_content([main_title, doc_title, css_title])

        main_content = content_map.get(main_title)
        if not main_content:
            raise RuntimeError(f"Основной шаблон не найден или пуст: {main_title}")

        target_dir = output_root / template_name
        target_main = target_dir / template_name
        target_doc = target_dir / f"{template_name}_doc"
        target_css = target_dir / f"{template_name}_styles.css"

        storage.write_text(target_main, main_content)

        doc_content = content_map.get(doc_title)
        css_content = content_map.get(css_title)
        if doc_content is not None:
            storage.write_text(target_doc, doc_content)
        if css_content is not None:
            storage.write_text(target_css, css_content)

        return main_title, target_dir, (doc_content is not None), (css_content is not None)

    def _is_retryable_import_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return any(marker in text for marker in RETRYABLE_ERROR_SUBSTRINGS)

    def _import_template_with_retry(
        self,
        client: MediaWikiClient,
        storage: DataStorage,
        output_root: Path,
        primary_prefix: str,
        template_prefixes: Set[str],
        input_name: str,
        retries: int = 3,
        base_delay_seconds: float = 0.6,
    ) -> Tuple[str, Path, bool, bool]:
        for attempt in range(retries + 1):
            try:
                return self._import_template(
                    client, storage, output_root, primary_prefix, template_prefixes, input_name
                )
            except Exception as exc:
                if attempt >= retries or not self._is_retryable_import_error(exc):
                    raise
                time.sleep(base_delay_seconds * (2 ** attempt))

        raise RuntimeError("Непредвиденная ошибка повторных попыток импорта шаблона")

    def execute(
        self,
        args: argparse.Namespace,
        ui: ConsoleUI,
        storage: DataStorage,
        config: AppConfig,
    ) -> int:
        if args.all and args.template_name:
            ui.error("Используйте либо template_name, либо --all")
            return 1
        if not args.all and not args.template_name:
            ui.error("Укажите template_name или --all")
            return 1

        output_root = storage.resolve_path(args.output_root, "templates")
        base_url = MediaWikiClient.normalize_base_url(args.wiki_base_url)

        mode_title = "Импорт всех шаблонов" if args.all else f"Импорт шаблона: {args.template_name}"
        ui.header(mode_title)

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

            # 2. Siteinfo + namespace prefixes
            with ui.spinner("Загрузка siteinfo"):
                primary_prefix, prefixes_list = self._get_template_siteinfo(client)
            ui.step_done("Siteinfo", f"префикс: {primary_prefix}")
            prefixes = set(prefixes_list)

            if args.all:
                template_names = self._collect_template_names(client, ui, prefixes)
                total = len(template_names)
                ui.step_done("Список шаблонов", f"{total} шт.")
                if total == 0:
                    ui.info("Нечего импортировать: в namespace 10 не найдено шаблонов")
                    return 0

                imported = 0
                failed = 0
                missing_doc = 0
                missing_css = 0
                errors: List[str] = []

                with ui.spinner("Импорт шаблонов") as sp:
                    for index, template_name in enumerate(template_names, start=1):
                        sp.update(f"{index}/{total}  {template_name}")
                        try:
                            _main_title, _target_dir, has_doc, has_css = self._import_template_with_retry(
                                client, storage, output_root, primary_prefix, prefixes, template_name
                            )
                            imported += 1
                            if not has_doc: missing_doc += 1
                            if not has_css: missing_css += 1
                        except Exception as exc:
                            failed += 1
                            if len(errors) < 10:
                                errors.append(f"{template_name}: {exc}")

                detail = f"{imported}/{total}"
                if failed:
                    detail += f", ошибок: {failed}"
                ui.step_done("Шаблоны импортированы", detail)

                ui.info(f"Папка: {output_root}")
                ui.info(f"Без /doc: {missing_doc}")
                ui.info(f"Без /styles.css: {missing_css}")
                if errors:
                    ui.info("Ошибки (первые 10):")
                    for err in errors:
                        ui.info(f"- {err}")

                ui.print_stdout(f"\nГотово: импортировано шаблонов {imported} из {total}")
                ui.print_stdout(f"Папка: {output_root}")
                return 0

            template_name = args.template_name or ""

            with ui.spinner(f"Загрузка страниц {ui.dim}{template_name}{ui.reset}"):
                main_title, target_dir, has_doc, has_css = self._import_template_with_retry(
                    client, storage, output_root, primary_prefix, prefixes, template_name
                )

            ui.step_done("Страницы загружены")
            ui.step_done("Сохранена разметка", f"{target_dir.name}")
            if has_doc: ui.step_done("Сохранена документация")
            if has_css: ui.step_done("Сохранены стили")

            ui.info(f"Шаблон: {main_title}")
            ui.info(f"Папка: {target_dir}")
            if not has_doc or not has_css:
                ui.info("Внимание: страницы не найдены, файлы не создавались:")
                if not has_doc: ui.info(f"- {main_title}/doc")
                if not has_css: ui.info(f"- {main_title}/styles.css")

            ui.print_stdout(f"\nГотово: {main_title}")
            ui.print_stdout(f"Папка: {target_dir}")
            return 0
        finally:
            client.close()
