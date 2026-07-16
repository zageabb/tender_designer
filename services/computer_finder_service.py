from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qs, unquote, urlparse

import requests

from services.ollama_client import OllamaClient
from services.prompt_service import render_prompt
from services.settings_service import get_setting, get_task_model


DUCKDUCKGO_HTML_URL = "https://duckduckgo.com/html/"
REQUEST_HEADERS = {
    "User-Agent": "TenderDesignerComputerFinder/1.0 (+local procurement research)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class ComputerFinderConfigError(ValueError):
    def __init__(self, message: str, steps: list[str] | None = None) -> None:
        super().__init__(message)
        self.steps = steps or []


@dataclass(frozen=True)
class ComputerFinderConfig:
    ollama_url: str
    model: str
    searxng_url: str
    search_results_per_domain: int
    max_pages_to_read: int
    allowed_domains: list[str]
    blocked_domains: list[str]
    country: str
    region: str
    city: str


def parse_domain_list(value: str | None) -> list[str]:
    domains: list[str] = []
    seen: set[str] = set()
    for raw_entry in (value or "").replace(",", "\n").splitlines():
        entry = raw_entry.strip().lower()
        if not entry or entry.startswith("#"):
            continue
        if "://" not in entry:
            entry = f"https://{entry}"
        parsed = urlparse(entry)
        domain = parsed.netloc or parsed.path
        domain = domain.split("/")[0].strip().strip(".")
        if not domain:
            continue
        if domain.startswith("www."):
            domain = domain[4:]
        if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain):
            continue
        if domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def get_computer_finder_config() -> ComputerFinderConfig:
    allowed_domains = parse_domain_list(get_setting("computer_finder_allowed_domains"))
    if not allowed_domains:
        raise ComputerFinderConfigError("Add at least one searchable website domain for the computer finder.")

    ollama_url = get_setting("ollama_url")
    if not ollama_url:
        raise ComputerFinderConfigError("Set the Ollama URL before running a computer search.")

    return ComputerFinderConfig(
        ollama_url=ollama_url,
        model=(get_setting("computer_finder_model") or get_task_model("chat_answering") or "llama3.2").strip(),
        searxng_url=(get_setting("computer_finder_searxng_url") or "").strip().rstrip("/"),
        search_results_per_domain=_int_setting("computer_finder_results_per_domain", 3, minimum=1, maximum=8),
        max_pages_to_read=_int_setting("computer_finder_max_pages_to_read", 8, minimum=1, maximum=20),
        allowed_domains=allowed_domains,
        blocked_domains=parse_domain_list(get_setting("computer_finder_blocked_domains")),
        country=(get_setting("computer_finder_market_country") or "").strip().upper(),
        region=(get_setting("computer_finder_market_region") or "").strip(),
        city=(get_setting("computer_finder_market_city") or "").strip(),
    )


def find_computer_for_spec(computer_spec: str, config: ComputerFinderConfig | None = None) -> dict:
    if not computer_spec.strip():
        raise ComputerFinderConfigError("Enter a computer specification before searching.")

    config = config or get_computer_finder_config()
    client = OllamaClient(config.ollama_url)
    planned_queries, planning_steps = _plan_queries(client, config.model, computer_spec, config)
    search_results, search_steps = _collect_search_results(planned_queries, config)
    page_context, page_steps = _build_page_context(search_results, config)
    if not page_context:
        raise ComputerFinderConfigError(
            "SearXNG is connected, but it returned no readable product results from the configured websites. "
            "Check the search diagnostics below; the likely cause is blocked or rate-limited upstream search engines.",
            [*planning_steps, *search_steps, *page_steps],
        )

    prompt = build_computer_finder_prompt(computer_spec, page_context, config)
    answer = client.generate_text(config.model, prompt)
    if not answer:
        raise ComputerFinderConfigError("The Ollama model returned an empty answer.")
    sources = _sources_from_page_context(search_results)
    return {
        "answer": answer,
        "sources": sources,
        "steps": [
            f"Ollama model: {config.model}",
            *planning_steps,
            *search_steps,
            *page_steps,
            f"Generated final recommendation from {len(sources)} sourced result(s).",
        ],
    }


def build_computer_finder_prompt(computer_spec: str, search_results_context: str, config: ComputerFinderConfig) -> str:
    market_parts = [part for part in [config.city, config.region, config.country] if part]
    market_context = ", ".join(market_parts) if market_parts else "No market location configured"
    return render_prompt(
        "computer_finder_search",
        current_date=date.today().isoformat(),
        market_context=market_context,
        allowed_domains="\n".join(f"- {domain}" for domain in config.allowed_domains),
        blocked_domains="\n".join(f"- {domain}" for domain in config.blocked_domains) or "- None",
        computer_spec=computer_spec.strip(),
        search_results=search_results_context,
    )


