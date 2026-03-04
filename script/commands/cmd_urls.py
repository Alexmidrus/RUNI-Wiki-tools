"""Import URLs Command."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple

import yaml

from core.api_client import MediaWikiClient
from core.config import AppConfig
from core.storage import DataStorage
from core.ui import ConsoleUI
from .base import BaseCommand
from .cmd_template import SERVICE_SUBPAGE_SUFFIXES


NAMESPACE_MODES = {
    "templates": {"namespace": 10, "label": "Шаблоны", "filename": "templates_urls.yml"},
    "categories": {"namespace": 14, "label": "Категории", "filename": "categories_urls.yml"},
    "articles": {"namespace": 0, "label": "Статьи", "filename": "articles_urls.yml"},
}


class ImportUrlsCommand(BaseCommand):
    """Fetch all page URLs from wiki and save to YAML."""

    def __init__(self) -> None:
        self.name = "urls"
        self.help = "Получает список всех URL (шаблоны, категории или статьи) и сохраняет в data"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "mode",
            choices=list(NAMESPACE_MODES.keys()),
            help="Режим получения URL: templates, categories, articles",
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
            help="Папка вывода внутри data/ (по умолчанию: source_url)",
        )
        parser.add_argument(
            "--insecure",
            action="store_true",
            help="Отключить проверку SSL-сертификата (если у вики проблемы с TLS)",
        )

    def _get_siteinfo(self, client: MediaWikiClient, namespace_id: int) -> Tuple[str, List[str]]:
        general, query = client.get_siteinfo()
        namespaces = query.get("namespaces", {})
        ns_key = str(namespace_id)
        if ns_key not in namespaces:
            raise RuntimeError(f"На вики не найден namespace {namespace_id}")

        ns_data = namespaces[ns_key]
        namespace_aliases = query.get("namespacealiases", [])

        primary_prefix = ns_data.get("*") or ns_data.get("name") or str(ns_data.get("id"))
        
        prefixes: Set[str] = set()
        for key in ("*", "canonical", "name"):
            val = ns_data.get(key)
            if isinstance(val, str) and val.strip():
                prefixes.add(val.strip().lower())
        for alias in namespace_aliases:
            if str(alias.get("id")) == ns_key:
                alias_name = alias.get("*")
                if isinstance(alias_name, str) and alias_name.strip():
                    prefixes.add(alias_name.strip().lower())
        
        if namespace_id == 10:
            prefixes.add("template")
        elif namespace_id == 14:
            prefixes.add("category")

        return str(primary_prefix), sorted(prefixes)

    def _split_namespace_title(self, title: str) -> Tuple[str, str]:
        prefix, sep, rest = title.partition(":")
        if not sep:
            return "", title
        return prefix.strip().lower(), rest.strip()

    def _is_service_subpage(self, title: str, namespace_id: int, prefixes: Set[str]) -> bool:
        if namespace_id != 10:
            return False
            
        prefix, short_name = self._split_namespace_title(title)
        if not short_name or prefix not in prefixes:
            return False

        lower = short_name.lower()
        if "/" not in short_name:
            return False

        if any(lower.endswith(suffix) for suffix in SERVICE_SUBPAGE_SUFFIXES):
            return True
        if "/doc/" in lower or "/documentation/" in lower:
            return True

        return False

    def build_page_url(self, client: MediaWikiClient, title: str) -> str:
        general, _ = client.get_siteinfo()
        server = general.get("server", client.normalize_base_url(client.get_api_endpoint().replace("/api.php", "")))
        articlepath = general.get("articlepath", "/wiki/$1")
        if not articlepath:
            articlepath = "/wiki/$1"
        try:
            from urllib.parse import quote
            encoded_title = quote(title.replace(" ", "_"), safe="/:")
            path = articlepath.replace("$1", encoded_title)
            return f"{server}{path}"
        except Exception:
            return f"{server}/wiki/{title.replace(' ', '_')}"

    def execute(
        self,
        args: argparse.Namespace,
        ui: ConsoleUI,
        storage: DataStorage,
        config: AppConfig,
    ) -> int:
        output_root = storage.resolve_path(args.output_root, "source_url")
        base_url = MediaWikiClient.normalize_base_url(args.wiki_base_url)
        mode_conf = NAMESPACE_MODES[args.mode]
        mode_label = mode_conf["label"]
        namespace_id = mode_conf["namespace"]
        filename = mode_conf["filename"]

        ui.header(f"Получение URL: {mode_label}")
        client = MediaWikiClient(ui, insecure=args.insecure)
        
        try:
            # 1. API endpoint
            if args.api_endpoint:
                api_endpoint = args.api_endpoint.rstrip("/")
                client._api_endpoint = api_endpoint
                ui.step_done("API endpoint", api_endpoint)
            else:
                with ui.spinner("Поиск API endpoint..."):
                    api_endpoint = client.detect_api_endpoint(base_url)
                ui.step_done("API endpoint", api_endpoint)

            # 2. Siteinfo and prefixes
            with ui.spinner("Синхронизация siteinfo..."):
                primary_prefix, prefixes_list = self._get_siteinfo(client, namespace_id)
            prefixes = set(prefixes_list)
            
            # 3. Collect titles
            titles: List[str] = []
            filtered_out = 0
            with ui.spinner("Сбор заголовков страниц...") as sp:
                for title in client.iter_allpages(namespace_id):
                    if self._is_service_subpage(title, namespace_id, prefixes):
                        filtered_out += 1
                        continue
                    titles.append(title)
                    if len(titles) % 100 == 0:
                        sp.update(f"проверено {len(titles) + filtered_out}")
                sp.update(f"проверено {len(titles) + filtered_out}")

            ui.step_done(f"Заголовки {mode_label}", f"{len(titles)} найдено")
            if filtered_out > 0:
                ui.step_done("Отфильтровано (doc/css и т.п.)", str(filtered_out))

            # 4. Generate YAML payload
            now = datetime.now(timezone.utc)
            yaml_data: Dict[str, object] = {
                "metadata": {
                    "source": client.normalize_base_url(client.get_api_endpoint().replace("/api.php", "")),
                    "mode": args.mode,
                    "namespace_id": namespace_id,
                    "total": len(titles),
                    "generated_at": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
                },
                "items": []
            }

            ui.info("Генерация URL адресов...")
            items = []
            for title in titles:
                items.append({
                    "title": title,
                    "url": self.build_page_url(client, title),
                })
            yaml_data["items"] = items

            # 5. Save YAML
            output_root.mkdir(parents=True, exist_ok=True)
            output_file = output_root / filename
            
            data_str = yaml.dump(
                yaml_data, 
                allow_unicode=True, 
                sort_keys=False, 
                default_flow_style=False,
            )
            data_bytes = data_str.encode("utf-8")
            storage.write_binary(output_file, data_bytes)

            ui.step_done("Сохранено", output_file.name)
            ui.info(f"Папка: {output_root}")
            ui.print_stdout(f"\nГотово: найдено {len(titles)} {mode_label.lower()}")
            ui.print_stdout(f"Файл: {output_file}")
            return 0
        finally:
            client.close()
