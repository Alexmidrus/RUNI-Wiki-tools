"""Push Bulk Templates Command."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.api_client import MediaWikiClient
from core.config import AppConfig
from core.storage import DataStorage
from core.ui import ConsoleUI
from .base import BaseCommand


class PushTemplatesCommand(BaseCommand):
    """Bulk push templates and global files to MediaWiki."""

    def __init__(self) -> None:
        self.name = "push-templates"
        self.help = "Массово загрузить шаблоны и/или глобальные стили/скрипты на вики"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--templates-dir",
            help="Каталог внутри data/ откуда брать шаблоны (по умолчанию: templates)",
        )
        parser.add_argument(
            "--no-docs",
            action="store_true",
            help="Пропустить загрузку страниц документации шаблонов (/doc)",
        )
        parser.add_argument(
            "--no-styles",
            action="store_true",
            help="Пропустить загрузку стилей шаблонов (/styles.css)",
        )
        parser.add_argument(
            "--no-globals",
            action="store_true",
            help="Пропустить загрузку глобальных стилей/скриптов (из папки data/globals/)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=0.5,
            help="Задержка между загрузками в секундах (по умолчанию 0.5s)",
        )
        parser.add_argument(
            "--no-retry",
            action="store_true",
            help="Не пытаться повторить загрузку при ошибках редактирования",
        )
        parser.add_argument(
            "--start-after",
            help="Начать синхронизацию строго ПОСЛЕ указанного файла шаблона "
                 "(полезно для возобновления прерванной сессии)",
        )
        parser.add_argument(
            "--insecure",
            action="store_true",
            help="Отключить проверку SSL-сертификата (если у вики проблемы с TLS)",
        )

    def _map_template_path_to_title(self, path: Path) -> str:
        name = path.name
        if name.endswith("_doc"):
            return f"Шаблон:{name.replace('_doc', '')}/doc".replace("_", " ")
        if name.endswith("_styles.css"):
            return f"Шаблон:{name.replace('_styles.css', '')}/styles.css".replace("_", " ")
        if name == str(path.parent.name):
            return f"Шаблон:{name}".replace("_", " ")
        
        return f"Шаблон:{name}".replace("_", " ")

    def _map_global_file_to_title(self, path: Path) -> str:
        return f"MediaWiki:{path.name}".replace("_", " ")

    def _discover_items(
        self,
        storage: DataStorage,
        templates_dir: Path,
        args: argparse.Namespace
    ) -> List[Tuple[Path, str, str]]:
        items_to_push: List[Tuple[Path, str, str]] = []
        
        if templates_dir.exists() and templates_dir.is_dir():
            for child in sorted(templates_dir.iterdir()):
                if not child.is_dir():
                    continue
                for f in sorted(child.iterdir()):
                    if not f.is_file() or f.name == "real_name":
                        continue
                    if args.no_docs and f.name.endswith("_doc"):
                        continue
                    if args.no_styles and f.name.endswith("_styles.css"):
                        continue
                        
                    title = self._map_template_path_to_title(f)
                    items_to_push.append((f, title, "шаблон"))

        if not args.no_globals:
            globals_dir = storage.get_default_subdir("globals")
            if globals_dir.exists() and globals_dir.is_dir():
                for f in sorted(globals_dir.iterdir()):
                    if f.is_file() and f.suffix in (".css", ".js"):
                        title = self._map_global_file_to_title(f)
                        items_to_push.append((f, title, "глобальный"))

        return items_to_push

    def execute(
        self,
        args: argparse.Namespace,
        ui: ConsoleUI,
        storage: DataStorage,
        config: AppConfig,
    ) -> int:
        ui.header("Массовый Push Шаблонов и Глобальных файлов")
        
        config.autoload_dotenv()
        if not config.dotenv_found:
            ui.error("Не найден файл .env, загрузка переменных из окружения")
        else:
            ui.step_done("Env", f"загружено {config.dotenv_loaded_count} переменных")
            
        try:
            api_config = config.read_api_config()
        except RuntimeError as e:
            ui.error(str(e))
            return 1

        templates_dir = storage.resolve_path(args.templates_dir, "templates")

        ui.info("Сбор файлов...")
        items_to_push = self._discover_items(storage, templates_dir, args)

        if args.start_after:
            skip_count = 0
            for i, (f, title, category) in enumerate(items_to_push):
                skip_count += 1
                if f.name == args.start_after:
                    items_to_push = items_to_push[i + 1:]
                    ui.step_done("Start-after filter", f"Пропущено {skip_count} файлов. Осталось {len(items_to_push)}.")
                    break
            else:
                ui.error(f"Файл '{args.start_after}' не найден в очереди. Проверьте правильность написания.")
                return 1

        total = len(items_to_push)
        if total == 0:
            ui.info("Очередь выгрузки пуста. Измените фильтры или проверьте наличие файлов.")
            return 0
        ui.step_done("Очередь готова", f"{total} файлов для синхронизации")

        client = MediaWikiClient(ui, config=api_config, insecure=args.insecure)
        try:
            client._api_endpoint = api_config.api_url

            with ui.spinner("Авторизация"):
                client.login()
                csrf_token = client.get_csrf_token()
                rights = client.get_user_rights()
                can_review = "review" in rights
            ui.step_done("Авторизация успешна", f"rights: {len(rights)}; review: {can_review}")

            processed = 0
            uploaded = 0
            skipped = 0
            failed = 0
            
            error_log: List[str] = []

            for idx, (path, title, category) in enumerate(items_to_push, start=1):
                ui.info(f"[{idx}/{total}] {category}: {ui.bold}{title}{ui.reset}")
                content = storage.read_text(path)

                # Fetch remote state
                remote_text, basets, startts = client.get_page_state(title)

                if remote_text == content:
                    ui.info(f"  {ui.dim}Пропуск: локальная версия идентична вики{ui.reset}")
                    skipped += 1
                    continue

                for attempt in range(1 if args.no_retry else 3):
                    try:
                        result_edit = client.edit_page(
                            title,
                            content,
                            summary="[RUNI] Синхронизация шаблона",
                            csrf_token=csrf_token,
                            bot=True,
                            minor=True,
                            basetimestamp=basets,
                            starttimestamp=startts,
                        )
                        ui.info(f"  {ui.green}Загружено успешно{ui.reset} (revid: {result_edit.get('newrevid')})")
                        uploaded += 1

                        if can_review:
                            new_revid = result_edit.get("newrevid")
                            status = client.get_flagged_status(title, new_revid)
                            if status == "pending":
                                client.try_review_revision(csrf_token, new_revid, "Авто-пуш RUNI")
                                ui.info(f"  {ui.dim}Статус 'Проверено' установлен{ui.reset}")

                        if args.delay > 0 and idx < total:
                            time.sleep(args.delay)
                        break
                    except Exception as e:
                        if attempt < (0 if args.no_retry else 2):
                            ui.info(f"  {ui.dim}Ошибка редактирования ({e}), повтор через 2с...{ui.reset}")
                            time.sleep(2)
                            csrf_token = client.get_csrf_token() # Re-fetch token just in case
                        else:
                            ui.info(f"  {ui.yellow}Не удалось загрузить после {attempt + 1} попыток: {e}{ui.reset}")
                            error_log.append(f"{title}: {e}")
                            failed += 1

                processed += 1

            ui.header("Синхронизация завершена")
            ui.info(f"Всего файлов: {total}")
            ui.info(f"Загружено (изменено): {uploaded}")
            ui.info(f"Пропущено (совпадают): {skipped}")
            ui.info(f"Ошибок: {failed}")

            if error_log:
                ui.info("\nСводка ошибок:")
                for e in error_log:
                    ui.info(f" - {e}")
                return 1

            return 0
        finally:
            client.close()
