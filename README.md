# RUNI Wiki

Инструментарий для офлайн-редактирования контента MediaWiki: шаблоны, статьи, категории и глобальные стили.

Целевая вики по умолчанию: `https://solarmeta.evecraft.ru`

## Ключевые изменения структуры

- Единая точка входа: `main.py` в корне проекта.
- Все создаваемые скриптами папки и файлы находятся только внутри `data/`.

## Структура проекта

```text
RUNI_Wiki/
├── main.py                  # Единый CLI entrypoint
├── data/                    # Все импортируемые/генерируемые данные
│   ├── templates/           # Импортированные шаблоны
│   ├── article/             # Импортированные статьи (+изображения)
│   ├── category/            # Импортированные категории
│   ├── source_url/          # YAML со списками URL
│   └── global/              # Глобальные файлы MediaWiki
│       ├── MediaWiki Common.js
│       └── MediaWiki_Common.css
├── script/
│   ├── project_paths.py
│   ├── wiki_api.py
│   ├── console_ui.py
│   ├── import_template_bundle.py
│   ├── import_article_bundle.py
│   ├── import_category_bundle.py
│   ├── import_page_urls.py
│   ├── push_page_via_api.py
│   └── push_templates_to_wiki.py
├── AGENTS.md
└── README.md
```

## Требования

- Python 3.13+
- Виртуальное окружение `.venv`
- Python-пакет `requests` (для команд `push`, `push-templates`)

## Единая точка входа

Общий формат:

```bash
python main.py <command> [аргументы]
```

Доступные команды:

- `template` — импорт шаблона (+`/doc`, +`/styles.css`)
- `article` — импорт статьи (+опционально изображения)
- `category` — импорт страницы категории
- `urls` — импорт URL страниц в YAML
- `push` — загрузка/обновление страницы на MediaWiki из локального файла
- `push-templates` — массовая выгрузка шаблонов и (опционально) `data/global/*` на MediaWiki

Для справки по конкретной команде:

```bash
python main.py <command> --help
```

## Команды

### template

Импортирует один шаблон или все шаблоны в `data/templates/<ИмяШаблона>/`.

```bash
python main.py template <имя_шаблона>
python main.py template --all
```

Примеры:

```bash
python main.py template ShipArticle
python main.py template --all
python main.py template ShipArticle --wiki-base-url https://example.org
python main.py template ShipArticle --api-endpoint https://example.org/w/api.php
python main.py template ShipArticle --insecure
python main.py template ShipArticle --output-root templates_custom
```

Параметры:

| Параметр | Описание | По умолчанию |
|---|---|---|
| `template_name` | Имя шаблона (позиционный, опционален при `--all`) | — |
| `--all` | Импортировать все шаблоны namespace 10 | выключено |
| `--wiki-base-url` | Базовый URL вики | `https://solarmeta.evecraft.ru` |
| `--api-endpoint` | Явный URL `api.php` | автоопределение |
| `--output-root` | Подпапка внутри `data/` или абсолютный путь внутри `data/` | `data/templates` |
| `--insecure` | Отключить проверку SSL | выключено |
### article

Импортирует статью в `data/article/<НазваниеСтатьи>/`.

```bash
python main.py article <название_статьи>
```

Примеры:

```bash
python main.py article "Imperial Navy Slicer"
python main.py article "Imperial Navy Slicer" --include-images
python main.py article "Imperial Navy Slicer" --wiki-base-url https://example.org
python main.py article "Imperial Navy Slicer" --api-endpoint https://example.org/w/api.php
python main.py article "Imperial Navy Slicer" --insecure
python main.py article "Imperial Navy Slicer" --output-root article_custom
```

Параметры:

| Параметр | Описание | По умолчанию |
|---|---|---|
| `article_name` | Название статьи (позиционный) | — |
| `--wiki-base-url` | Базовый URL вики | `https://solarmeta.evecraft.ru` |
| `--api-endpoint` | Явный URL `api.php` | автоопределение |
| `--output-root` | Подпапка внутри `data/` или абсолютный путь внутри `data/` | `data/article` |
| `--include-images` | Скачать изображения статьи | выключено |
| `--insecure` | Отключить проверку SSL | выключено |

