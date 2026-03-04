"""Push Single Page Command."""

from __future__ import annotations

import argparse
from pathlib import Path

from core.api_client import MediaWikiClient
from core.config import AppConfig
from core.storage import DataStorage
from core.ui import ConsoleUI
from .base import BaseCommand


class PushPageCommand(BaseCommand):
    """Push a local .wiki or .css file to MediaWiki."""

    def __init__(self) -> None:
        self.name = "push"
        self.help = "Загрузить (пуш) изменения из локального файла на вики (требует данные в .env)"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "file_path",
            help="Путь (можно относительный) до .wiki или .css файла (например: article/Ship_article)",
        )
        parser.add_argument(
            "--minor",
            action="store_true",
            help="Пометить правку как малую (minor)",
        )
        parser.add_argument(
            "--bot",
            action="store_true",
            help="Пометить правку как правку бота",
        )
        parser.add_argument(
            "--no-review",
            action="store_true",
            help="Не пытаться установить статус 'Проверено' (FlaggedRevisions) после загрузки",
        )
        parser.add_argument(
            "--summary",
            default="Изменение через CLI пуш",
            help="Комментарий (описание) к правке",
        )
        parser.add_argument(
            "--insecure",
            action="store_true",
            help="Отключить проверку SSL-сертификата",
        )

    def _determine_title_from_file(self, file_path: Path) -> str:
        marker_file = file_path.parent / "real_name"
        if marker_file.exists():
            return marker_file.read_text(encoding="utf-8").strip()

        name = file_path.name
        if name.endswith("_article"):
            title = name.replace("_article", "")
        elif name.endswith("_category"):
            title = f"Категория:{name.replace('_category', '')}"
        elif name.endswith("_doc"):
            title = f"Шаблон:{name.replace('_doc', '')}/doc"
        elif name.endswith("_styles.css"):
            title = f"Шаблон:{name.replace('_styles.css', '')}/styles.css"
        elif file_path.parent.name == "globals" and file_path.suffix in (".css", ".js"):
            title = f"MediaWiki:{name}"
        else:
            title = f"Шаблон:{name}"

        return title.replace("_", " ")

    def execute(
        self,
        args: argparse.Namespace,
        ui: ConsoleUI,
        storage: DataStorage,
        config: AppConfig,
    ) -> int:
        ui.header("Push на Википедию")
        
        # 1. Config loading validation
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

        # 2. File lookup and logic
        try:
            target_file = storage.resolve_path(args.file_path, "")
            if not target_file.exists() or not target_file.is_file():
                ui.error(f"Файл не найден: {target_file}")
                return 1
            local_content = storage.read_text(target_file)
        except Exception as e:
            ui.error(str(e))
            return 1

        title = self._determine_title_from_file(target_file)
        ui.info(f"Определен заголовок вики: {title}")

        client = MediaWikiClient(ui, config=api_config, insecure=args.insecure)
        try:
            with ui.spinner("Явная установка Endpoint из конфигурации"):
                client._api_endpoint = api_config.api_url

            # 3. Authentication
            with ui.spinner("Авторизация"):
                client.login()
            ui.step_done("Авторизация успешна", api_config.username)

            # 4. Check changes
            with ui.spinner("Сравнение с вики"):
                wiki_text, basetimestamp, starttimestamp = client.get_page_state(title)

            if wiki_text == local_content:
                ui.info("Локальный файл идентичен версии на вики. Изменения не требуются.")
                return 0

            ui.info("Найдены различия, загрузка новой ревизии...")

            # 5. Push
            with ui.spinner("Загрузка страницы"):
                csrf_token = client.get_csrf_token()
                result_edit = client.edit_page(
                    title,
                    local_content,
                    summary=args.summary,
                    csrf_token=csrf_token,
                    minor=args.minor,
                    bot=args.bot,
                    basetimestamp=basetimestamp,
                    starttimestamp=starttimestamp,
                )
            ui.step_done("Страница загружена", f"revid_new: {result_edit.get('newrevid')}")

            # 6. FlaggedRevisions (Review)
            if not args.no_review:
                new_revid = result_edit.get("newrevid")
                ui.info("Проверка прав и FlaggedRevisions...")
                rights = client.get_user_rights()
                can_review = "review" in rights

                if can_review:
                    status = client.get_flagged_status(title, new_revid)
                    if status == "pending":
                        with ui.spinner("Установка статуса 'Проверено'"):
                            client.try_review_revision(csrf_token, new_revid, "Авто-пуш скриптом")
                        ui.step_done("Статус 'Проверено' установлен", "FlaggedRevisions")
                    elif status == "stable":
                        ui.info("Страница уже имеет актуальный статус stable.")
                    else:
                        ui.info("FlaggedRevisions не настроен для данной страницы.")
                else:
                    ui.info("Нет прав 'review', автоматическое одобрение пропущено.")

            ui.print_stdout(f"\nГотово: изменения сохранены ({title})")
            return 0
            
        except RuntimeError as e:
            ui.error(str(e))
            return 1
        finally:
            client.close()
