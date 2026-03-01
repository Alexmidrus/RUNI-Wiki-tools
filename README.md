# RUNI Wiki

Инструментарий для офлайн-редактирования контента MediaWiki: шаблоны, статьи, категории и глобальные стили.
Позволяет загружать данные с целевой вики, редактировать локально и выгружать обратно.

Целевая вики: `https://solarmeta.evecraft.ru`

## Структура проекта

```
RUNI_Wiki/
├── template/          # Загруженные шаблоны вики
├── global/            # Глобальные стили и скрипты вики
│   ├── MediaWiki Common.js
│   └── MediaWiki_Common.css
├── article/           # Загруженные статьи и файлы к статьям
├── category/          # Загруженные страницы категорий
├── script/            # API-скрипты для взаимодействия с вики
│   ├── wiki_api.py               # Общие хелперы MediaWiki API
│   ├── console_ui.py             # Общие хелперы консольного UI
│   ├── import_template_bundle.py # Импорт шаблона (+doc, +styles.css)
│   ├── import_article_bundle.py  # Импорт статьи (+изображения)
│   ├── import_category_bundle.py # Импорт страницы категории
│   ├── import_page_urls.py       # Импорт URL страниц в YAML
│   └── exports/                  # Результаты выгрузки (YAML-файлы)
├── AGENTS.md          # Инструкции для AI-агентов
└── README.md
```

## Требования

- Python 3.13+
- Виртуальное окружение `.venv`

## Скрипты

### import_template_bundle.py

Импортирует шаблон, его `/doc` и `/styles.css` с вики в локальную папку.

**Запуск:**

```bash
./.venv/bin/python script/import_template_bundle.py <имя_шаблона>
```

Имя шаблона можно указывать с префиксом пространства имён или без него. Поддерживаемые префиксы: `Шаблон:`, `Template:`. Префикс автоматически распознаётся и отбрасывается при нормализации.

**Примеры:**

```bash
# Базовый запуск
./.venv/bin/python script/import_template_bundle.py ShipArticle

# С указанием другой вики
./.venv/bin/python script/import_template_bundle.py ShipArticle --wiki-base-url https://example.org

# С явным API endpoint
./.venv/bin/python script/import_template_bundle.py ShipArticle --api-endpoint https://example.org/w/api.php

# Без проверки SSL
./.venv/bin/python script/import_template_bundle.py ShipArticle --insecure

# В другую папку
./.venv/bin/python script/import_template_bundle.py ShipArticle --output-root ./my_templates
```

**Параметры:**

| Параметр | Описание | По умолчанию |
|---|---|---|
| `template_name` | Имя шаблона (позиционный) | — |
| `--wiki-base-url` | Базовый URL вики | `https://solarmeta.evecraft.ru` |
| `--api-endpoint` | Явный URL `api.php` | автоопределение |
| `--output-root` | Корневая папка для выгрузки | `templates` |
| `--insecure` | Отключить проверку SSL | выключено |

### import_page_urls.py

Импортирует URL страниц из MediaWiki (шаблоны, категории, статьи) в YAML-файлы.

**Запуск:**

```bash
./.venv/bin/python script/import_page_urls.py <mode>
```

Режимы (`mode`):
- `templates` — шаблоны (namespace 10)
- `categories` — категории (namespace 14)
- `articles` — статьи (namespace 0)
- `all` — все три, в отдельные файлы

**Примеры:**

```bash
# Импортировать только шаблоны
./.venv/bin/python script/import_page_urls.py templates

# Импортировать категории
./.venv/bin/python script/import_page_urls.py categories

# Импортировать статьи
./.venv/bin/python script/import_page_urls.py articles

# Импортировать всё (три файла)
./.venv/bin/python script/import_page_urls.py all

# Шаблоны с служебными подстраницами
./.venv/bin/python script/import_page_urls.py templates --include-service-subpages

# С указанием другой вики
./.venv/bin/python script/import_page_urls.py templates --wiki-base-url https://example.org

# С явным API endpoint
./.venv/bin/python script/import_page_urls.py all --api-endpoint https://example.org/w/api.php

# В указанную папку и файл
./.venv/bin/python script/import_page_urls.py templates --output-dir ./exports --output-file urls.yaml

# Без проверки SSL
./.venv/bin/python script/import_page_urls.py all --insecure
```

**Параметры:**

| Параметр | Описание | По умолчанию |
|---|---|---|
| `mode` | Режим импорта (позиционный) | — |
| `--wiki-base-url` | Базовый URL вики | `https://solarmeta.evecraft.ru` |
| `--api-endpoint` | Явный URL `api.php` | автоопределение |
| `--output-dir` | Папка для YAML-файла | `script/exports` |
| `--output-file` | Имя выходного файла (игнорируется при `all`) | генерируется с таймстампом |
| `--include-service-subpages` | Включить `/doc`, `/styles.css` и т.п. (только для templates) | выключено |
| `--insecure` | Отключить проверку SSL | выключено |

