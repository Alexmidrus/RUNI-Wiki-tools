#!/usr/bin/env python3
"""Push local template files (and optional global CSS/JS) to MediaWiki."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import requests

from console_ui import Spinner, _header, _info, _step_done
from project_paths import resolve_path_in_data
from push_page_via_api import (
    _mw_get,
    _mw_post,
    autoload_dotenv,
    mw_edit,
    mw_get_csrf_token,
    mw_login,
    read_env_config,
)

DEFAULT_SUMMARY = "Sync templates from local"
DEFAULT_USER_AGENT = "RUNI_Wiki push_templates_to_wiki/1.0"


@dataclass(frozen=True)
class PushItem:
    file_path: Path
    rel_path: str
    page_title: str
    group: str


def _parse_int(value: object) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_slashes(path: str) -> str:
    return path.replace("\\", "/")


def _collect_manifest_map(manifest_path: Optional[Path]) -> Dict[str, str]:
    if manifest_path is None or not manifest_path.exists():
        return {}
    if not manifest_path.is_file():
        raise RuntimeError(f"Ожидался файл manifest: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Manifest должен быть JSON-объектом: {manifest_path}")
    result: Dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        norm_key = _normalize_slashes(key).strip("/")
        norm_val = value.strip()
        if not norm_key or not norm_val:
            continue
        result[norm_key] = norm_val
    return result


def _map_template_path_to_title(rel_path: str) -> Optional[str]:
    parts = _normalize_slashes(rel_path).split("/")
    if len(parts) != 2:
        return None
    folder, filename = parts
    if not folder or not filename:
        return None
    if filename == folder:
        return f"Template:{folder}"
    if filename == f"{folder}_doc":
        return f"Template:{folder}/doc"
    if filename == f"{folder}_styles.css":
        return f"Template:{folder}/styles.css"
    return None


def _map_global_file_to_title(filename: str) -> Optional[str]:
    value = filename.strip()
    if not value:
        return None
    if value.startswith("MediaWiki:"):
        return value
    if value.startswith("MediaWiki_"):
        return f"MediaWiki:{value[len('MediaWiki_'):]}"
    if value.startswith("MediaWiki "):
        return f"MediaWiki:{value[len('MediaWiki '):]}"
    simple = {"Common.css", "Common.js", "Vector.css", "Vector.js"}
    if value in simple:
        return f"MediaWiki:{value}"
    return None


def _iter_template_files(root: Path) -> List[Tuple[Path, str]]:
    items: List[Tuple[Path, str]] = []
    for path in sorted(root.rglob("*"), key=lambda p: str(p).casefold()):
        if not path.is_file():
            continue
        rel = _normalize_slashes(str(path.relative_to(root)))
        items.append((path, rel))
    return items


def _iter_global_files(root: Path) -> List[Tuple[Path, str]]:
    items: List[Tuple[Path, str]] = []
    for path in sorted(root.glob("*"), key=lambda p: str(p).casefold()):
        if not path.is_file():
            continue
        items.append((path, path.name))
    return items


def _matches_only(
    item: PushItem, pattern: Optional[str], compiled_regex: Optional[re.Pattern[str]] = None
) -> bool:
    if not pattern:
        return True
    target_path = item.rel_path
    target_title = item.page_title
    if pattern.startswith("re:"):
        regex = compiled_regex or re.compile(pattern[3:], re.IGNORECASE)
        return bool(regex.search(target_path) or regex.search(target_title))
    mask = pattern.lower()
    return fnmatch.fnmatch(target_path.lower(), mask) or fnmatch.fnmatch(
        target_title.lower(), mask
    )


def _discover_items(
    templates_root: Path,
    include_global: bool,
    global_root: Path,
    manifest_map: Dict[str, str],
) -> Tuple[List[PushItem], List[str]]:
    items: List[PushItem] = []
    skipped: List[str] = []

    for path, rel in _iter_template_files(templates_root):
        mapped = manifest_map.get(rel)
        if not mapped:
            mapped = _map_template_path_to_title(rel)
        if not mapped:
            skipped.append(f"templates/{rel}: unsupported file name format")
            continue
        items.append(PushItem(path, f"templates/{rel}", mapped, "template"))

    if include_global:
        for path, rel in _iter_global_files(global_root):
            mapped = _map_global_file_to_title(rel)
            if not mapped:
                skipped.append(f"global/{rel}: unsupported global file name")
                continue
            items.append(PushItem(path, f"global/{rel}", mapped, "global"))

    items.sort(key=lambda x: x.rel_path.casefold())
    return items, skipped


def _is_access_error(error_text: str) -> bool:
    low = error_text.lower()
    markers = (
        "protectedpage",
        "permissiondenied",
        "readapidenied",
        "badaccess",
        "cantcreate",
    )
    return any(token in low for token in markers)


def _is_edit_conflict(error_text: str) -> bool:
    return "editconflict" in error_text.lower()


def _get_page_state(
    session: requests.Session, api_url: str, title: str
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
    revisions = page.get("revisions", [])
    text = ""
    basetimestamp = None
    if revisions:
        rev = revisions[0]
        basetimestamp = rev.get("timestamp")
        slots = rev.get("slots", {})
        main_slot = slots.get("main", {})
        if isinstance(main_slot, dict) and "content" in main_slot:
            text = str(main_slot.get("content") or "")
        elif isinstance(main_slot, dict) and "*" in main_slot:
            text = str(main_slot.get("*") or "")
        elif "*" in rev:
            text = str(rev.get("*") or "")
    return text, basetimestamp, payload.get("curtimestamp")


def _get_user_rights(session: requests.Session, api_url: str) -> Set[str]:
    payload = _mw_get(
        session,
        api_url,
        {
            "action": "query",
            "meta": "userinfo",
            "uiprop": "rights",
        },
    )
    rights = payload.get("query", {}).get("userinfo", {}).get("rights", [])
    if not isinstance(rights, list):
        return set()
    return {str(item).strip() for item in rights if str(item).strip()}


def _get_flagged_status(
    session: requests.Session, api_url: str, title: str, new_revid: Optional[int]
) -> str:
    payload = _mw_get(
        session,
        api_url,
        {
            "action": "query",
            "prop": "flagged",
            "titles": title,
            "formatversion": "2",
        },
    )
    pages = payload.get("query", {}).get("pages", [])
    if not pages:
        return "unknown"
    flagged = pages[0].get("flagged")
    if not isinstance(flagged, dict):
        return "unknown"
    stable_revid = _parse_int(flagged.get("stable_revid"))
    pending_since = str(flagged.get("pending_since") or "").strip()
    if pending_since:
        return "pending"
    if stable_revid is not None and new_revid is not None:
        return "stable" if stable_revid == new_revid else "pending"
    return "unknown"


def _try_review_revision(
    session: requests.Session,
    api_url: str,
    csrf_token: str,
    revid: int,
    comment: str,
) -> None:
    _mw_post(
        session,
        api_url,
        {
            "action": "review",
            "revid": str(revid),
            "token": csrf_token,
            "comment": comment,
        },
    )


def _make_report_row(
    *,
    file_path: Path,
    page_title: str,
    edit_result: str,
    new_revision_id: Optional[int],
    flaggedrevs_status: str,
    error_message: str = "",
) -> Dict[str, object]:
    return {
        "file_path": str(file_path),
        "page_title": page_title,
        "edit_result": edit_result,
        "new_revision_id": new_revision_id,
        "flaggedrevs_status": flaggedrevs_status,
        "error_message": error_message,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Выгружает шаблоны из data/templates и (опционально) global CSS/JS "
            "в целевую MediaWiki через API."
        )
    )
    parser.add_argument(
        "--api-url",
        help="URL api.php (если не указан, берется из MW_API_URL или MEDIAWIKI_API_URL)",
    )
    parser.add_argument(
        "--templates-root",
        help="Путь внутри data/ к папке шаблонов (по умолчанию: templates)",
    )
    parser.add_argument(
        "--include-global",
        action="store_true",
        help="Также обработать файлы из data/global",
    )
    parser.add_argument(
        "--global-root",
        help="Путь внутри data/ к папке global (по умолчанию: global)",
    )
    parser.add_argument(
        "--manifest",
        help=(
            "JSON-карта relative_path -> page_title для неоднозначных случаев "
            "(путь внутри data/ или абсолютный путь внутри data/)"
        ),
    )
    parser.add_argument(
        "--only",
        help=(
            "Фильтр. По умолчанию glob-маска (например '*_styles.css'). "
            "Для regex используйте префикс 're:' (например re:^templates/.+_doc$)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Ограничить количество обрабатываемых файлов",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Обработать список в обратном порядке",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать сопоставление file -> page_title без API-запросов",
    )
    parser.add_argument(
        "--summary",
        default=DEFAULT_SUMMARY,
        help=f"Комментарий правки (по умолчанию: {DEFAULT_SUMMARY!r})",
    )
    parser.add_argument("--minor", action="store_true", help="Отметить правку как minor")
    parser.add_argument("--bot", action="store_true", help="Отметить правку как bot")
    parser.add_argument(
        "--editconflict-retries",
        type=int,
        default=1,
        help="Количество повторов при editconflict (по умолчанию: 1)",
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Не пытаться выполнять action=review (FlaggedRevs)",
    )
    parser.add_argument(
        "--report-dir",
        help="Папка для JSON-отчета внутри data/ (по умолчанию: exports)",
    )
    ns = parser.parse_args(argv)
    if ns.limit is not None and ns.limit <= 0:
        parser.error("--limit должен быть > 0")
    if ns.editconflict_retries < 0:
        parser.error("--editconflict-retries должен быть >= 0")
    return ns


def _resolve_input_paths(args: argparse.Namespace) -> Tuple[Path, Path, Optional[Path], Path]:
    templates_root = resolve_path_in_data(args.templates_root, "templates")
    global_root = resolve_path_in_data(args.global_root, "global")
    report_dir = resolve_path_in_data(args.report_dir, "exports")
    manifest_path: Optional[Path] = None
    if args.manifest:
        manifest_path = resolve_path_in_data(args.manifest, "")
    return templates_root, global_root, manifest_path, report_dir


def run_push(args: argparse.Namespace) -> int:
    _header("Push templates")

    with Spinner("Загрузка .env"):
        dotenv_found, dotenv_loaded = autoload_dotenv()
    env_detail = ".env не найден"
    if dotenv_found:
        env_detail = f".env загружен, vars: {dotenv_loaded}"
    _step_done("Конфигурация", env_detail)

    config: Dict[str, str] = {}
    api_url = ""
    if not args.dry_run:
        with Spinner("Чтение переменных окружения для API"):
            config = read_env_config()
        api_url = (args.api_url or config["api_url"]).strip()
        if not api_url:
            raise RuntimeError(
                "Не задан API URL (--api-url или env MW_API_URL/MEDIAWIKI_API_URL)"
            )
        _step_done("API endpoint", api_url)

    with Spinner("Проверка путей и manifest"):
        templates_root, global_root, manifest_path, report_dir = _resolve_input_paths(args)
        manifest_map = _collect_manifest_map(manifest_path)
        if not templates_root.exists() or not templates_root.is_dir():
            raise RuntimeError(f"Папка templates не найдена: {templates_root}")
        if args.include_global and (not global_root.exists() or not global_root.is_dir()):
            raise RuntimeError(f"Папка global не найдена: {global_root}")
    _step_done("Templates root", str(templates_root))
    if args.include_global:
        _step_done("Global root", str(global_root))
    if manifest_map:
        _step_done("Manifest", f"{len(manifest_map)} entries")

    with Spinner("Поиск файлов для выгрузки"):
        items, skipped = _discover_items(
            templates_root=templates_root,
            include_global=args.include_global,
            global_root=global_root,
            manifest_map=manifest_map,
        )

    only_regex: Optional[re.Pattern[str]] = None
    if args.only and args.only.startswith("re:"):
        try:
            only_regex = re.compile(args.only[3:], re.IGNORECASE)
        except re.error as exc:
            raise RuntimeError(f"Некорректный regex в --only: {exc}") from exc

    if args.only:
        items = [item for item in items if _matches_only(item, args.only, only_regex)]
    if args.reverse:
        items = list(reversed(items))
    if args.limit is not None:
        items = items[: args.limit]

    _step_done("Файлы к обработке", str(len(items)))
    if skipped:
        _info(f"Пропущено файлов: {len(skipped)}")
    if not items:
        _info("Нет файлов для выгрузки")
        return 0

    report_rows: List[Dict[str, object]] = []

    if args.dry_run:
        for idx, item in enumerate(items, start=1):
            _info(f"{idx:>4}. {item.rel_path} -> {item.page_title}")
            report_rows.append(
                _make_report_row(
                    file_path=item.file_path,
                    page_title=item.page_title,
                    edit_result="dry-run",
                    new_revision_id=None,
                    flaggedrevs_status="unknown",
                )
            )

        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "last_push_report.json"
        report_payload = {
            "summary": {
                "total": len(items),
                "success": 0,
                "failed": 0,
                "pending_review": 0,
                "access_errors": 0,
                "dry_run": True,
                "only_filter": args.only or "",
                "reverse": bool(args.reverse),
                "limit": args.limit,
            },
            "skipped_files": skipped,
            "items": report_rows,
        }
        report_path.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _step_done("Dry-run", "запросы к API не выполнялись")
        _step_done("Отчет", str(report_path))
        return 0

    session = requests.Session()
    user_agent = (config.get("user_agent") or "").strip() or DEFAULT_USER_AGENT
    session.headers.update({"User-Agent": user_agent})

    success_count = 0
    pending_count = 0
    access_error_count = 0
    failed_count = 0

    try:
        with Spinner("Авторизация в MediaWiki"):
            mw_login(session, api_url, config["username"], config["password"])
        _step_done("Авторизация", "успешно")

        with Spinner("Получение CSRF token"):
            csrf_token = mw_get_csrf_token(session, api_url)
        _step_done("CSRF token", "получен")

        with Spinner("Проверка прав пользователя"):
            rights = _get_user_rights(session, api_url)
        can_review = bool({"review", "validate"} & rights)
        review_enabled = (not args.no_review) and can_review
        _step_done("Review rights", "есть" if can_review else "нет")
        if args.no_review:
            _info("Review отключен флагом --no-review")

        with Spinner("Выгрузка страниц") as sp:
            total = len(items)
            for idx, item in enumerate(items, start=1):
                sp.update(f"{idx}/{total}  {item.page_title}")
                try:
                    text = item.file_path.read_text(encoding="utf-8")
                    attempts_left = args.editconflict_retries + 1
                    new_revid: Optional[int] = None
                    while attempts_left > 0:
                        attempts_left -= 1
                        _old_text, basets, startts = _get_page_state(
                            session, api_url, item.page_title
                        )
                        try:
                            result = mw_edit(
                                session=session,
                                api_url=api_url,
                                title=item.page_title,
                                text=text,
                                summary=args.summary,
                                csrf_token=csrf_token,
                                minor=args.minor,
                                bot=args.bot,
                                basetimestamp=basets,
                                starttimestamp=startts,
                            )
                            new_revid = _parse_int(result.get("newrevid"))
                            break
                        except RuntimeError as exc:
                            error_text = str(exc)
                            if attempts_left > 0 and _is_edit_conflict(error_text):
                                continue
                            raise

                    try:
                        flagged = _get_flagged_status(
                            session, api_url, item.page_title, new_revid
                        )
                    except RuntimeError:
                        flagged = "unknown"
                    if flagged == "pending" and review_enabled and new_revid is not None:
                        try:
                            _try_review_revision(
                                session=session,
                                api_url=api_url,
                                csrf_token=csrf_token,
                                revid=new_revid,
                                comment=args.summary,
                            )
                            try:
                                flagged = _get_flagged_status(
                                    session, api_url, item.page_title, new_revid
                                )
                            except RuntimeError:
                                flagged = "unknown"
                        except RuntimeError:
                            # Review is best-effort: keep pending if action failed.
                            flagged = "pending"

                    success_count += 1
                    if flagged == "pending":
                        pending_count += 1

                    report_rows.append(
                        _make_report_row(
                            file_path=item.file_path,
                            page_title=item.page_title,
                            edit_result="success",
                            new_revision_id=new_revid,
                            flaggedrevs_status=flagged,
                        )
                    )
                except Exception as exc:
                    failed_count += 1
                    error_text = str(exc)
                    if _is_access_error(error_text):
                        access_error_count += 1
                    report_rows.append(
                        _make_report_row(
                            file_path=item.file_path,
                            page_title=item.page_title,
                            edit_result="fail",
                            new_revision_id=None,
                            flaggedrevs_status="unknown",
                            error_message=error_text,
                        )
                    )
    finally:
        session.close()

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "last_push_report.json"
    report_payload = {
        "summary": {
            "total": len(items),
            "success": success_count,
            "failed": failed_count,
            "pending_review": pending_count,
            "access_errors": access_error_count,
            "dry_run": False,
            "only_filter": args.only or "",
            "reverse": bool(args.reverse),
            "limit": args.limit,
        },
        "skipped_files": skipped,
        "items": report_rows,
    }
    report_path.write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _step_done("Обновлено страниц", str(success_count))
    _step_done("Pending review", str(pending_count))
    _step_done("Ошибки доступа/защиты", str(access_error_count))
    _step_done("Ошибок всего", str(failed_count))
    _step_done("Отчет", str(report_path))
    return 0 if failed_count == 0 else 1


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
