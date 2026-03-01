"""Shared helpers for MediaWiki API access, HTTP fetching, and SSL fallback."""

from __future__ import annotations

import json
import re
import ssl
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, TypeVar
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# SSL helpers
# ---------------------------------------------------------------------------

def create_insecure_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def make_ssl_context(insecure: bool) -> Optional[ssl.SSLContext]:
    return create_insecure_ssl_context() if insecure else None


def is_ssl_verify_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "certificate_verify_failed" in text
        or "ssl: certificate verify failed" in text
        or "unable to get local issuer certificate" in text
    )


def run_with_ssl_fallback(
    func: Callable[..., T],
    args: tuple = (),
    kwargs: Optional[Dict[str, Any]] = None,
    insecure: bool = False,
) -> T:
    """Run *func* once.  If it fails with an SSL-verify error and *insecure*
    is ``False``, retry with an insecure SSL context passed as *ssl_context*
    keyword argument.  Re-raises any other exception."""
    if kwargs is None:
        kwargs = {}
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        if insecure or not is_ssl_verify_error(exc):
            raise
        print(
            "Предупреждение: SSL-сертификат не прошел проверку. "
            "Повторяем запрос в insecure-режиме.",
            file=sys.stderr,
        )
        kwargs["ssl_context"] = create_insecure_ssl_context()
        return func(*args, **kwargs)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_text(url: str, ssl_context: Optional[ssl.SSLContext] = None) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=ssl_context) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_json(
    endpoint: str,
    params: Dict[str, str],
    ssl_context: Optional[ssl.SSLContext] = None,
) -> Dict:
    url = f"{endpoint}?{urlencode(params)}"
    request = Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json,text/plain,*/*"},
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=ssl_context) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        snippet = raw[:280].replace("\n", " ").strip()
        raise RuntimeError(f"Ответ API не JSON: {snippet}") from exc


# ---------------------------------------------------------------------------
# URL / API-endpoint helpers
# ---------------------------------------------------------------------------

def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def discover_api_candidates(
    base_url: str, ssl_context: Optional[ssl.SSLContext] = None
) -> List[str]:
    candidates: List[str] = []
    homepage_url = f"{normalize_base_url(base_url)}/"
    html = fetch_text(homepage_url, ssl_context=ssl_context)

    matches = re.findall(r"""['"]([^'"]*api\.php[^'"]*)['"]""", html, flags=re.IGNORECASE)
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


def detect_api_endpoint(
    base_url: str, ssl_context: Optional[ssl.SSLContext] = None
) -> str:
    base = normalize_base_url(base_url)
    candidates = [
        f"{base}/api.php",
        f"{base}/w/api.php",
        f"{base}/wiki/api.php",
        f"{base}/mediawiki/api.php",
    ]
    try:
        discovered = discover_api_candidates(base, ssl_context=ssl_context)
        for endpoint in discovered:
            if endpoint not in candidates:
                candidates.append(endpoint)
    except Exception:
        pass

    errors: Dict[str, str] = {}
    for endpoint in candidates:
        try:
            data = fetch_json(
                endpoint,
                {"action": "query", "meta": "siteinfo", "siprop": "general", "format": "json"},
                ssl_context=ssl_context,
            )
            if "query" in data and "general" in data["query"]:
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


# ---------------------------------------------------------------------------
# Page iteration
# ---------------------------------------------------------------------------

def iter_allpages(
    api_endpoint: str,
    namespace: int,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> Iterable[str]:
    """Yield all page titles from *namespace* via the allpages API."""
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

        data = fetch_json(api_endpoint, params, ssl_context=ssl_context)
        allpages = data.get("query", {}).get("allpages", [])

        for page in allpages:
            title = page.get("title")
            if title:
                yield title

        cont = data.get("continue", {})
        apcontinue = cont.get("apcontinue")
        if not apcontinue:
            break


# ---------------------------------------------------------------------------
# Content retrieval
# ---------------------------------------------------------------------------

def extract_revision_content(page: Dict) -> Optional[str]:
    """Extract wikitext content from a page object returned by the API."""
    revisions = page.get("revisions", [])
    if not revisions:
        return None

    rev = revisions[0]
    slots = rev.get("slots", {})
    main_slot = slots.get("main", {})

    content = main_slot.get("content")
    if content is not None:
        return content

    # Legacy MediaWiki formats fallback.
    if "*" in main_slot:
        return main_slot.get("*")
    if "*" in rev:
        return rev.get("*")
    return None


def fetch_titles_content(
    api_endpoint: str,
    titles: List[str],
    ssl_context: Optional[ssl.SSLContext] = None,
) -> Dict[str, Optional[str]]:
    """Fetch wikitext content for a list of page titles."""
    data = fetch_json(
        api_endpoint,
        {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": "|".join(titles),
            "format": "json",
            "formatversion": "2",
        },
        ssl_context=ssl_context,
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
        result[title] = extract_revision_content(page)
    return result


# ---------------------------------------------------------------------------
# Binary download
# ---------------------------------------------------------------------------

def fetch_binary(url: str, ssl_context: Optional[ssl.SSLContext] = None) -> bytes:
    """Download a binary resource (e.g. image) and return raw bytes."""
    request = Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=ssl_context) as response:
        return response.read()


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def fetch_page_images(
    api_endpoint: str,
    title: str,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> List[str]:
    """Return all image (File:) titles used on *title* via prop=images with pagination."""
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

        data = fetch_json(api_endpoint, params, ssl_context=ssl_context)
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


def fetch_image_urls(
    api_endpoint: str,
    file_titles: List[str],
    ssl_context: Optional[ssl.SSLContext] = None,
) -> Dict[str, str]:
    """Return {file_title: download_url} for the given File: titles (batched by 50)."""
    result: Dict[str, str] = {}
    batch_size = 50

    for i in range(0, len(file_titles), batch_size):
        batch = file_titles[i : i + batch_size]
        data = fetch_json(
            api_endpoint,
            {
                "action": "query",
                "prop": "imageinfo",
                "iiprop": "url",
                "titles": "|".join(batch),
                "format": "json",
            },
            ssl_context=ssl_context,
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
# Filename helpers
# ---------------------------------------------------------------------------

_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')


def has_unsafe_chars(name: str) -> bool:
    """Return True if *name* contains characters unsafe for common file systems."""
    return bool(_UNSAFE_CHARS.search(name))


def sanitize_filename(name: str) -> str:
    """Replace characters unsafe for file systems with ``_``."""
    return _UNSAFE_CHARS.sub("_", name)
