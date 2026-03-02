#!/usr/bin/env python3
"""Import template pages from wiki into data/templates."""

from __future__ import annotations

import argparse
import ssl
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from console_ui import (
    Spinner,
    _DIM,
    _RESET,
    _YELLOW,
    _header,
    _info,
    _step_done,
)
from project_paths import default_templates_root, resolve_path_in_data
from wiki_api import (
    detect_api_endpoint,
    fetch_json,
    fetch_titles_content,
    iter_allpages,
    make_ssl_context,
    normalize_base_url,
    run_with_ssl_fallback,
)

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


def extract_template_namespace_data(query: Dict) -> Tuple[str, List[str]]:
    namespaces = query.get("namespaces", {})
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


def get_siteinfo(
    api_endpoint: str, ssl_context: Optional[ssl.SSLContext] = None
) -> Tuple[Dict, str, List[str]]:
    data = fetch_json(
        api_endpoint,
        {
            "action": "query",
            "meta": "siteinfo",
            "siprop": "general|namespaces|namespacealiases",
            "format": "json",
        },
        ssl_context=ssl_context,
    )
    query = data.get("query", {})
    general = query.get("general", {})
    namespaces = query.get("namespaces", {})
    if not general:
        raise RuntimeError("API вернул неполный siteinfo: отсутствует general")
    if "10" not in namespaces:
        raise RuntimeError("На вики не найден namespace 10 (Template)")
    primary_prefix, prefixes = extract_template_namespace_data(query)
    return general, primary_prefix, prefixes


def normalize_template_name(input_name: str, template_prefixes: Set[str]) -> str:
    value = input_name.strip().lstrip(":")
    prefix, sep, rest = value.partition(":")
    if sep and prefix.strip().lower() in template_prefixes:
        value = rest.strip()

    if "/" in value:
        value = value.split("/", 1)[0].strip()
    if not value:
        raise RuntimeError("Пустое имя шаблона после нормализации")
    return value


def split_namespace_title(title: str) -> Tuple[str, str]:
    prefix, sep, rest = title.partition(":")
    if not sep:
        return "", ""
    return prefix.strip().lower(), rest


def is_importable_template_title(title: str, template_prefixes: Set[str]) -> bool:
    prefix, short_name = split_namespace_title(title)
    if not short_name:
        return False
    if prefix not in template_prefixes:
        return False

    lower = short_name.lower()
    # Mass import should only target base templates, not arbitrary subpages.
    if "/" in short_name:
        return False
    if any(lower.endswith(suffix) for suffix in SERVICE_SUBPAGE_SUFFIXES):
        return False
    if "/doc/" in lower or "/documentation/" in lower:
        return False

    return True


def collect_template_names(
    api_endpoint: str,
    template_prefixes: Set[str],
    ssl_context: Optional[ssl.SSLContext],
) -> List[str]:
    names: Set[str] = set()
    scanned = 0
    with Spinner("Получение списка шаблонов") as sp:
        for title in iter_allpages(api_endpoint, 10, ssl_context=ssl_context):
            scanned += 1
            if scanned % 100 == 0:
                sp.update(f"проверено {scanned}")
            if not is_importable_template_title(title, template_prefixes):
                continue
            names.add(normalize_template_name(title, template_prefixes))
        sp.update(f"проверено {scanned}")
    return sorted(names)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def import_template(
    *,
    api_endpoint: str,
    output_root: Path,
    primary_prefix: str,
    template_prefixes: Set[str],
    input_name: str,
    ssl_context: Optional[ssl.SSLContext],
) -> Tuple[str, Path, bool, bool]:
    template_name = normalize_template_name(input_name, template_prefixes)
    main_title = f"{primary_prefix}:{template_name}"
    doc_title = f"{primary_prefix}:{template_name}/doc"
    css_title = f"{primary_prefix}:{template_name}/styles.css"

    content_map = fetch_titles_content(
        api_endpoint,
        [main_title, doc_title, css_title],
        ssl_context=ssl_context,
    )

    main_content = content_map.get(main_title)
    if not main_content:
        raise RuntimeError(f"Основной шаблон не найден или пуст: {main_title}")

    target_dir = output_root / template_name
    target_main = target_dir / template_name
    target_doc = target_dir / f"{template_name}_doc"
    target_css = target_dir / f"{template_name}_styles.css"

    write_text(target_main, main_content)

    doc_content = content_map.get(doc_title)
    css_content = content_map.get(css_title)
    if doc_content is not None:
        write_text(target_doc, doc_content)
    if css_content is not None:
        write_text(target_css, css_content)

    return main_title, target_dir, (doc_content is not None), (css_content is not None)


def is_retryable_import_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in RETRYABLE_ERROR_SUBSTRINGS)


