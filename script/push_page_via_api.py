#!/usr/bin/env python3
"""Push local wiki page text to MediaWiki via action=edit."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import requests

from console_ui import Spinner, _header, _info, _step_done

REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = "RUNI_Wiki push_page_via_api/1.0"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _parse_env_line(line: str, line_no: int) -> Optional[Tuple[str, str]]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    if stripped.startswith("export "):
        stripped = stripped[len("export "):].strip()

    if "=" not in stripped:
        raise RuntimeError(f"Некорректная строка в .env (line {line_no})")

    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        raise RuntimeError(f"Пустой ключ в .env (line {line_no})")

    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]

    return key, value


def autoload_dotenv() -> Tuple[bool, int]:
    """Load .env from project root into process env without overriding existing vars.

    Returns (dotenv_found, vars_loaded_count).
    """
    env_path = _project_root() / ".env"
    if not env_path.exists():
        return False, 0
    if not env_path.is_file():
        raise RuntimeError(f"Ожидался файл .env, но найден другой тип: {env_path}")

    content = env_path.read_text(encoding="utf-8-sig")
    loaded = 0
    for idx, line in enumerate(content.splitlines(), start=1):
        parsed = _parse_env_line(line, idx)
        if not parsed:
            continue
        key, value = parsed
        if key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return True, loaded


def load_page_text(path: str) -> str:
    file_path = Path(path)
    if not file_path.exists():
        raise RuntimeError(f"Файл не найден: {file_path}")
    if not file_path.is_file():
        raise RuntimeError(f"Ожидался файл, но получен путь: {file_path}")
    return file_path.read_text(encoding="utf-8")


def infer_title(path: str, explicit_title: Optional[str] = None) -> str:
    if explicit_title and explicit_title.strip():
        return explicit_title.strip()
    stem = Path(path).stem.strip()
    if not stem:
        raise RuntimeError("Не удалось определить title из имени файла")
    return stem


def read_env_config() -> Dict[str, str]:
    api_url = os.getenv("MW_API_URL", "").strip()
    username = os.getenv("MW_USERNAME", "").strip()
    bot_password = os.getenv("MW_BOT_PASSWORD", "")
    user_password = os.getenv("MW_PASSWORD", "")
    user_agent = os.getenv("MW_USER_AGENT", "").strip() or DEFAULT_USER_AGENT

    missing = []
    if not api_url:
        missing.append("MW_API_URL")
    if not username:
        missing.append("MW_USERNAME")
    if not bot_password and not user_password:
        missing.append("MW_BOT_PASSWORD|MW_PASSWORD")
    if missing:
        raise RuntimeError(f"Отсутствуют обязательные env: {', '.join(missing)}")

    password = bot_password if bot_password else user_password
    auth_mode = "bot_password" if bot_password else "password"

    return {
        "api_url": api_url,
        "username": username,
        "password": password,
        "auth_mode": auth_mode,
        "user_agent": user_agent,
    }


def _extract_api_error(payload: Dict) -> str:
    error = payload.get("error")
    if not isinstance(error, dict):
        return "Неизвестная ошибка API"
    code = str(error.get("code", "unknown"))
    info = str(error.get("info", "no info"))
    return f"{code}: {info}"


def _mw_get(session: requests.Session, api_url: str, params: Dict[str, str]) -> Dict:
    query = dict(params)
    query["format"] = "json"
    response = session.get(api_url, params=query, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(_extract_api_error(payload))
    return payload


def _mw_post(session: requests.Session, api_url: str, data: Dict[str, str]) -> Dict:
    body = dict(data)
    body["format"] = "json"
    response = session.post(api_url, data=body, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(_extract_api_error(payload))
    return payload


def _mw_get_login_token(session: requests.Session, api_url: str) -> str:
    payload = _mw_get(
        session,
        api_url,
        {
            "action": "query",
            "meta": "tokens",
            "type": "login",
        },
    )
    token = payload.get("query", {}).get("tokens", {}).get("logintoken", "")
    if not token:
        raise RuntimeError("Не удалось получить login token")
    return token


def _mw_login_action(
    session: requests.Session, api_url: str, username: str, password: str, token: str
) -> None:
    payload = _mw_post(
        session,
        api_url,
        {
            "action": "login",
            "lgname": username,
            "lgpassword": password,
            "lgtoken": token,
        },
    )
    login = payload.get("login", {})
    result = str(login.get("result", ""))
    if result == "Success":
        return
    reason = str(login.get("reason", "")).strip()
    raise RuntimeError(f"login failed: {result}{f' ({reason})' if reason else ''}")


def _mw_clientlogin_action(
    session: requests.Session, api_url: str, username: str, password: str, token: str
) -> None:
    payload = _mw_post(
        session,
        api_url,
        {
            "action": "clientlogin",
            "username": username,
            "password": password,
            "logintoken": token,
            "loginreturnurl": "https://localhost/",
        },
    )
    result = payload.get("clientlogin", {})
    status = str(result.get("status", ""))
    if status == "PASS":
        return
    message = str(result.get("message", "")).strip()
    message_code = str(result.get("messagecode", "")).strip()
    details = message or message_code or "unknown"
    raise RuntimeError(f"clientlogin failed: {status} ({details})")


def mw_login(session: requests.Session, api_url: str, username: str, password: str) -> None:
    token = _mw_get_login_token(session, api_url)
    try:
        _mw_login_action(session, api_url, username, password, token)
        return
    except RuntimeError as login_error:
        login_error_text = str(login_error)

    token = _mw_get_login_token(session, api_url)
    try:
        _mw_clientlogin_action(session, api_url, username, password, token)
        return
    except RuntimeError as clientlogin_error:
        raise RuntimeError(
            "Не удалось авторизоваться. "
            f"login: {login_error_text}; clientlogin: {clientlogin_error}"
        ) from clientlogin_error


def mw_get_csrf_token(session: requests.Session, api_url: str) -> str:
    payload = _mw_get(
        session,
        api_url,
        {
            "action": "query",
            "meta": "tokens",
            "type": "csrf",
        },
    )
    token = payload.get("query", {}).get("tokens", {}).get("csrftoken", "")
    if not token:
        raise RuntimeError("Не удалось получить CSRF token")
    return token


def _extract_revision_text(page: Dict) -> str:
    revisions = page.get("revisions", [])
    if not revisions:
        return ""
    rev = revisions[0]
    slots = rev.get("slots", {})
    main_slot = slots.get("main", {})
    content = main_slot.get("content")
    if content is not None:
        return str(content)
    if "*" in main_slot:
        return str(main_slot.get("*"))
    if "*" in rev:
        return str(rev.get("*"))
    return ""


def _mw_get_page_state(
    session: requests.Session,
    api_url: str,
    title: str,
) -> Tuple[str, Optional[str], Optional[str]]:
    payload = _mw_get(
        session,
        api_url,
        {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content|timestamp",
            "rvslots": "main",
            "titles": title,
            "formatversion": "2",
            "curtimestamp": "1",
        },
    )
    page_list = payload.get("query", {}).get("pages", [])
    if not page_list:
        return "", None, payload.get("curtimestamp")
    page = page_list[0]
    if page.get("missing"):
        return "", None, payload.get("curtimestamp")

    text = _extract_revision_text(page)
    revisions = page.get("revisions", [])
    basetimestamp = None
    if revisions:
        basetimestamp = revisions[0].get("timestamp")
    starttimestamp = payload.get("curtimestamp")
    return text, basetimestamp, starttimestamp


def mw_get_current_text(session: requests.Session, api_url: str, title: str) -> str:
    text, _basetimestamp, _starttimestamp = _mw_get_page_state(session, api_url, title)
    return text


def mw_edit(
    session: requests.Session,
    api_url: str,
    title: str,
    text: str,
    summary: str,
    csrf_token: str,
    minor: bool = False,
    bot: bool = False,
    basetimestamp: Optional[str] = None,
    starttimestamp: Optional[str] = None,
) -> Dict:
    data: Dict[str, str] = {
        "action": "edit",
        "title": title,
        "text": text,
        "token": csrf_token,
        "summary": summary,
    }
    if minor:
        data["minor"] = "1"
    if bot:
        data["bot"] = "1"
    if basetimestamp:
        data["basetimestamp"] = basetimestamp
    if starttimestamp:
        data["starttimestamp"] = starttimestamp

    payload = _mw_post(session, api_url, data)
    edit = payload.get("edit")
    if not isinstance(edit, dict):
        raise RuntimeError("Неожиданный ответ API: отсутствует блок edit")
    result = str(edit.get("result", ""))
    if result != "Success":
        raise RuntimeError(f"Редактирование не выполнено: {result}")
    return edit


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Загружает/обновляет страницу на MediaWiki по локальному .wiki файлу."
    )
    parser.add_argument(
        "--api-url",
        help="URL api.php (если не указан, берётся из MW_API_URL)",
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Путь к локальному файлу статьи (UTF-8)",
    )
    parser.add_argument(
        "--title",
        help="Явный title страницы (по умолчанию — имя файла без расширения)",
    )
    parser.add_argument(
        "--summary",
        default="Sync from local",
        help='Комментарий правки (по умолчанию: "Sync from local")',
    )
    parser.add_argument(
        "--minor",
        action="store_true",
        help="Пометить правку как minor",
    )
    parser.add_argument(
        "--bot",
        action="store_true",
        help="Пометить правку как bot",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать параметры отправки, без сетевых запросов",
    )
    parser.add_argument(
        "--skip-if-same",
        action="store_true",
        help="Сравнить с текущим текстом страницы и пропустить edit, если изменений нет",
    )
    return parser.parse_args(argv)


def run_push(args: argparse.Namespace) -> int:
    _header("Push страницы")

    with Spinner("Загрузка конфигурации окружения"):
        dotenv_found, dotenv_loaded = autoload_dotenv()
        config = read_env_config()
    env_detail = ".env не найден"
    if dotenv_found:
        env_detail = f".env загружен, vars: {dotenv_loaded}"
    _step_done("Конфигурация", env_detail)

    api_url = (args.api_url or config["api_url"]).strip()
    if not api_url:
        raise RuntimeError("Не задан API URL (параметр --api-url или env MW_API_URL)")
    _step_done("API endpoint", api_url)

    with Spinner("Чтение локального файла"):
        text = load_page_text(args.file)
        title = infer_title(args.file, args.title)

    _step_done("Страница", title)
    _step_done("Файл", args.file)
    _info(f"Размер текста: {len(text.encode('utf-8'))} bytes")
    summary = args.summary
    _info(f"Summary: {summary}")

    if args.dry_run:
        _step_done("Dry-run", "сетевые запросы не выполнялись")
        _info(f"title: {title}")
        _info(f"bytes: {len(text.encode('utf-8'))}")
        _info(f"summary: {summary}")
        return 0

    session = requests.Session()
    session.headers.update({"User-Agent": config["user_agent"]})

    try:
        with Spinner("Авторизация в MediaWiki"):
            mw_login(session, api_url, config["username"], config["password"])
        _step_done("Авторизация", "успешно")

        with Spinner("Получение CSRF token"):
            csrf_token = mw_get_csrf_token(session, api_url)
        _step_done("CSRF token", "получен")

        with Spinner("Получение состояния страницы"):
            current_text, basetimestamp, starttimestamp = _mw_get_page_state(
                session, api_url, title
            )
        _step_done("Состояние страницы", "получено")

        if args.skip_if_same and current_text == text:
            _step_done("Сравнение", "без изменений")
            _info("No changes, skipped")
            return 0
        if args.skip_if_same:
            _step_done("Сравнение", "изменения обнаружены")

        with Spinner("Публикация правки"):
            edit_result = mw_edit(
                session=session,
                api_url=api_url,
                title=title,
                text=text,
                summary=summary,
                csrf_token=csrf_token,
                minor=args.minor,
                bot=args.bot,
                basetimestamp=basetimestamp,
                starttimestamp=starttimestamp,
            )
        new_revid = edit_result.get("newrevid")
        _step_done("Публикация", "успешно")
        if new_revid is not None:
            _info(f"Success: newrevid={new_revid}")
        else:
            _info("Success")
        return 0
    finally:
        session.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        return run_push(args)
    except requests.exceptions.RequestException as exc:
        print(f"Ошибка сети: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Непредвиденная ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