def _int_setting(key: str, fallback: int, minimum: int, maximum: int) -> int:
    raw_value = get_setting(key, str(fallback))
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError):
        value = fallback
    return max(minimum, min(maximum, value))


def _plan_queries(client: OllamaClient, model_name: str, computer_spec: str, config: ComputerFinderConfig) -> tuple[list[str], list[str]]:
    prompt = render_prompt(
        "computer_finder_query_planning",
        computer_spec=computer_spec.strip(),
        allowed_domains="\n".join(f"- {domain}" for domain in config.allowed_domains),
        market_context=", ".join(part for part in [config.city, config.region, config.country] if part) or "No market location configured",
    )
    try:
        parsed, raw_response, error = client.generate_json(model_name, prompt)
    except Exception as exc:
        return _fallback_queries(computer_spec), [f"Query planning used fallback rules because Ollama planning failed: {exc}"]
    if parsed is None or error is not None:
        return _fallback_queries(computer_spec), [f"Query planning used fallback rules because the model returned invalid JSON: {error or raw_response}"]
    queries = []
    for query in parsed.get("queries", []):
        cleaned = " ".join(str(query).split())
        if cleaned and cleaned not in queries:
            queries.append(cleaned)
    if not queries:
        return _fallback_queries(computer_spec), ["Query planning used fallback rules because no usable queries were returned."]
    return queries[:4], [f"Planned {min(len(queries), 4)} search query path(s) with Ollama."]


def _fallback_queries(computer_spec: str) -> list[str]:
    terms = re.sub(r"[^a-zA-Z0-9+.# -]", " ", computer_spec)
    terms = " ".join(terms.split())
    if len(terms) > 120:
        terms = terms[:120].rsplit(" ", 1)[0]
    return [
        f"{terms} business laptop datasheet",
        "15.6 business laptop 16GB 512GB RJ45 Windows 11 Pro 3 year warranty",
        "i5 Ryzen 5 15.6 laptop 16GB 512GB RJ45 Windows 11 Pro",
    ]


def _collect_search_results(queries: list[str], config: ComputerFinderConfig) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    seen_urls: set[str] = set()
    steps: list[str] = []
    if config.searxng_url:
        searxng_results, searxng_steps = _collect_searxng_results(queries, config, seen_urls)
        results.extend(searxng_results)
        steps.extend(searxng_steps)
        return results, [*steps, "Public search-engine fallback skipped because SearXNG is configured."]

    failed_searches = 0
    for domain in config.allowed_domains:
        domain_results = 0
        for query in queries:
            if domain_results >= config.search_results_per_domain:
                break
            site_query = f"site:{domain} {query}"
            try:
                query_results = _duckduckgo_search(site_query)
            except Exception:
                failed_searches += 1
                continue
            for result in query_results:
                url = _normalise_search_url(result.get("url") or "")
                if not url or url in seen_urls:
                    continue
                if not _domain_allowed(url, config.allowed_domains, config.blocked_domains):
                    continue
                seen_urls.add(url)
                domain_results += 1
                results.append(
                    {
                        "title": result.get("title") or urlparse(url).netloc,
                        "url": url,
                        "snippet": result.get("snippet") or "",
                        "provider": "DuckDuckGo HTML",
                    }
                )
                if domain_results >= config.search_results_per_domain:
                    break
    return results, [
        *steps,
        f"DuckDuckGo fallback searched {len(config.allowed_domains)} configured website domain(s) with site-restricted web queries.",
        f"Collected {len(results)} candidate result(s).",
        f"Search requests skipped after errors: {failed_searches}." if failed_searches else "All search requests completed without transport errors.",
    ]


def _collect_searxng_results(
    queries: list[str],
    config: ComputerFinderConfig,
    seen_urls: set[str],
) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    attempted_queries: list[str] = []
    unresponsive: dict[str, set[str]] = {}
    errors: list[str] = []
    max_results = max(config.max_pages_to_read * 2, 12)

    search_queries = _searxng_query_candidates(queries, config)[:8]
    for query in search_queries:
        if len(results) >= max_results:
            break
        attempted_queries.append(query)
        try:
            payload = _searxng_search(query, config)
        except Exception as exc:
            errors.append(f"{query}: {exc}")
            continue
        for engine, reason in payload.get("unresponsive_engines") or []:
            engine_name = str(engine or "unknown")
            reason_text = str(reason or "unresponsive")
            unresponsive.setdefault(engine_name, set()).add(reason_text)
        for result in payload.get("results") or []:
            url = _normalise_search_url(result.get("url") or "")
            if not url or url in seen_urls:
                continue
            if not _domain_allowed(url, config.allowed_domains, config.blocked_domains):
                continue
            seen_urls.add(url)
            results.append(
                {
                    "title": result.get("title") or urlparse(url).netloc,
                    "url": url,
                    "snippet": result.get("content") or result.get("snippet") or "",
                    "provider": "SearXNG",
                    "engine": result.get("engine") or "",
                }
            )
            if len(results) >= max_results:
                break

    steps = [
        f"SearXNG provider: {config.searxng_url}",
        f"SearXNG query attempts: {len(attempted_queries)}.",
        f"SearXNG collected {len(results)} allowed candidate result(s).",
    ]
    if attempted_queries:
        steps.append("SearXNG tried: " + " | ".join(attempted_queries[:6]) + (" | ..." if len(attempted_queries) > 6 else ""))
    if unresponsive:
        summaries = []
        for engine, reasons in sorted(unresponsive.items()):
            summaries.append(f"{engine} ({', '.join(sorted(reasons))})")
        steps.append("SearXNG unresponsive engines: " + "; ".join(summaries[:8]) + ("; ..." if len(summaries) > 8 else ""))
    if errors:
        steps.append("SearXNG request errors: " + " | ".join(errors[:3]) + (" | ..." if len(errors) > 3 else ""))
    return results, steps