def import_template_with_retry(
    *,
    api_endpoint: str,
    output_root: Path,
    primary_prefix: str,
    template_prefixes: Set[str],
    input_name: str,
    ssl_context: Optional[ssl.SSLContext],
    retries: int = 3,
    base_delay_seconds: float = 0.6,
) -> Tuple[str, Path, bool, bool]:
    for attempt in range(retries + 1):
        try:
            return import_template(
                api_endpoint=api_endpoint,
                output_root=output_root,
                primary_prefix=primary_prefix,
                template_prefixes=template_prefixes,
                input_name=input_name,
                ssl_context=ssl_context,
            )
        except Exception as exc:
            if attempt >= retries or not is_retryable_import_error(exc):
                raise
            time.sleep(base_delay_seconds * (2 ** attempt))

    raise RuntimeError("Непредвиденная ошибка повторных попыток импорта шаблона")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    default_output = default_templates_root()
    parser = argparse.ArgumentParser(
        description=(
            "Импортирует код шаблона, шаблона/doc и шаблона/styles.css "
            "с вики в папку data/templates/<ИмяШаблона>/."
        )
    )
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
        help=(
            "Папка вывода внутри data/ или абсолютный путь внутри data/ "
            f"(по умолчанию: {default_output})"
        ),
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Отключить проверку SSL-сертификата (если у вики проблемы с TLS)",
    )

    ns = parser.parse_args(argv)
    if ns.all and ns.template_name:
        parser.error("Используйте либо template_name, либо --all")
    if not ns.all and not ns.template_name:
        parser.error("Укажите template_name или --all")
    return ns


def run_import(args: argparse.Namespace, ssl_context: Optional[ssl.SSLContext]) -> None:
    output_root = resolve_path_in_data(args.output_root, "templates")
    base_url = normalize_base_url(args.wiki_base_url)

    mode_title = "Импорт всех шаблонов" if args.all else f"Импорт шаблона: {args.template_name}"
    _header(mode_title)

    # 1. API endpoint
    if args.api_endpoint:
        api_endpoint = args.api_endpoint.rstrip("/")
        _step_done("API endpoint", api_endpoint)
    else:
        with Spinner("Поиск API endpoint"):
            api_endpoint = detect_api_endpoint(base_url, ssl_context=ssl_context)
        _step_done("API endpoint", api_endpoint)

    # 2. Siteinfo + namespace prefixes
    with Spinner("Загрузка siteinfo"):
        _general, primary_prefix, prefixes_list = get_siteinfo(
            api_endpoint, ssl_context=ssl_context
        )
    _step_done("Siteinfo", f"префикс: {primary_prefix}")
    prefixes = set(prefixes_list)

    if args.all:
        template_names = collect_template_names(
            api_endpoint, prefixes, ssl_context=ssl_context
        )
        total = len(template_names)
        _step_done("Список шаблонов", f"{total} шт.")
        if total == 0:
            _info("Нечего импортировать: в namespace 10 не найдено шаблонов")
            return

        imported = 0
        failed = 0
        missing_doc = 0
        missing_css = 0
        errors: List[str] = []

        with Spinner("Импорт шаблонов") as sp:
            for index, template_name in enumerate(template_names, start=1):
                sp.update(f"{index}/{total}  {template_name}")
                try:
                    _main_title, _target_dir, has_doc, has_css = import_template_with_retry(
                        api_endpoint=api_endpoint,
                        output_root=output_root,
                        primary_prefix=primary_prefix,
                        template_prefixes=prefixes,
                        input_name=template_name,
                        ssl_context=ssl_context,
                    )
                    imported += 1
                    if not has_doc:
                        missing_doc += 1
                    if not has_css:
                        missing_css += 1
                except Exception as exc:
                    failed += 1
                    if len(errors) < 10:
                        errors.append(f"{template_name}: {exc}")

        detail = f"{imported}/{total}"
        if failed:
            detail += f", ошибок: {failed}"
        _step_done("Шаблоны импортированы", detail)

        _info(f"Папка: {output_root}")
        _info(f"Без /doc: {missing_doc}")
        _info(f"Без /styles.css: {missing_css}")
        if errors:
            _info("Ошибки (первые 10):")
            for err in errors:
                _info(f"- {err}")

        print(f"\nГотово: импортировано шаблонов {imported} из {total}")
        print(f"Папка: {output_root}")
        return

    template_name = args.template_name or ""

    with Spinner(f"Загрузка страниц {_DIM}{template_name}{_RESET}"):
        main_title, target_dir, has_doc, has_css = import_template_with_retry(
            api_endpoint=api_endpoint,
            output_root=output_root,
            primary_prefix=primary_prefix,
            template_prefixes=prefixes,
            input_name=template_name,
            ssl_context=ssl_context,
        )

    _step_done("Страницы загружены")
    _step_done("Сохранена разметка", f"{Path(target_dir).name}")
    if has_doc:
        _step_done("Сохранена документация")
    if has_css:
        _step_done("Сохранены стили")

    _info(f"Шаблон: {main_title}")
    _info(f"Папка: {target_dir}")
    if not has_doc or not has_css:
        _info("Внимание: страницы не найдены, файлы не создавались:")
        if not has_doc:
            _info(f"- {main_title}/doc")
        if not has_css:
            _info(f"- {main_title}/styles.css")

    print(f"\nГотово: {main_title}")
    print(f"Папка: {target_dir}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    ssl_context = make_ssl_context(args.insecure)
    try:
        run_with_ssl_fallback(
            run_import,
            args=(args,),
            kwargs={"ssl_context": ssl_context},
            insecure=args.insecure,
        )
        return 0
    except Exception as exc:
        print(f"\n  {_YELLOW}Ошибка:{_RESET} {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
