"""API Client for interacting with MediaWiki."""

from __future__ import annotations

import json
import re
import ssl
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, TypeVar
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

import requests

from .config import AppConfigData
from .ui import ConsoleUI

T = TypeVar("T")

class MediaWikiClient:
    """Encapsulates MediaWiki API operations, including fetching, editing, and SSL handling."""

    REQUEST_TIMEOUT_SECONDS = 30

    def __init__(self, ui: ConsoleUI, config: Optional[AppConfigData] = None, insecure: bool = False) -> None:
        self.ui = ui
        self.insecure = insecure
        self._ssl_context = self.make_ssl_context(insecure)
        self.user_agent = config.user_agent if config else "RUNI_Wiki/1.0"
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent})
        self._config = config

        self._api_endpoint: Optional[str] = config.api_url if config else None

    # ---------------------------------------------------------------------------
    # SSL and Fallback Handling
    # ---------------------------------------------------------------------------
    @staticmethod
    def create_insecure_ssl_context() -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    @classmethod
    def make_ssl_context(cls, insecure: bool) -> Optional[ssl.SSLContext]:
        return cls.create_insecure_ssl_context() if insecure else None

    @staticmethod
    def is_ssl_verify_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "certificate_verify_failed" in text
            or "ssl: certificate verify failed" in text
            or "unable to get local issuer certificate" in text
            or "sslerror" in text
        )

    def run_with_ssl_fallback(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Run *func* once. Retry with an insecure context if it fails with an SSL-verify error."""
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if self.insecure or not self.is_ssl_verify_error(exc):
                raise
            self.ui.error("SSL-сертификат не прошел проверку. Повторяем запрос в insecure-режиме.")
            self._ssl_context = self.create_insecure_ssl_context()
            self._session.verify = False 
            if "ssl_context" in func.__code__.co_varnames:
                kwargs["ssl_context"] = self._ssl_context
            return func(*args, **kwargs)

    # ---------------------------------------------------------------------------
    # HTTP requests wrapper (urllib based for simpler reading)
    # ---------------------------------------------------------------------------
    def fetch_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urlopen(request, timeout=self.REQUEST_TIMEOUT_SECONDS, context=self._ssl_context) as response:
            return response.read().decode("utf-8", errors="replace")

    def fetch_binary(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.REQUEST_TIMEOUT_SECONDS, context=self._ssl_context) as response:
            return response.read()

    def fetch_json(self, endpoint: str, params: Dict[str, str]) -> Dict:
        url = f"{endpoint}?{urlencode(params)}"
        request = Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "application/json,text/plain,*/*"},
        )
        with urlopen(request, timeout=self.REQUEST_TIMEOUT_SECONDS, context=self._ssl_context) as response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            snippet = raw[:280].replace("\n", " ").strip()
            raise RuntimeError(f"Ответ API не JSON: {snippet}") from exc

    # ---------------------------------------------------------------------------
    # Requests wrapper (for auth and edits)
    # ---------------------------------------------------------------------------
    def _mw_get(self, api_url: str, params: Dict[str, str]) -> Dict:
        query = dict(params)
        query["format"] = "json"
        response = self._session.get(
            api_url, params=query, timeout=self.REQUEST_TIMEOUT_SECONDS,
            verify=not self.insecure and self._session.verify is not False
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(self._extract_api_error(payload))
        return payload

    def _mw_post(self, api_url: str, data: Dict[str, str]) -> Dict:
        body = dict(data)
        body["format"] = "json"
        response = self._session.post(
            api_url, data=body, timeout=self.REQUEST_TIMEOUT_SECONDS,
            verify=not self.insecure and self._session.verify is not False
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(self._extract_api_error(payload))
        return payload

    def _extract_api_error(self, payload: Dict) -> str:
        error = payload.get("error")
        if not isinstance(error, dict):
            return "Неизвестная ошибка API"
        code = str(error.get("code", "unknown"))
        info = str(error.get("info", "no info"))
        return f"{code}: {info}"

    def close(self) -> None:
        self._session.close()

    # ---------------------------------------------------------------------------
    # Discovery functions
    # ---------------------------------------------------------------------------
    @staticmethod
    def normalize_base_url(base_url: str) -> str:
        return base_url.rstrip("/")

    def _discover_api_candidates(self, base_url: str) -> List[str]:
        candidates: List[str] = []
        homepage_url = f"{self.normalize_base_url(base_url)}/"
        html = self.fetch_text(homepage_url)

        matches = re.findall(r'''['"]([^'"]*api\.php[^'"]*)['"]''', html, flags=re.IGNORECASE)
        for value in matches:
            absolute = urljoin(homepage_url, value)
            parsed = urlparse(absolute)
            path = parsed.path
            if not path.endswith("api.php"):
                api_idx = path.lower().find("api.php")
                if api_idx != -1:
                    path = path[: api_idx + len("api.php")]
            if not path.lower().endswith("api.php"):
                continue
            endpoint = f"{parsed.scheme}://{parsed.netloc}{path}"
            candidates.append(endpoint)
        return candidates

    def detect_api_endpoint(self, base_url: str) -> str:
        if self._api_endpoint:
            return self._api_endpoint

        base = self.normalize_base_url(base_url)
        candidates = [
            f"{base}/api.php",
            f"{base}/w/api.php",
            f"{base}/wiki/api.php",
            f"{base}/mediawiki/api.php",
        ]
        try:
            discovered = self._discover_api_candidates(base)
            for endpoint in discovered:
                if endpoint not in candidates:
                    candidates.append(endpoint)
        except Exception:
            pass

        errors: Dict[str, str] = {}
        for endpoint in candidates:
            try:
                data = self.fetch_json(
                    endpoint,
                    {"action": "query", "meta": "siteinfo", "siprop": "general", "format": "json"}
                )
                if "query" in data and "general" in data["query"]:
                    self._api_endpoint = endpoint
                    return endpoint
                errors[endpoint] = f"неожиданный JSON: ключи {list(data.keys())[:8]}"
            except Exception as exc:
                errors[endpoint] = str(exc)

        details = "; ".join([f"{k} -> {v}" for k, v in errors.items()]) or "нет деталей"
        raise RuntimeError(
            "Не удалось определить API endpoint. Проверены: "
            + ", ".join(candidates)
            + f". Детали: {details}"
        )

    def get_api_endpoint(self) -> str:
        if not self._api_endpoint:
            raise RuntimeError("API endpoint не установлен (запустите detect_api_endpoint)")
        return self._api_endpoint

    # ---------------------------------------------------------------------------
    # Data structure fetchers
    # ---------------------------------------------------------------------------
    def get_siteinfo(self) -> Tuple[Dict, Dict]:
        data = self.fetch_json(
            self.get_api_endpoint(),
            {
                "action": "query",
                "meta": "siteinfo",
                "siprop": "general|namespaces|namespacealiases",
                "format": "json",
            }
        )
        query = data.get("query", {})
        general = query.get("general", {})
        if not general:
            raise RuntimeError("API вернул неполный siteinfo: отсутствует блок general")
        return general, query

    def iter_allpages(self, namespace: int) -> Iterable[str]:
        apcontinue: Optional[str] = None
        while True:
            params: Dict[str, str] = {
                "action": "query",
                "list": "allpages",
                "apnamespace": str(namespace),
                "aplimit": "max",
                "format": "json",
            }
            if apcontinue:
                params["apcontinue"] = apcontinue

            data = self.fetch_json(self.get_api_endpoint(), params)
            allpages = data.get("query", {}).get("allpages", [])

            for page in allpages:
                title = page.get("title")
                if title:
                    yield title

            cont = data.get("continue", {})
            apcontinue = cont.get("apcontinue")
            if not apcontinue:
                break

    def fetch_titles_content(self, titles: List[str]) -> Dict[str, Optional[str]]:
        data = self.fetch_json(
            self.get_api_endpoint(),
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "titles": "|".join(titles),
                "format": "json",
                "formatversion": "2",
            }
        )
        pages = data.get("query", {}).get("pages", [])
        result: Dict[str, Optional[str]] = {}
        for page in pages:
            title = page.get("title")
            if not title:
                continue
            if page.get("missing"):
                result[title] = None
                continue
            result[title] = self.extract_revision_content(page)
        return result

    @staticmethod
    def extract_revision_content(page: Dict) -> Optional[str]:
        revisions = page.get("revisions", [])
        if not revisions:
            return None

        rev = revisions[0]
        slots = rev.get("slots", {})
        main_slot = slots.get("main", {})

        content = main_slot.get("content")
        if content is not None:
            return content

        if "*" in main_slot:
            return main_slot.get("*")
        if "*" in rev:
            return rev.get("*")
        return None

    def fetch_page_images(self, title: str) -> List[str]:
        images: List[str] = []
        imcontinue: Optional[str] = None
        while True:
            params: Dict[str, str] = {
                "action": "query",
                "prop": "images",
                "titles": title,
                "imlimit": "max",
                "format": "json",
            }
            if imcontinue:
                params["imcontinue"] = imcontinue

            data = self.fetch_json(self.get_api_endpoint(), params)
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                for img in page.get("images", []):
                    img_title = img.get("title")
                    if img_title:
                        images.append(img_title)

            cont = data.get("continue", {})
            imcontinue = cont.get("imcontinue")
            if not imcontinue:
                break
        return images

    def fetch_image_urls(self, file_titles: List[str]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        batch_size = 50
        for i in range(0, len(file_titles), batch_size):
            batch = file_titles[i : i + batch_size]
            data = self.fetch_json(
                self.get_api_endpoint(),
                {
                    "action": "query",
                    "prop": "imageinfo",
                    "iiprop": "url",
                    "titles": "|".join(batch),
                    "format": "json",
                }
            )
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                title = page.get("title")
                imageinfo = page.get("imageinfo", [])
                if title and imageinfo:
                    url = imageinfo[0].get("url")
                    if url:
                        result[title] = url
        return result

    # ---------------------------------------------------------------------------
    # Authentication & Pushing Logic
    # ---------------------------------------------------------------------------
    def login(self) -> None:
        if not self._config:
            raise RuntimeError("AppConfigData is missing. Cannot perform login.")
        
        def _do_login():
            token = self._mw_get_login_token()
            try:
                self._mw_login_action(token)
                return
            except RuntimeError as login_error:
                login_error_text = str(login_error)

            token = self._mw_get_login_token()
            try:
                self._mw_clientlogin_action(token)
                return
            except RuntimeError as clientlogin_error:
                raise RuntimeError(
                    f"Не удалось авторизоваться. login: {login_error_text}; clientlogin: {clientlogin_error}"
                ) from clientlogin_error
                
        self.run_with_ssl_fallback(_do_login)

    def _mw_get_login_token(self) -> str:
        payload = self._mw_get(
            self.get_api_endpoint(),
            {"action": "query", "meta": "tokens", "type": "login"}
        )
        token = payload.get("query", {}).get("tokens", {}).get("logintoken", "")
        if not token:
            raise RuntimeError("Не удалось получить login token")
        return token

    def _mw_login_action(self, token: str) -> None:
        payload = self._mw_post(
            self.get_api_endpoint(),
            {
                "action": "login",
                "lgname": self._config.username,
                "lgpassword": self._config.password,
                "lgtoken": token,
            }
        )
        login = payload.get("login", {})
        result = str(login.get("result", ""))
        if result == "Success":
            return
        reason = str(login.get("reason", "")).strip()
        raise RuntimeError(f"login failed: {result}{f' ({reason})' if reason else ''}")

    def _mw_clientlogin_action(self, token: str) -> None:
        payload = self._mw_post(
            self.get_api_endpoint(),
            {
                "action": "clientlogin",
                "username": self._config.username,
                "password": self._config.password,
                "logintoken": token,
                "loginreturnurl": "https://localhost/",
            }
        )
        result = payload.get("clientlogin", {})
        status = str(result.get("status", ""))
        if status == "PASS":
            return
        message = str(result.get("message", "")).strip()
        message_code = str(result.get("messagecode", "")).strip()
        details = message or message_code or "unknown"
        raise RuntimeError(f"clientlogin failed: {status} ({details})")

    def get_csrf_token(self) -> str:
        def _get_token():
            payload = self._mw_get(
                self.get_api_endpoint(),
                {"action": "query", "meta": "tokens", "type": "csrf"}
            )
            token = payload.get("query", {}).get("tokens", {}).get("csrftoken", "")
            if not token:
                raise RuntimeError("Не удалось получить CSRF token")
            return token
            
        return self.run_with_ssl_fallback(_get_token)

    def get_page_state(self, title: str) -> Tuple[str, Optional[str], Optional[str]]:
        def _get_state():
            payload = self._mw_get(
                self.get_api_endpoint(),
                {
                    "action": "query",
                    "prop": "revisions",
                    "rvprop": "content|timestamp",
                    "rvslots": "main",
                    "titles": title,
                    "formatversion": "2",
                    "curtimestamp": "1",
                }
            )
            page_list = payload.get("query", {}).get("pages", [])
            if not page_list:
                return "", None, payload.get("curtimestamp")
            
            page = page_list[0]
            if page.get("missing"):
                return "", None, payload.get("curtimestamp")

            revisions = page.get("revisions", [])
            text = ""
            basetimestamp = None
            if revisions:
                rev = revisions[0]
                basetimestamp = rev.get("timestamp")
                slots = rev.get("slots", {})
                main_slot = slots.get("main", {})
                if isinstance(main_slot, dict) and "content" in main_slot:
                    text = str(main_slot.get("content") or "")
                elif isinstance(main_slot, dict) and "*" in main_slot:
                    text = str(main_slot.get("*") or "")
                elif "*" in rev:
                    text = str(rev.get("*") or "")
            return text, basetimestamp, payload.get("curtimestamp")
            
        return self.run_with_ssl_fallback(_get_state)

    def edit_page(
        self,
        title: str,
        text: str,
        summary: str,
        csrf_token: str,
        minor: bool = False,
        bot: bool = False,
        basetimestamp: Optional[str] = None,
        starttimestamp: Optional[str] = None,
    ) -> Dict:
        def _edit():
            data: Dict[str, str] = {
                "action": "edit",
                "title": title,
                "text": text,
                "token": csrf_token,
                "summary": summary,
            }
            if minor:
                data["minor"] = "1"
            if bot:
                data["bot"] = "1"
            if basetimestamp:
                data["basetimestamp"] = basetimestamp
            if starttimestamp:
                data["starttimestamp"] = starttimestamp

            payload = self._mw_post(self.get_api_endpoint(), data)
            edit = payload.get("edit")
            if not isinstance(edit, dict):
                raise RuntimeError("Неожиданный ответ API: отсутствует блок edit")
            result = str(edit.get("result", ""))
            if result != "Success":
                details = self._extract_edit_failure_details(edit)
                if details:
                    raise RuntimeError(f"Редактирование не выполнено: {result}; {details}")
                raise RuntimeError(f"Редактирование не выполнено: {result}")
            return edit
            
        return self.run_with_ssl_fallback(_edit)

    def _extract_edit_failure_details(self, edit: Dict) -> str:
        details = []
        code = str(edit.get("code", "")).strip()
        info = str(edit.get("info", "")).strip()
        if code:
            details.append(f"code={code}")
        if info:
            details.append(f"info={info}")

        known_keys = {
            "result", "code", "info", "newrevid", "newtimestamp",
            "oldrevid", "pageid", "title", "watched", "nochange", "contentmodel",
        }
        for key in sorted(edit.keys()):
            if key in known_keys:
                continue
            value = edit.get(key)
            if value in (None, "", False):
                continue
            details.append(f"{key}={self._format_api_value(value)}")
        return "; ".join(details)

    @staticmethod
    def _format_api_value(value: object) -> str:
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    def get_user_rights(self) -> Set[str]:
        def _get_rights():
            payload = self._mw_get(
                self.get_api_endpoint(),
                {"action": "query", "meta": "userinfo", "uiprop": "rights"}
            )
            rights = payload.get("query", {}).get("userinfo", {}).get("rights", [])
            if not isinstance(rights, list):
                return set()
            return {str(item).strip() for item in rights if str(item).strip()}
        return self.run_with_ssl_fallback(_get_rights)

    def get_flagged_status(self, title: str, new_revid: Optional[int]) -> str:
        def _parse_int(value: object) -> Optional[int]:
            try:
                if value is None:
                    return None
                return int(str(value))
            except (TypeError, ValueError):
                return None
                
        def _get_status():
            payload = self._mw_get(
                self.get_api_endpoint(),
                {
                    "action": "query",
                    "prop": "flagged",
                    "titles": title,
                    "formatversion": "2",
                }
            )
            pages = payload.get("query", {}).get("pages", [])
            if not pages:
                return "unknown"
            flagged = pages[0].get("flagged")
            if not isinstance(flagged, dict):
                return "unknown"
            stable_revid = _parse_int(flagged.get("stable_revid"))
            pending_since = str(flagged.get("pending_since") or "").strip()
            if pending_since:
                return "pending"
            if stable_revid is not None and new_revid is not None:
                return "stable" if stable_revid == new_revid else "pending"
            return "unknown"
            
        return self.run_with_ssl_fallback(_get_status)

    def try_review_revision(self, csrf_token: str, revid: int, comment: str) -> None:
        def _review():
            self._mw_post(
                self.get_api_endpoint(),
                {
                    "action": "review",
                    "revid": str(revid),
                    "token": csrf_token,
                    "comment": comment,
                }
            )
        self.run_with_ssl_fallback(_review)

