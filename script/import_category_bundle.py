#!/usr/bin/env python3
"""Import a category page markup from wiki into a local category folder."""

from __future__ import annotations

import argparse
import ssl
import sys
from pathlib import Path
from typing import Dict, Optional, Set

from console_ui import (
    Spinner,
    _DIM,
    _RESET,
    _YELLOW,
    _header,
    _info,
    _step_done,
)
from wiki_api import (
    detect_api_endpoint,
    fetch_json,
    fetch_titles_content,
    has_unsafe_chars,
    make_ssl_context,
    normalize_base_url,
    run_with_ssl_fallback,
    sanitize_filename,
)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_category_siteinfo(
    api_endpoint: str, ssl_context: Optional[ssl.SSLContext] = None
) -> tuple[str, Set[str]]:
    """Return (primary_prefix, all_lowercase_prefixes) for namespace 14."""
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


def normalize_category_name(input_name: str, category_prefixes: Set[str]) -> str:
    """Strip category namespace prefix if present."""
    value = input_name.strip().lstrip(":")
    prefix, sep, rest = value.partition(":")
    if sep and prefix.strip().lower() in category_prefixes:
        value = rest.strip()
    if not value:
        raise RuntimeError("Пустое имя категории после нормализации")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Импортирует разметку страницы категории "
            "с вики в папку category/<НазваниеКатегории>/."
        )
    )
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
        default="category",
        help="Корневая папка для выгрузки (по умолчанию: category)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Отключить проверку SSL-сертификата (если у вики проблемы с TLS)",
    )
    return parser.parse_args()


def run_import(args: argparse.Namespace, ssl_context: Optional[ssl.SSLContext]) -> None:
    base_url = normalize_base_url(args.wiki_base_url)

    _header(f"Импорт категории: {args.category_name}")

    # 1. API endpoint
    if args.api_endpoint:
        api_endpoint = args.api_endpoint.rstrip("/")
        _step_done("API endpoint", api_endpoint)
    else:
        with Spinner("Поиск API endpoint"):
            api_endpoint = detect_api_endpoint(base_url, ssl_context=ssl_context)
        _step_done("API endpoint", api_endpoint)

    # 2. Siteinfo — get category prefixes
    with Spinner("Загрузка siteinfo"):
        primary_prefix, prefixes = get_category_siteinfo(api_endpoint, ssl_context=ssl_context)
    _step_done("Siteinfo", f"префикс: {primary_prefix}")

    # 3. Normalize name — strip prefix if given
    category_name = normalize_category_name(args.category_name, prefixes)
    full_title = f"{primary_prefix}:{category_name}"

    # 4. Fetch category markup
    with Spinner(f"Загрузка разметки {_DIM}{full_title}{_RESET}"):
        content_map = fetch_titles_content(
            api_endpoint, [full_title], ssl_context=ssl_context
        )
    category_content = content_map.get(full_title)
    if not category_content:
        raise RuntimeError(f"Категория не найдена или пуста: {full_title}")
    _step_done("Разметка загружена")

    # 5. Prepare output directory
    safe_name = sanitize_filename(category_name)
    target_dir = Path(args.output_root).resolve() / safe_name
    target_dir.mkdir(parents=True, exist_ok=True)

    # 6. Save category markup
    category_file = target_dir / f"{safe_name}_category"
    write_text(category_file, category_content)
    _step_done("Сохранена разметка", category_file.name)

    # 7. If name has unsafe chars — write real_name file
    if has_unsafe_chars(category_name):
        real_name_file = target_dir / "real_name"
        write_text(real_name_file, category_name)
        _info(f"Создан real_name (оригинальное имя: {category_name})")

    _info(f"Папка: {target_dir}")
    print(f"\nГотово: {full_title}")
    print(f"Папка: {target_dir}")


def main() -> int:
    args = parse_args()
    ssl_context = make_ssl_context(args.insecure)
    try:
        run_with_ssl_fallback(
            run_import, args=(args,), kwargs={"ssl_context": ssl_context},
            insecure=args.insecure,
        )
        return 0
    except Exception as exc:
        print(f"\n  {_YELLOW}Ошибка:{_RESET} {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
