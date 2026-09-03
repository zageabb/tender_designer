from __future__ import annotations

import json
import os
import queue
import re
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests

from services.agentic_web_search import (
    Evidence,
    MAX_REDIRECTS,
    MAX_RESPONSE_BYTES,
    SEARCH_HEADERS,
    SearchResult,
    _extract_page_text,
    _safe_public_url,
)


TECHNICAL_SIGNAL_RE = re.compile(
    r"\b(?:model|part\s*(?:number|no\.?|code)|sku|datasheet|data\s*sheet|technical\s+data|"
    r"rated\s+(?:voltage|current|power)|voltage|current|frequency|short[-\s]?circuit|fault\s+level|"
    r"breaking\s+capacity|insulation\s+level|impulse\s+withstand|ip\s*\d{2}|iec\s*\d{3,}|"
    r"en\s*\d{3,}|dimensions?|height|width|depth|weight|busbar|feeder|incomer|transformer|switchgear|"
    r"relay|protection|cable|conductor|cross[-\s]?section|cpu|processor|ram|memory|storage|ssd|ethernet|"
    r"warranty|operating\s+system|ports?)\b",
    re.I,
)

BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
AD_HOST_TOKENS = (
    "doubleclick.",
    "googlesyndication.",
    "google-analytics.",
    "adservice.",
    "adnxs.",
    "facebook.net",
    "hotjar.",
    "scorecardresearch.",
)


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def browser_fallback_enabled() -> bool:
    return _env_bool("TENDER_RESEARCH_BROWSER_FALLBACK", True)


def browser_page_limit() -> int:
    return _env_int("TENDER_RESEARCH_BROWSER_MAX_PAGES", 3, 0, 5)


def browser_timeout_ms() -> int:
    return _env_int("TENDER_RESEARCH_BROWSER_TIMEOUT_MS", 15_000, 5_000, 30_000)


def browser_settle_ms() -> int:
    return _env_int("TENDER_RESEARCH_BROWSER_SETTLE_MS", 1_200, 0, 5_000)


def _decode_html(body: bytes, response: requests.Response) -> str:
    encoding = response.encoding or "utf-8"
    return body.decode(encoding, errors="replace")