def _searxng_query_candidates(queries: list[str], config: ComputerFinderConfig) -> list[str]:
    candidates: list[str] = []

    def add(query: str) -> None:
        cleaned = " ".join(query.split())
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    for query in queries[:3]:
        add(query)
    for domain in config.allowed_domains[:8]:
        for query in queries[:2]:
            add(f"site:{domain} {query}")
    return candidates


def _searxng_search(query: str, config: ComputerFinderConfig) -> dict:
    response = requests.get(
        f"{config.searxng_url}/search",
        params={
            "q": query,
            "format": "json",
            "safesearch": "0",
            "language": "all",
        },
        headers={
            **REQUEST_HEADERS,
            "Accept": "application/json",
        },
        timeout=12,
    )
    response.raise_for_status()
    return response.json()


def _duckduckgo_search(query: str) -> list[dict]:
    response = requests.get(
        DUCKDUCKGO_HTML_URL,
        params={"q": query},
        headers=REQUEST_HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    body = response.text
    blocks = re.split(r'<div[^>]+class="[^"]*result[^"]*"[^>]*>', body)
    results: list[dict] = []
    for block in blocks:
        link_match = re.search(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.S)
        if not link_match:
            continue
        snippet_match = re.search(r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>|<div[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</div>', block, flags=re.S)
        snippet_html = ""
        if snippet_match:
            snippet_html = snippet_match.group(1) or snippet_match.group(2) or ""
        results.append(
            {
                "title": _clean_html(link_match.group(2)),
                "url": html.unescape(link_match.group(1)),
                "snippet": _clean_html(snippet_html),
            }
        )
    return results[:10]


def _normalise_search_url(url: str) -> str:
    if not url:
        return ""
    url = html.unescape(url.strip())
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        if uddg:
            url = unquote(uddg)
    return url


def _domain_allowed(url: str, allowed_domains: list[str], blocked_domains: list[str]) -> bool:
    host = (urlparse(url).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return False
    if any(host == blocked or host.endswith(f".{blocked}") for blocked in blocked_domains):
        return False
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_domains)


def _build_page_context(search_results: list[dict], config: ComputerFinderConfig) -> tuple[str, list[str]]:
    sections: list[str] = []
    readable_pages = 0
    for index, result in enumerate(search_results[: config.max_pages_to_read], start=1):
        page_text = _fetch_page_text(result["url"])
        if not page_text:
            page_text = result.get("snippet", "")
        if not page_text:
            continue
        readable_pages += 1
        sections.append(
            "\n".join(
                [
                    f"[{index}] {result.get('title') or 'Untitled result'}",
                    f"URL: {result['url']}",
                    f"Search provider: {result.get('provider') or '-'}" + (f" / {result.get('engine')}" if result.get("engine") else ""),
                    f"Snippet: {result.get('snippet') or '-'}",
                    "Readable page text:",
                    page_text[:3500],
                ]
            )
        )
    return "\n\n---\n\n".join(sections), [
        f"Read {readable_pages} candidate product or reseller page(s).",
        "Prepared source snippets for the final Ollama recommendation prompt.",
    ]


def _fetch_page_text(url: str) -> str:
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
        response.raise_for_status()
    except Exception:
        return ""
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return ""
    text = response.text
    text = re.sub(r"(?is)<(script|style|noscript|svg|iframe).*?</\1>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if len(line) > 30]
    return "\n".join(lines)[:5000]


def _sources_from_page_context(search_results: list[dict]) -> list[dict]:
    sources = []
    seen_urls = set()
    for result in search_results:
        url = result.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append({"title": result.get("title") or urlparse(url).netloc, "url": url})
    return sources[:20]


def _clean_html(value: str) -> str:
    value = re.sub(r"(?s)<[^>]+>", " ", value or "")
    return " ".join(html.unescape(value).split())
