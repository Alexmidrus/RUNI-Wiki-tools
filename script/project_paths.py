"""Project path helpers: root, data dir, and safe output resolving."""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    return project_root() / "data"


def default_templates_root() -> Path:
    return data_root() / "templates"


def default_article_root() -> Path:
    return data_root() / "article"


def default_category_root() -> Path:
    return data_root() / "category"


def default_source_url_root() -> Path:
    return data_root() / "source_url"


def resolve_path_in_data(user_path: str | None, default_subdir: str) -> Path:
    """Resolve *user_path* to an absolute path strictly inside project data/.

    - If *user_path* is empty, uses data/<default_subdir>.
    - Relative paths are treated as paths inside data/.
    - Absolute paths are allowed only if they are inside data/.
    """
    data_dir = data_root().resolve()
    if user_path:
        raw_path = Path(user_path)
        candidate = raw_path if raw_path.is_absolute() else (data_dir / raw_path)
    else:
        candidate = data_dir / default_subdir

    resolved = candidate.resolve()
    try:
        resolved.relative_to(data_dir)
    except ValueError as exc:
        raise RuntimeError(f"Путь вывода должен быть внутри {data_dir}") from exc
    return resolved