def _download_public_resource(url: str, timeout: int) -> tuple[requests.Response, bytes]:
    current_url = url
    session = requests.Session()
    for _ in range(MAX_REDIRECTS + 1):
        if not _safe_public_url(current_url):
            raise requests.RequestException("Blocked non-public URL.")
        response = session.get(
            current_url,
            headers=SEARCH_HEADERS,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise requests.RequestException("Redirect response omitted its destination.")
            current_url = urljoin(current_url, location)
            continue
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                response.close()
                raise requests.RequestException("Web resource exceeded the download size limit.")
            chunks.append(chunk)
        return response, b"".join(chunks)
    raise requests.RequestException("Web resource exceeded the redirect limit.")


def _extract_pdf_text(body: bytes, max_characters: int) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(BytesIO(body))
    except Exception:
        return ""
    sections: list[str] = []
    total = 0
    for page in reader.pages[:80]:
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not text:
            continue
        remaining = max_characters - total
        if remaining <= 0:
            break
        sections.append(text[:remaining])
        total += len(sections[-1])
    return "\n\n".join(sections).strip()


def _json_ld_blocks(html_text: str) -> list[object]:
    blocks: list[object] = []
    for match in re.finditer(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html_text,
        flags=re.I | re.S,
    ):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except Exception:
            continue
    return blocks


def _flatten_product_json(value: object, rows: list[str], depth: int = 0) -> None:
    if depth > 5 or len(rows) >= 80:
        return
    if isinstance(value, list):
        for item in value[:25]:
            _flatten_product_json(item, rows, depth + 1)
        return
    if not isinstance(value, dict):
        return

    item_type = value.get("@type")
    if isinstance(item_type, list):
        type_values = {str(item).lower() for item in item_type}
    else:
        type_values = {str(item_type or "").lower()}
    interesting = bool(type_values & {"product", "individualproduct", "productmodel", "offer"})

    preferred_keys = (
        "name",
        "model",
        "mpn",
        "sku",
        "productID",
        "description",
        "brand",
        "manufacturer",
        "category",
        "material",
        "weight",
        "width",
        "height",
        "depth",
        "additionalProperty",
        "offers",
    )
    if interesting:
        for key in preferred_keys:
            if key not in value:
                continue
            field_value = value[key]
            if isinstance(field_value, (str, int, float, bool)):
                rows.append(f"{key}: {field_value}")
            elif isinstance(field_value, dict):
                if key in {"brand", "manufacturer"}:
                    name = field_value.get("name")
                    if name:
                        rows.append(f"{key}: {name}")
                elif key == "additionalProperty":
                    _flatten_product_json(field_value, rows, depth + 1)
                else:
                    for child_key in ("name", "price", "priceCurrency", "availability", "url", "value"):
                        child = field_value.get(child_key)
                        if isinstance(child, (str, int, float, bool)):
                            rows.append(f"{key}.{child_key}: {child}")
            elif isinstance(field_value, list):
                for child in field_value[:25]:
                    if isinstance(child, dict):
                        name = child.get("name") or child.get("propertyID")
                        child_value = child.get("value")
                        if name and child_value not in (None, ""):
                            rows.append(f"{name}: {child_value}")
                        else:
                            _flatten_product_json(child, rows, depth + 1)

    for child in value.values():
        if isinstance(child, (dict, list)):
            _flatten_product_json(child, rows, depth + 1)


def _structured_product_text(html_text: str) -> str:
    rows: list[str] = []
    for block in _json_ld_blocks(html_text):
        _flatten_product_json(block, rows)
    clean: list[str] = []
    seen: set[str] = set()
    for row in rows:
        compact = " ".join(str(row).split())[:600]
        key = compact.lower()
        if compact and key not in seen:
            seen.add(key)
            clean.append(compact)
    return "\n".join(clean)[:5000]


def _technical_signal_count(text: str) -> int:
    return len({match.group(0).lower() for match in TECHNICAL_SIGNAL_RE.finditer(text or "")})


def _evidence_sufficient(text: str) -> bool:
    compact = " ".join((text or "").split())
    if len(compact) >= 1800 and _technical_signal_count(compact) >= 2:
        return True
    if len(compact) >= 700 and _technical_signal_count(compact) >= 4:
        return True
    return False


class BrowserRenderer:
    """Run one sandboxed Chromium process on a dedicated thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, int, Future]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def render(self, url: str, timeout_ms: int) -> dict:
        self._ensure_worker()
        future: Future = Future()
        self._queue.put((url, timeout_ms, future))
        try:
            return future.result(timeout=(timeout_ms / 1000) + 12)
        except FutureTimeoutError:
            return {"html": "", "url": url, "error": "Headless Chromium rendering exceeded its bounded timeout"}

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="tender-research-browser", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            self._fail_requests(f"Playwright is unavailable: {exc}")
            return
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, chromium_sandbox=True)
                while True:
                    url, timeout_ms, future = self._queue.get()
                    if future.cancelled():
                        continue
                    try:
                        if not browser.is_connected():
                            browser = playwright.chromium.launch(headless=True, chromium_sandbox=True)
                        result = self._render_one(browser, url, timeout_ms)
                    except Exception as exc:
                        result = {"html": "", "url": url, "error": f"Headless Chromium failed: {exc}"}
                    if not future.done():
                        future.set_result(result)
        except Exception as exc:
            self._fail_requests(f"Headless Chromium could not start: {exc}")

    def _fail_requests(self, message: str) -> None:
        while True:
            _url, _timeout_ms, future = self._queue.get()
            if not future.done():
                future.set_result({"html": "", "error": message})

    @staticmethod
    def _render_one(browser, url: str, timeout_ms: int) -> dict:
        if not _safe_public_url(url):
            return {"html": "", "url": url, "error": "Blocked non-public or invalid URL"}
        context = browser.new_context(
            locale="en-GB",
            java_script_enabled=True,
            service_workers="block",
            accept_downloads=False,
        )
        page = context.new_page()

        def route_request(route) -> None:
            request = route.request
            if request.resource_type in BLOCKED_RESOURCE_TYPES:
                route.abort()
                return
            parsed = urlparse(request.url)
            if parsed.scheme in {"data", "blob", "about"}:
                route.continue_()
                return
            host = (parsed.hostname or "").lower()
            if any(token in host for token in AD_HOST_TOKENS):
                route.abort()
                return
            if parsed.scheme not in {"http", "https"} or not _safe_public_url(request.url):
                route.abort()
                return
            route.continue_()

        try:
            context.route("**/*", route_request)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            settle_ms = browser_settle_ms()
            if settle_ms:
                page.wait_for_timeout(settle_ms)
            final_url = page.url
            if not _safe_public_url(final_url):
                return {"html": "", "url": final_url, "error": "Browser redirected to a non-public or invalid URL"}
            return {"html": page.content(), "url": final_url, "error": ""}
        finally:
            context.close()


_RENDERER = BrowserRenderer()


class EnhancedEquipmentPageReader:
    """Evidence reader for equipment research, datasheets and difficult product pages."""

    def __init__(self, timeout: int = 15, max_characters: int = 12000) -> None:
        self.timeout = timeout
        self.max_characters = max_characters
        self._render_lock = threading.Lock()
        self._rendered_pages = 0

    def read(self, result: SearchResult, source_id: int) -> Evidence | None:
        if not _safe_public_url(result.url):
            return None
        try:
            response, body = _download_public_resource(result.url, self.timeout)
        except requests.RequestException:
            return self._snippet_evidence(result, source_id)

        content_type = (response.headers.get("content-type") or "").lower()
        final_url = response.url
        if "pdf" in content_type or final_url.lower().split("?", 1)[0].endswith(".pdf"):
            text = _extract_pdf_text(body, self.max_characters)
            if len(text) >= 80:
                return Evidence(source_id, result.title, final_url, text[: self.max_characters], result.query)
            return self._snippet_evidence(result, source_id)

        if "html" not in content_type and "xhtml" not in content_type:
            return self._snippet_evidence(result, source_id)

        html_text = _decode_html(body, response)
        text = self._extract_html_evidence(html_text, final_url)

        if not _evidence_sufficient(text) and self._reserve_browser_slot():
            rendered = _RENDERER.render(final_url, browser_timeout_ms())
            rendered_html = str(rendered.get("html") or "")
            if rendered_html:
                rendered_url = str(rendered.get("url") or final_url)
                rendered_text = self._extract_html_evidence(rendered_html, rendered_url)
                if len(rendered_text) > len(text):
                    text = rendered_text
                    final_url = rendered_url

        compact = "\n".join(line.rstrip() for line in text.splitlines() if line.strip()).strip()
        if len(compact) < 80:
            return self._snippet_evidence(result, source_id)
        return Evidence(source_id, result.title, final_url, compact[: self.max_characters], result.query)

    def _extract_html_evidence(self, html_text: str, url: str) -> str:
        visible = _extract_page_text(html_text, url)
        structured = _structured_product_text(html_text)
        sections: list[str] = []
        if visible:
            sections.append(visible)
        if structured:
            sections.extend(["Structured product metadata:", structured])
        return "\n\n".join(sections)

    def _reserve_browser_slot(self) -> bool:
        if not browser_fallback_enabled():
            return False
        limit = browser_page_limit()
        if limit <= 0:
            return False
        with self._render_lock:
            if self._rendered_pages >= limit:
                return False
            self._rendered_pages += 1
            return True

    @staticmethod
    def _snippet_evidence(result: SearchResult, source_id: int) -> Evidence | None:
        snippet = " ".join((result.snippet or "").split())
        if not snippet:
            return None
        return Evidence(source_id, result.title, result.url, snippet, result.query)


def install_enhanced_equipment_reader() -> None:
    """Install the enhanced reader into the existing Finder service without changing its public API."""
    import services.computer_finder_service as finder_service

    finder_service.WebPageReader = EnhancedEquipmentPageReader
