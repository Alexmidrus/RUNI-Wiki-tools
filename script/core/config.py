"""Configuration management for environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple


@dataclass
class AppConfigData:
    api_url: str
    username: str
    password: str
    auth_mode: str
    user_agent: str


class AppConfig:
    """Manages loading and resolving variables from .env or current os environment."""

    DEFAULT_USER_AGENT = "RUNI_Wiki Tools OOP/1.0"

    def __init__(self, project_root: Path | None = None) -> None:
        if project_root is None:
            self.root = Path(__file__).resolve().parent.parent.parent
        else:
            self.root = project_root
        
        self.dotenv_found = False
        self.dotenv_loaded_count = 0

    def parse_env_line(self, line: str, line_no: int) -> Optional[Tuple[str, str]]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None

        if stripped.startswith("export "):
            stripped = stripped[len("export "):].strip()

        if "=" not in stripped:
            raise RuntimeError(f"Некорректная строка в .env (line {line_no})")

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise RuntimeError(f"Пустой ключ в .env (line {line_no})")

        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        return key, value

    def autoload_dotenv(self) -> None:
        """Load .env from project root into process env without overriding existing vars."""
        env_path = self.root / ".env"
        if not env_path.exists():
            self.dotenv_found = False
            self.dotenv_loaded_count = 0
            return
            
        if not env_path.is_file():
            raise RuntimeError(f"Ожидался файл .env, но найден другой тип: {env_path}")

        content = env_path.read_text(encoding="utf-8-sig")
        loaded = 0
        for idx, line in enumerate(content.splitlines(), start=1):
            parsed = self.parse_env_line(line, idx)
            if not parsed:
                continue
            key, value = parsed
            if key not in os.environ:
                os.environ[key] = value
                loaded += 1
                
        self.dotenv_found = True
        self.dotenv_loaded_count = loaded

    def read_api_config(self) -> AppConfigData:
        """Resolve and validate minimum variables required for API authenticated sessions."""
        api_url = (
            os.getenv("MW_API_URL", "").strip()
            or os.getenv("MEDIAWIKI_API_URL", "").strip()
        )
        username = (
            os.getenv("MW_USERNAME", "").strip()
            or os.getenv("MEDIAWIKI_USERNAME", "").strip()
        )
        bot_password = os.getenv("MW_BOT_PASSWORD", "") or os.getenv(
            "MEDIAWIKI_BOT_PASSWORD", ""
        )
        user_password = os.getenv("MW_PASSWORD", "") or os.getenv("MEDIAWIKI_PASSWORD", "")
        user_agent = (
            os.getenv("MW_USER_AGENT", "").strip()
            or os.getenv("MEDIAWIKI_USER_AGENT", "").strip()
            or self.DEFAULT_USER_AGENT
        )

        missing = []
        if not api_url:
            missing.append("MW_API_URL|MEDIAWIKI_API_URL")
        if not username:
            missing.append("MW_USERNAME|MEDIAWIKI_USERNAME")
        if not bot_password and not user_password:
            missing.append(
                "MW_BOT_PASSWORD|MW_PASSWORD|MEDIAWIKI_BOT_PASSWORD|MEDIAWIKI_PASSWORD"
            )
        if missing:
            raise RuntimeError(f"Отсутствуют обязательные env переменные: {', '.join(missing)}")

        password = bot_password if bot_password else user_password
        auth_mode = "bot_password" if bot_password else "password"

        return AppConfigData(
            api_url=api_url,
            username=username,
            password=password,
            auth_mode=auth_mode,
            user_agent=user_agent
        )
