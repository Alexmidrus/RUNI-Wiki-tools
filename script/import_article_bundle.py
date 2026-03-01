#!/usr/bin/env python3
"""Import an article page (and optionally its images) from wiki into data/article."""

from __future__ import annotations

import argparse
import ssl
import sys
from pathlib import Path
from typing import Optional, Sequence

from console_ui import (
    Spinner,
    _DIM,
    _RESET,
    _YELLOW,
    _header,
    _info,
    _step_done,
)
from project_paths import default_article_root, resolve_path_in_data
from wiki_api import (
    detect_api_endpoint,
    fetch_binary,
    fetch_image_urls,
    fetch_page_images,
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


def write_binary(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    default_output = default_article_root()
    parser = argparse.ArgumentParser(
        description=(
            "Импортирует разметку статьи (и, опционально, изображения) "
            "с вики в папку data/article/<НазваниеСтатьи>/."
        )
    )
    parser.add_argument("article_name", help="Название статьи (например: Imperial Navy Slicer)")
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
        "--include-images",
        action="store_true",
        help="Скачать изображения, используемые в статье",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Отключить проверку SSL-сертификата (если у вики проблемы с TLS)",
    )
    return parser.parse_args(argv)


def run_import(args: argparse.Namespace, ssl_context: Optional[ssl.SSLContext]) -> None:
    output_root = resolve_path_in_data(args.output_root, "article")
    base_url = normalize_base_url(args.wiki_base_url)
    article_name = args.article_name.strip()

    _header(f"Импорт статьи: {article_name}")

    # 1. API endpoint
    if args.api_endpoint:
        api_endpoint = args.api_endpoint.rstrip("/")
        _step_done("API endpoint", api_endpoint)
    else:
        with Spinner("Поиск API endpoint"):
            api_endpoint = detect_api_endpoint(base_url, ssl_context=ssl_context)
        _step_done("API endpoint", api_endpoint)

    # 2. Fetch article markup
    with Spinner(f"Загрузка разметки {_DIM}{article_name}{_RESET}"):
        content_map = fetch_titles_content(
            api_endpoint, [article_name], ssl_context=ssl_context
        )
    article_content = content_map.get(article_name)
    if not article_content:
        raise RuntimeError(f"Статья не найдена или пуста: {article_name}")
    _step_done("Разметка загружена")

    # 3. Prepare output directory
    safe_name = sanitize_filename(article_name)
    target_dir = output_root / safe_name
    target_dir.mkdir(parents=True, exist_ok=True)

    # 4. Save article markup
    article_file = target_dir / f"{safe_name}_article"
    write_text(article_file, article_content)
    _step_done("Сохранена разметка", article_file.name)

    # 5. If name has unsafe chars — write real_name file
    if has_unsafe_chars(article_name):
        real_name_file = target_dir / "real_name"
        write_text(real_name_file, article_name)
        _info(f"Создан real_name (оригинальное имя: {article_name})")

    # 6. Download images (only with --include-images)
    if args.include_images:
        with Spinner("Получение списка изображений"):
            image_titles = fetch_page_images(api_endpoint, article_name, ssl_context=ssl_context)
        _step_done("Изображения", f"{len(image_titles)} найдено")

        image_urls = {}
        if image_titles:
            with Spinner("Получение URL изображений"):
                image_urls = fetch_image_urls(api_endpoint, image_titles, ssl_context=ssl_context)

        downloaded = 0
        failed = 0
        if image_urls:
            with Spinner("Скачивание изображений") as sp:
                for file_title, url in image_urls.items():
                    # File:Name.png -> Name.png
                    filename = file_title.split(":", 1)[-1] if ":" in file_title else file_title
                    safe_img = sanitize_filename(filename)
                    sp.update(f"{downloaded + 1}/{len(image_urls)}  {safe_img}")
                    try:
                        data = fetch_binary(url, ssl_context=ssl_context)
                        write_binary(target_dir / safe_img, data)
                        downloaded += 1
                    except Exception as exc:
                        failed += 1
                        _info(f"Не удалось скачать {filename}: {exc}")
            detail = f"{downloaded} скачано"
            if failed:
                detail += f", {failed} ошибок"
            _step_done("Изображения", detail)

    _info(f"Папка: {target_dir}")
    print(f"\nГотово: {article_name}")
    print(f"Папка: {target_dir}")


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
