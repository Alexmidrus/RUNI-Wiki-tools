#!/usr/bin/env python3
"""Import a template page and its /doc + /styles.css from wiki into data/templates."""

from __future__ import annotations

import argparse
import ssl
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from project_paths import default_templates_root, resolve_path_in_data
from wiki_api import (
    detect_api_endpoint,
    fetch_json,
    fetch_titles_content,
    make_ssl_context,
    normalize_base_url,
    run_with_ssl_fallback,
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


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    default_output = default_templates_root()
    parser = argparse.ArgumentParser(
        description=(
            "Импортирует код шаблона, шаблона/doc и шаблона/styles.css "
            "с вики в папку data/templates/<ИмяШаблона>/."
        )
    )
    parser.add_argument("template_name", help="Имя шаблона (например: ShipArticle)")
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
    return parser.parse_args(argv)


def run_import(args: argparse.Namespace, ssl_context: Optional[ssl.SSLContext]) -> None:
    output_root = resolve_path_in_data(args.output_root, "templates")
    base_url = normalize_base_url(args.wiki_base_url)
    api_endpoint = (
        args.api_endpoint.rstrip("/")
        if args.api_endpoint
        else detect_api_endpoint(base_url, ssl_context=ssl_context)
    )

    _general, primary_prefix, prefixes_list = get_siteinfo(
        api_endpoint, ssl_context=ssl_context
    )
    prefixes = set(prefixes_list)

    template_name = normalize_template_name(args.template_name, prefixes)
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

    missing = []
    if doc_content is None:
        missing.append(doc_title)
    if css_content is None:
        missing.append(css_title)

    print(f"API endpoint: {api_endpoint}")
    print(f"Шаблон: {main_title}")
    print(f"Папка: {target_dir}")
    print(f"Сохранен: {target_main.name}")
    if doc_content is not None:
        print(f"Сохранен: {target_doc.name}")
    if css_content is not None:
        print(f"Сохранен: {target_css.name}")
    if missing:
        print("Внимание: страницы не найдены, файлы не создавались:")
        for title in missing:
            print(f"  - {title}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    ssl_context = make_ssl_context(args.insecure)
    try:
        run_with_ssl_fallback(
            run_import, args=(args,), kwargs={"ssl_context": ssl_context},
            insecure=args.insecure,
        )
        return 0
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