### category

Импортирует категорию в `data/category/<НазваниеКатегории>/`.

```bash
python main.py category <название_категории>
```

Примеры:

```bash
python main.py category "Фрегаты"
python main.py category "Категория:Фрегаты"
python main.py category "Фрегаты" --wiki-base-url https://example.org
python main.py category "Фрегаты" --api-endpoint https://example.org/w/api.php
python main.py category "Фрегаты" --insecure
python main.py category "Фрегаты" --output-root category_custom
```

Параметры:

| Параметр          | Описание | По умолчанию |
|-------------------|---|---|
| `category_name`   | Название категории (позиционный) | — |
| `--wiki-base-url` | Базовый URL вики | `https://solarmeta.evecraft.ru` |
| `--api-endpoint`  | Явный URL `api.php` | автоопределение |
| `--outСоput-root` | Подпапка внутри `data/` или абсолютный путь внутри `data/` | `data/category` |
| `--insecure`      | Отключить проверку SSL | выключено |

### urls

Импортирует URL страниц в YAML в `data/source_url/`.

```bash
python main.py urls <mode>
```

Режимы:

- `templates` — шаблоны (namespace 10)
- `categories` — категории (namespace 14)
- `articles` — статьи (namespace 0)
- `all` — все три в отдельные файлы

Примеры:

```bash
python main.py urls templates
python main.py urls categories
python main.py urls articles
python main.py urls all
python main.py urls templates --include-service-subpages
python main.py urls templates --wiki-base-url https://example.org
python main.py urls all --api-endpoint https://example.org/w/api.php
python main.py urls templates --output-dir exports_custom --output-file urls.yaml
python main.py urls all --insecure
```

Параметры:

| Параметр | Описание | По умолчанию |
|---|---|---|
| `mode` | Режим импорта (позиционный) | — |
| `--wiki-base-url` | Базовый URL вики | `https://solarmeta.evecraft.ru` |
| `--api-endpoint` | Явный URL `api.php` | автоопределение |
| `--output-dir` | Подпапка внутри `data/` или абсолютный путь внутри `data/` | `data/source_url` |
| `--output-file` | Имя выходного файла (игнорируется при `all`) | генерируется с таймстампом |
| `--include-service-subpages` | Включить `/doc`, `/styles.css` и т.п. (только для templates) | выключено |
| `--insecure` | Отключить проверку SSL | выключено |

### push

Загружает/обновляет страницу на целевой MediaWiki через API (`action=edit`) из локального файла `.wiki`.

```bash
python main.py push --file data/pages/Avatar.wiki
```

Параметры:

| Параметр | Описание | По умолчанию |
|---|---|---|
| `--api-url` | URL `api.php` (если не указан, берётся из `MW_API_URL`) | из env |
| `--file` | Путь к локальному файлу статьи (UTF-8) | — |
| `--title` | Явный title страницы (иначе имя файла без расширения) | из имени файла |
| `--summary` | Комментарий правки | `Sync from local` |
| `--minor` | Флаг minor edit | выключено |
| `--bot` | Флаг bot edit | выключено |
| `--dry-run` | Показать параметры без сетевых запросов | выключено |
| `--skip-if-same` | Пропустить edit, если локальный и текущий текст идентичны | выключено |

Переменные окружения для `push`:

- Обязательные:
  - `MW_API_URL` или `MEDIAWIKI_API_URL`
  - `MW_USERNAME` или `MEDIAWIKI_USERNAME`
  - один из: `MW_BOT_PASSWORD` / `MEDIAWIKI_BOT_PASSWORD` (приоритет), `MW_PASSWORD` / `MEDIAWIKI_PASSWORD`
- Опционально:
  - `MW_USER_AGENT` или `MEDIAWIKI_USER_AGENT`

Шаблон env:

- Используйте файл [`.env.example`](./.env.example) как основу.
- Скопируйте его в `.env` и заполните своими значениями.
- В репозиторий коммитится только `.env.example`; `.env` игнорируется.
- Команды `push` и `push-templates` автоматически загружают `.env` из корня проекта при запуске.

Пример запуска:

```powershell
python main.py push --file data/pages/Avatar.wiki --summary "Sync from local" --skip-if-same
```

Пример dry-run (без сетевых запросов):

```bash
python main.py push --file data/pages/Avatar.wiki --dry-run
```

### push-templates

Массово загружает локальные шаблоны из `data/templates/` в соответствующие страницы MediaWiki.
Дополнительно может выгружать глобальные стили/скрипты из `data/global/`.

Reverse mapping (обратное восстановление title из имени файла):

- `data/templates/<Name>/<Name>` → `Template:<Name>`
- `data/templates/<Name>/<Name>_doc` → `Template:<Name>/doc`
- `data/templates/<Name>/<Name>_styles.css` → `Template:<Name>/styles.css`
- `data/global/MediaWiki_Common.css` → `MediaWiki:Common.css`
- `data/global/MediaWiki Common.js` → `MediaWiki:Common.js`

```bash
python main.py push-templates --dry-run
```

Основные параметры:

| Параметр | Описание | По умолчанию |
|---|---|---|
| `--api-url` | URL `api.php` (если не указан, берется из env) | из env |
| `--templates-root` | Папка шаблонов внутри `data/` | `data/templates` |
| `--include-global` | Также включить файлы из `data/global` | выключено |
| `--global-root` | Папка global внутри `data/` | `data/global` |
| `--manifest` | JSON-карта `relative_path -> page_title` для неоднозначных случаев | не используется |
| `--only` | Фильтр файлов/тайтлов: glob или `re:<regex>` | не задан |
| `--limit` | Ограничить число обрабатываемых файлов | без лимита |
| `--reverse` | Обрабатывать список в обратном порядке | выключено |
| `--dry-run` | Показать сопоставление без API-запросов | выключено |
| `--summary` | Комментарий правки | `Sync templates from local` |
| `--minor` | Отметка minor edit | выключено |
| `--bot` | Отметка bot edit | выключено |
| `--editconflict-retries` | Повторы при `editconflict` | `1` |
| `--no-review` | Не выполнять `action=review` для FlaggedRevs | выключено |
| `--report-dir` | Куда писать JSON-отчет | `data/exports` |

Примеры:

```bash
python main.py push-templates --dry-run --limit 10
python main.py push-templates --only "*_styles.css" --summary "Sync TemplateStyles"
python main.py push-templates --include-global --only "re:^global/.+\\.css$"
python main.py push-templates --reverse --limit 20
```

Отчет пишется в `data/exports/last_push_report.json`:

- `file_path`
- `page_title`
- `edit_result`
- `new_revision_id`
- `flaggedrevs_status` (`stable|pending|unknown`)
- `error_message`

## Правила путей вывода

- Все output-пути резолвятся строго внутри `data/`.
- Относительные пути в `--output-root` и `--output-dir` трактуются как подпапки `data/`.
- Абсолютный путь разрешен только если он находится внутри `data/`.
- Попытка сохранить вне `data/` завершится ошибкой.

## Структура загруженных данных

### Шаблоны (`data/templates/`)

```text
data/templates/
└── ShipArticle/
    ├── ShipArticle
    ├── ShipArticle_doc
    └── ShipArticle_styles.css
```

### Статьи (`data/article/`)

```text
data/article/
└── Imperial Navy Slicer/
    ├── Imperial Navy Slicer_article
    ├── ship_icon.png
    └── ...
```

### Категории (`data/category/`)

```text
data/category/
└── Фрегаты/
    └── Фрегаты_category
```

### URL-выгрузки (`data/source_url/`)

```text
data/source_url/
├── template_urls_YYYYMMDD_HHMMSS.yaml
├── article_urls_YYYYMMDD_HHMMSS.yaml
└── category_urls_YYYYMMDD_HHMMSS.yaml
```

### Глобальные файлы (`data/global/`)

```text
data/global/
├── MediaWiki Common.js
└── MediaWiki_Common.css
```

## Поток работы

1. Импортировать актуальные данные с вики (`python main.py ...`).
2. Редактировать данные локально в `data/` (включая `data/global/`).
3. Выполнять экспорт обратно на вики (когда будут подключены export-скрипты).
