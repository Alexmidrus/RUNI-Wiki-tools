"""Storage subsystem to manage isolation inside data/ folder."""

from __future__ import annotations

import re
from pathlib import Path


class DataStorage:
    """Encapsulates file system operations strictly within the project's data directory."""

    UNSAFE_CHARS_REGEX = re.compile(r'[\\/:*?"<>|]')

    def __init__(self, root_dir: Path | None = None) -> None:
        if root_dir is None:
            self.root = Path(__file__).resolve().parent.parent.parent / "data"
        else:
            self.root = root_dir.resolve()

    def get_default_subdir(self, subdir_name: str) -> Path:
        return self.root / subdir_name

    def resolve_path(self, user_path: str | None, default_subdir: str) -> Path:
        """Resolve *user_path* to an absolute path strictly inside project data/.

        - If *user_path* is empty, uses root/<default_subdir>.
        - Relative paths are treated as paths inside root.
        - Absolute paths are allowed only if they are inside root.
        """
        if user_path:
            raw_path = Path(user_path)
            candidate = raw_path if raw_path.is_absolute() else (self.root / raw_path)
        else:
            candidate = self.root / default_subdir

        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise RuntimeError(f"Путь вывода должен быть строго внутри {self.root}") from exc
        return resolved

    def write_text(self, path: Path, content: str) -> None:
        """Safely write UTF-8 text to path. Creates parents if missing."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_binary(self, path: Path, data: bytes) -> None:
        """Safely write binary data to path. Creates parents if missing."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read_text(self, path: Path) -> str:
        if not path.exists():
            raise RuntimeError(f"Файл не найден: {path}")
        if not path.is_file():
            raise RuntimeError(f"Ожидался файл, но получен путь: {path}")
        return path.read_text(encoding="utf-8")

    def has_unsafe_chars(self, name: str) -> bool:
        """Return True if *name* contains characters unsafe for common file systems."""
        return bool(self.UNSAFE_CHARS_REGEX.search(name))

    def sanitize_filename(self, name: str) -> str:
        """Replace characters unsafe for file systems with ``_``."""
        return self.UNSAFE_CHARS_REGEX.sub("_", name)