### import_article_bundle.py

Импортирует разметку статьи с вики в локальную папку. При указании флага `--include-images` также скачивает связанные изображения.

**Запуск:**

```bash
./.venv/bin/python script/import_article_bundle.py <название_статьи>
```

Название статьи передаётся как есть (namespace 0, без префикса).

**Примеры:**

```bash
# Только разметка
./.venv/bin/python script/import_article_bundle.py "Imperial Navy Slicer"

# Разметка + изображения
./.venv/bin/python script/import_article_bundle.py "Imperial Navy Slicer" --include-images

# С указанием другой вики
./.venv/bin/python script/import_article_bundle.py "Imperial Navy Slicer" --wiki-base-url https://example.org

# С явным API endpoint
./.venv/bin/python script/import_article_bundle.py "Imperial Navy Slicer" --api-endpoint https://example.org/w/api.php

# Без проверки SSL
./.venv/bin/python script/import_article_bundle.py "Imperial Navy Slicer" --insecure

# В другую папку
./.venv/bin/python script/import_article_bundle.py "Imperial Navy Slicer" --output-root ./my_articles
```

**Параметры:**

| Параметр | Описание | По умолчанию |
|---|---|---|
| `article_name` | Название статьи (позиционный) | — |
| `--wiki-base-url` | Базовый URL вики | `https://solarmeta.evecraft.ru` |
| `--api-endpoint` | Явный URL `api.php` | автоопределение |
| `--output-root` | Корневая папка для выгрузки | `article` |
| `--include-images` | Скачать изображения статьи | выключено |
| `--insecure` | Отключить проверку SSL | выключено |

### import_category_bundle.py

Импортирует разметку страницы категории с вики в локальную папку.

**Запуск:**

```bash
./.venv/bin/python script/import_category_bundle.py <название_категории>
```

Название категории можно указывать с префиксом пространства имён или без него. Поддерживаемые префиксы: `Категория:`, `Category:`. Префикс автоматически распознаётся и отбрасывается при нормализации.

**Примеры:**

```bash
# Базовый запуск (без префикса)
./.venv/bin/python script/import_category_bundle.py "Фрегаты"

# С префиксом — тоже работает
./.venv/bin/python script/import_category_bundle.py "Категория:Фрегаты"

# С указанием другой вики
./.venv/bin/python script/import_category_bundle.py "Фрегаты" --wiki-base-url https://example.org

# С явным API endpoint
./.venv/bin/python script/import_category_bundle.py "Фрегаты" --api-endpoint https://example.org/w/api.php

# Без проверки SSL
./.venv/bin/python script/import_category_bundle.py "Фрегаты" --insecure

# В другую папку
./.venv/bin/python script/import_category_bundle.py "Фрегаты" --output-root ./my_categories
```

**Параметры:**

| Параметр | Описание | По умолчанию |
|---|---|---|
| `category_name` | Название категории (позиционный) | — |
| `--wiki-base-url` | Базовый URL вики | `https://solarmeta.evecraft.ru` |
| `--api-endpoint` | Явный URL `api.php` | автоопределение |
| `--output-root` | Корневая папка для выгрузки | `category` |
| `--insecure` | Отключить проверку SSL | выключено |

## Структура загруженных файлов

### Шаблоны (`template/`)

На каждый шаблон создаётся отдельная папка с именем шаблона. Внутри:

```
template/
└── ShipArticle/
    ├── ShipArticle_template      # Код шаблона
    ├── ShipArticle_styles.css    # Стили шаблона
    └── ShipArticle_doc           # Документация шаблона
```

Именование файлов:
- `{имя шаблона}_template` — сам шаблон
- `{имя шаблона}_styles.css` — стили шаблона
- `{имя шаблона}_doc` — документация шаблона

### Статьи (`article/`)

На каждую статью создаётся отдельная папка с именем статьи. Внутри хранится файл статьи и связанные изображения.

```
article/
└── Imperial Navy Slicer/
    ├── Imperial Navy Slicer_article   # Разметка статьи
    ├── ship_icon.png                  # Изображения к статье (--include-images)
    └── ...
```

Именование файлов:
- `{название статьи}_article` — разметка статьи

Если название статьи содержит символы, недопустимые для файловой системы (`\`, `/`, `:`, `*`, `?`, `"`, `<`, `>`, `|`), они безопасно заменяются, а в папке создаётся файл `real_name`, в который записывается оригинальное название статьи на вики.

### Категории (`category/`)

На каждую категорию создаётся отдельная папка с именем категории. Внутри — файл с разметкой страницы категории.

```
category/
└── Фрегаты/
    └── Фрегаты_category   # Разметка страницы категории
```

Именование файлов:
- `{название категории}_category` — разметка страницы категории

## Поток работы

1. Импортировать актуальные данные с вики через скрипты в `script/`.
2. Редактировать шаблоны, статьи, категории и стили локально.
3. Экспортировать изменения обратно на вики.
