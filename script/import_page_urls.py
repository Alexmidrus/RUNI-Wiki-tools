#!/usr/bin/env python3
"""Import page URLs (templates, categories, articles) into YAML under data/source_url."""

from __future__ import annotations

import argparse
import datetime as dt
import ssl
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urljoin

from console_ui import (
    Spinner,
    _CYAN,
    _DIM,
    _MAGENTA,
    _RESET,
    _YELLOW,
    _header,
    _info,
    _step_done,
    _summary_box,
)
from project_paths import default_source_url_root, resolve_path_in_data
from wiki_api import (
    detect_api_endpoint,
    fetch_json,
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

# Mapping: mode name -> (namespace id, yaml list key, filename prefix, label)
NAMESPACE_MODES: Dict[str, Tuple[int, str, str, str]] = {
    "templates":  (10, "templates",  "template",  "Шаблоны"),
    "categories": (14, "categories", "category",  "Категории"),
    "articles":   (0,  "articles",   "article",   "Статьи"),
}


# ---------------------------------------------------------------------------
# Siteinfo
# ---------------------------------------------------------------------------

def extract_namespace_prefixes(query: Dict, namespace_id: int) -> List[str]:
    """Return sorted lowercase prefixes for *namespace_id* from siteinfo query."""
    ns_key = str(namespace_id)
    namespaces = query.get("namespaces", {})
    ns_info = namespaces.get(ns_key, {})
    namespace_aliases = query.get("namespacealiases", [])

    prefixes: Set[str] = set()

    for key in ("*", "canonical", "name"):
        value = ns_info.get(key)
        if isinstance(value, str) and value.strip():
            prefixes.add(value.strip().lower())

    for alias in namespace_aliases:
        if str(alias.get("id")) == ns_key:
            alias_name = alias.get("*")
            if isinstance(alias_name, str) and alias_name.strip():
                prefixes.add(alias_name.strip().lower())

    return sorted(prefixes)


def get_siteinfo(
    api_endpoint: str, ssl_context: Optional[ssl.SSLContext] = None
) -> Tuple[Dict, Dict]:
    """Return (general_info, full_query) from siteinfo API."""
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
    if not general:
        raise RuntimeError("API вернул неполный siteinfo: отсутствует блок general")
    return general, query


# ---------------------------------------------------------------------------
# Title helpers
# ---------------------------------------------------------------------------

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

    if any(lower.endswith(suffix) for suffix in SERVICE_SUBPAGE_SUFFIXES):
        return False

    if "/doc/" in lower or "/documentation/" in lower:
        return False

    return True


def build_page_url(base_url: str, articlepath: str, title: str) -> str:
    readable_title = title.replace(" ", "_")

    if "$1" in articlepath:
        path = articlepath.replace("$1", readable_title)
    else:
        path = f"/index.php?title={readable_title}"

    return urljoin(f"{base_url}/", path.lstrip("/"))


# ---------------------------------------------------------------------------
# YAML output
# ---------------------------------------------------------------------------

def write_yaml(
    output_path: Path,
    generated_at_utc: str,
    wiki_base_url: str,
    detected_total: int,
    imported_total: int,
    list_key: str,
    urls: List[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        f.write(f'generated_at_utc: "{generated_at_utc}"\n')
        f.write(f'wiki_base_url: "{wiki_base_url}"\n')
        f.write(f"detected_total: {detected_total}\n")
        f.write(f"imported_total: {imported_total}\n")
        f.write(f"{list_key}:\n")
        for url in urls:
            escaped_url = url.replace("\\", "\\\\").replace('"', '\\"')
            f.write(f'  - "{escaped_url}"\n')


# ---------------------------------------------------------------------------
# Core import logic
# ---------------------------------------------------------------------------

def collect_titles(
    api_endpoint: str,
    ns_id: int,
    label: str,
    ssl_context: Optional[ssl.SSLContext],
) -> List[str]:
    """Fetch all titles from a namespace with a live counter spinner."""
    titles: List[str] = []
    with Spinner(f"Загрузка страниц {_MAGENTA}{label}{_RESET}") as sp:
        for title in iter_allpages(api_endpoint, ns_id, ssl_context=ssl_context):
            titles.append(title)
            if len(titles) % 50 == 0:
                sp.update(f"{len(titles)} стр.")
        sp.update(f"{len(titles)} стр.")
    return titles


def import_namespace(
    *,
    mode: str,
    api_endpoint: str,
    siteinfo_query: Dict,
    articlepath: str,
    base_url: str,
    output_dir: Path,
    output_file: Optional[str],
    now: dt.datetime,
    include_service_subpages: bool,
    ssl_context: Optional[ssl.SSLContext],
) -> Tuple[str, int, int, Path]:
    """Import one namespace. Returns (label, detected, imported, output_path)."""
    ns_id, list_key, file_prefix, label = NAMESPACE_MODES[mode]

    generated_at_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    filename = output_file or f"{file_prefix}_urls_{now.strftime('%Y%m%d_%H%M%S')}.yaml"
    output_path = output_dir / filename

    detected_titles = collect_titles(api_endpoint, ns_id, label, ssl_context)

    # Filtering: only templates support service-subpage filtering
    if mode == "templates" and not include_service_subpages:
        template_prefixes = set(extract_namespace_prefixes(siteinfo_query, 10))
        template_prefixes.add("template")  # safety fallback
        imported_titles = sorted(
            {
                title
                for title in detected_titles
                if is_importable_template_title(title, template_prefixes)
            }
        )
    else:
        imported_titles = sorted(set(detected_titles))

    urls = [build_page_url(base_url, articlepath, title) for title in imported_titles]

    with Spinner(f"Запись YAML {_DIM}{filename}{_RESET}"):
        write_yaml(
            output_path=output_path,
            generated_at_utc=generated_at_utc,
            wiki_base_url=base_url,
            detected_total=len(detected_titles),
            imported_total=len(urls),
            list_key=list_key,
            urls=urls,
        )

    detected = len(detected_titles)
    imported = len(urls)
    _step_done(
        f"{label}",
        f"{detected} найдено, {imported} импортировано",
    )

    return label, detected, imported, output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    default_output = default_source_url_root()
    parser = argparse.ArgumentParser(
        description=(
            "Импортирует URL страниц из MediaWiki (шаблоны, категории, статьи) в YAML."
        )
    )
    parser.add_argument(
        "mode",
        choices=["templates", "categories", "articles", "all"],
        help="Режим импорта: templates (ns 10), categories (ns 14), articles (ns 0), all",
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
        "--output-dir",
        help=(
            "Папка для YAML внутри data/ или абсолютный путь внутри data/ "
            f"(по умолчанию: {default_output})"
        ),
    )
    parser.add_argument(
        "--output-file",
        help="Имя выходного YAML файла (работает для одного namespace, игнорируется при all)",
    )
    parser.add_argument(
        "--include-service-subpages",
        action="store_true",
        help="Включать служебные подстраницы шаблонов (/doc, /styles.css и т.п.)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Отключить проверку SSL-сертификата (если API с проблемным TLS)",
    )
    return parser.parse_args(argv)


def run_import(args: argparse.Namespace, ssl_context: Optional[ssl.SSLContext]) -> None:
    output_dir = resolve_path_in_data(args.output_dir, "source_url")
    base_url = normalize_base_url(args.wiki_base_url)

    if args.mode == "all":
        modes = list(NAMESPACE_MODES.keys())
    else:
        modes = [args.mode]

    mode_labels = ", ".join(NAMESPACE_MODES[m][3] for m in modes)
    _header(f"Импорт URL: {mode_labels}")

    # Resolve API endpoint
    if args.api_endpoint:
        api_endpoint = args.api_endpoint.rstrip("/")
        _step_done("API endpoint", api_endpoint)
    else:
        with Spinner("Поиск API endpoint"):
            api_endpoint = detect_api_endpoint(base_url, ssl_context=ssl_context)
        _step_done("API endpoint", api_endpoint)

    # Fetch siteinfo
    with Spinner("Загрузка siteinfo"):
        general, siteinfo_query = get_siteinfo(api_endpoint, ssl_context=ssl_context)
    articlepath = general.get("articlepath", "/index.php?title=$1")
    site_name = general.get("sitename", "?")
    _step_done("Siteinfo", site_name)

    now = dt.datetime.now(dt.timezone.utc)

    # --output-file is ignored when mode is 'all'
    output_file = args.output_file if args.mode != "all" else None

    _info(f"Папка вывода: {output_dir}")
    sys.stderr.write("\n")
    sys.stderr.flush()

    # Import each namespace
    results: List[Tuple[str, str, str, str, str]] = []
    t0 = time.monotonic()

    for mode in modes:
        label, detected, imported, path = import_namespace(
            mode=mode,
            api_endpoint=api_endpoint,
            siteinfo_query=siteinfo_query,
            articlepath=articlepath,
            base_url=base_url,
            output_dir=output_dir,
            output_file=output_file,
            now=now,
            include_service_subpages=args.include_service_subpages,
            ssl_context=ssl_context,
        )
        filtered = str(detected - imported)
        results.append((label, str(detected), str(imported), filtered, str(path)))

    elapsed = time.monotonic() - t0
    _summary_box(results)
    _info(f"Готово за {elapsed:.1f} сек.\n")


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
        print(f"\n  {_YELLOW}Ошибка:{_RESET} {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
