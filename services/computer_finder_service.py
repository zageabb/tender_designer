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
    searxng_engines: str
    search_results_per_domain: int
    max_pages_to_read: int
    allowed_domains: list[str]
    blocked_domains: list[str]
    country: str
    region: str
    city: str


@dataclass(frozen=True)
class ComputerSearchPlan:
    queries: list[str]
    negative_terms: list[str]
    requirements: dict[str, str]
    expanded_terms: list[str]
    source: str


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
        searxng_engines=(get_setting("computer_finder_searxng_engines") or "").strip(),
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
    search_plan, planning_steps = _plan_searches(client, config.model, computer_spec, config)
    search_results, search_steps = _collect_search_results(computer_spec, search_plan, config)
    page_context, page_steps = _build_page_context(search_results, config)
    if not page_context:
        raise ComputerFinderConfigError(
            "SearXNG is connected, but it returned no readable product results for the planner queries or configured-domain refinement. "
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


def _plan_searches(client: OllamaClient, model_name: str, computer_spec: str, config: ComputerFinderConfig) -> tuple[ComputerSearchPlan, list[str]]:
    prompt = render_prompt(
        "computer_finder_query_planning",
        computer_spec=computer_spec.strip(),
        allowed_domains="\n".join(f"- {domain}" for domain in config.allowed_domains),
        market_context=", ".join(part for part in [config.city, config.region, config.country] if part) or "No market location configured",
    )
    try:
        parsed, raw_response, error = client.generate_json(model_name, prompt)
    except Exception as exc:
        return _fallback_search_plan(computer_spec), [f"Search planning used fallback rules because Ollama planning failed: {exc}"]
    if parsed is None or error is not None:
        return _fallback_search_plan(computer_spec), [f"Search planning used fallback rules because the model returned invalid JSON: {error or raw_response}"]
    queries = _normalise_query_list(parsed.get("queries", []), config.allowed_domains, max_items=6)
    if not queries:
        return _fallback_search_plan(computer_spec), ["Search planning used fallback rules because no usable queries were returned."]
    negative_terms = _normalise_term_list(parsed.get("negative_terms", []), max_items=10)
    if not negative_terms:
        negative_terms = _default_negative_terms(computer_spec)
    requirements = _normalise_requirements(parsed.get("requirements", {}))
    expanded_terms = _normalise_term_list(parsed.get("expanded_terms", []), max_items=12)
    plan = ComputerSearchPlan(
        queries=queries,
        negative_terms=negative_terms,
        requirements=requirements,
        expanded_terms=expanded_terms,
        source="ollama",
    )
    steps = [
        f"Planned {len(plan.queries)} search query path(s) with Ollama search planner.",
    ]
    if plan.requirements:
        summary = "; ".join(f"{key}: {value}" for key, value in list(plan.requirements.items())[:8])
        steps.append(f"Planner parsed requirements: {summary}.")
    if plan.expanded_terms:
        steps.append("Planner expanded search terms: " + ", ".join(plan.expanded_terms[:10]) + ".")
    if plan.negative_terms:
        steps.append("Planner excluded common false matches: " + ", ".join(f"-{term}" for term in plan.negative_terms[:10]) + ".")
    return plan, steps


def _fallback_search_plan(computer_spec: str) -> ComputerSearchPlan:
    spec_lower = computer_spec.lower()
    display = _first_match(computer_spec, [r"\b\d{2}(?:\.\d)?(?=\s*(?:\"|inch|in|”))", r"\b\d{2}(?:\.\d)?\b"]) or "15.6"
    ram = _first_match(computer_spec, [r"\b\d+\s*gb\s*ram\b", r"\b\d+\s*gb\b"]) or "16GB"
    storage = _first_match(computer_spec, [r"\b\d+\s*(?:gb|tb)\s*ssd\b", r"\b\d+\s*(?:gb|tb)\b"]) or "512GB SSD"
    os_term = "Windows 11 Pro" if "windows 11 pro" in spec_lower else "Windows 11"
    warranty = "3 year warranty" if "3 year" in spec_lower or "3-year" in spec_lower else "warranty"
    queries = [
        f'"{display}" business laptop "{ram}" "{storage}" "{os_term}" Ethernet {warranty}',
        f'Core i5 14th Gen business laptop "{ram}" "{storage}" "{os_term}" Ethernet {warranty}',
        f'Ryzen 5 7530U business laptop "{ram}" "{storage}" "{os_term}" Ethernet {warranty}',
        f'business laptop "{ram}" "{storage}" "{os_term}" Ethernet LAN port Autopilot hardware hash',
        f'ProBook 450 Latitude 3550 ThinkPad E16 "{ram}" "{storage}" "{os_term}" Ethernet {warranty}',
        f'TravelMate P2 ExpertBook B1 business laptop "{ram}" "{storage}" "{os_term}" Ethernet {warranty}',
    ]
    requirements = {
        "device": "business laptop" if any(term in spec_lower for term in ["laptop", "screen", "notebook"]) else "business computer",
        "display": display,
        "memory": ram,
        "storage": storage,
        "os": os_term,
        "warranty": warranty,
    }
    return ComputerSearchPlan(
        queries=_normalise_query_list(queries, [], max_items=6),
        negative_terms=_default_negative_terms(computer_spec),
        requirements=requirements,
        expanded_terms=["Ethernet", "LAN port", "Windows Autopilot hardware hash", "business laptop", "datasheet", "ProBook", "Latitude", "ThinkPad"],
        source="fallback",
    )


def _first_match(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return " ".join(match.group(0).replace("”", "").replace("“", "").replace('"', "").split())
    return ""


def _normalise_query_list(value, allowed_domains: list[str], max_items: int) -> list[str]:
    raw_items = value if isinstance(value, list) else str(value or "").splitlines()
    queries: list[str] = []
    for raw_item in raw_items:
        cleaned = _clean_planned_query(str(raw_item), allowed_domains)
        if cleaned and cleaned not in queries:
            queries.append(cleaned)
        if len(queries) >= max_items:
            break
    return queries


def _clean_planned_query(query: str, allowed_domains: list[str]) -> str:
    cleaned = " ".join(str(query or "").split())
    cleaned = re.sub(r"\bsite:\S+", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:search|find|look up)\s+(?:for\s+)?", " ", cleaned, flags=re.I)
    for domain in allowed_domains:
        escaped = re.escape(domain)
        cleaned = re.sub(rf"\b(?:https?://)?(?:www\.)?{escaped}\b", " ", cleaned, flags=re.I)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > 180:
        cleaned = cleaned[:180].rsplit(" ", 1)[0]
    return cleaned.strip()


def _normalise_term_list(value, max_items: int) -> list[str]:
    raw_items = value if isinstance(value, list) else str(value or "").splitlines()
    terms: list[str] = []
    for raw_item in raw_items:
        cleaned = str(raw_item or "").strip().strip("-").strip("\"'")
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned or len(cleaned) > 40 or cleaned.lower().startswith("site:"):
            continue
        if cleaned.lower() not in [term.lower() for term in terms]:
            terms.append(cleaned)
        if len(terms) >= max_items:
            break
    return terms


def _normalise_requirements(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    requirements: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = re.sub(r"[^a-zA-Z0-9_ -]", "", str(raw_key or "")).strip().replace(" ", "_").lower()
        if not key:
            continue
        if isinstance(raw_value, (list, tuple)):
            value_text = ", ".join(str(item).strip() for item in raw_value if str(item).strip())
        else:
            value_text = str(raw_value or "").strip()
        value_text = " ".join(value_text.split())
        if value_text:
            requirements[key] = value_text[:120]
        if len(requirements) >= 12:
            break
    return requirements


def _default_negative_terms(computer_spec: str) -> list[str]:
    spec_lower = computer_spec.lower()
    terms = ["iphone", "phone", "tablet", "wikipedia", "youtube", "number facts", "numerology"]
    if any(term in spec_lower for term in ["laptop", "notebook", "screen"]):
        terms.extend(["smartphone", "ipad", "mobile phone"])
    return terms


def _query_with_negative_terms(query: str, negative_terms: list[str]) -> str:
    existing = query.lower()
    additions: list[str] = []
    for term in negative_terms[:10]:
        cleaned = str(term or "").strip().strip("-").strip("\"'")
        if not cleaned or cleaned.lower() in existing:
            continue
        additions.append(f'-"{cleaned}"' if " " in cleaned else f"-{cleaned}")
    if not additions:
        return query
    return " ".join([query, *additions])


def _collect_search_results(computer_spec: str, search_plan: ComputerSearchPlan, config: ComputerFinderConfig) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    seen_urls: set[str] = set()
    steps: list[str] = []
    if config.searxng_url:
        searxng_results, searxng_steps = _collect_searxng_results(computer_spec, search_plan, config, seen_urls)
        results.extend(searxng_results)
        steps.extend(searxng_steps)
        return results, [*steps, "Public search-engine fallback skipped because SearXNG is configured."]

    failed_searches = 0
    for domain in config.allowed_domains:
        domain_results = 0
        for query in search_plan.queries:
            if domain_results >= config.search_results_per_domain:
                break
            site_query = f"site:{domain} {_query_with_negative_terms(query, search_plan.negative_terms)}"
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
    computer_spec: str,
    search_plan: ComputerSearchPlan,
    config: ComputerFinderConfig,
    seen_urls: set[str],
) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    attempted_queries: list[str] = []
    unresponsive: dict[str, set[str]] = {}
    errors: list[str] = []
    discarded_low_relevance = 0
    max_results = max(config.max_pages_to_read * 2, 12)

    search_queries = _searxng_query_candidates(search_plan, config)[:12]
    planner_results = 0
    refined_results = 0
    for query_payload in search_queries:
        if len(results) >= max_results:
            break
        query = query_payload["query"]
        strict_domains = query_payload["strict_domains"]
        search_mode = query_payload["search_mode"]
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
            if strict_domains and not _domain_allowed(url, config.allowed_domains, config.blocked_domains):
                continue
            if not strict_domains and _domain_blocked(url, config.blocked_domains):
                continue
            if not strict_domains and not _result_relevant_to_spec(result, computer_spec, config.allowed_domains):
                discarded_low_relevance += 1
                continue
            seen_urls.add(url)
            if strict_domains:
                refined_results += 1
            else:
                planner_results += 1
            results.append(
                {
                    "title": result.get("title") or urlparse(url).netloc,
                    "url": url,
                    "snippet": result.get("content") or result.get("snippet") or "",
                    "provider": "SearXNG",
                    "engine": result.get("engine") or "",
                    "search_mode": search_mode,
                }
            )
            if len(results) >= max_results:
                break

    steps = [
        f"SearXNG provider: {config.searxng_url}",
        f"SearXNG engines: {config.searxng_engines or 'default'}",
        f"SearXNG query attempts: {len(attempted_queries)}.",
        f"SearXNG collected {len(results)} candidate result(s): {planner_results} from planner queries, {refined_results} from configured-domain refinement.",
    ]
    if attempted_queries:
        steps.append("SearXNG tried: " + " | ".join(attempted_queries[:6]) + (" | ..." if len(attempted_queries) > 6 else ""))
    if unresponsive:
        summaries = []
        for engine, reasons in sorted(unresponsive.items()):
            summaries.append(f"{engine} ({', '.join(sorted(reasons))})")
        steps.append("SearXNG unresponsive engines: " + "; ".join(summaries[:8]) + ("; ..." if len(summaries) > 8 else ""))
    if discarded_low_relevance:
        steps.append(f"Discarded {discarded_low_relevance} low-relevance planner-query result(s) before asking Ollama.")
    if errors:
        steps.append("SearXNG request errors: " + " | ".join(errors[:3]) + (" | ..." if len(errors) > 3 else ""))
    return results, steps


def _searxng_query_candidates(search_plan: ComputerSearchPlan, config: ComputerFinderConfig) -> list[dict]:
    candidates: list[dict] = []
    seen: set[tuple[str, bool, str]] = set()

    def add(query: str, strict_domains: bool, search_mode: str) -> None:
        cleaned = " ".join(query.split())
        key = (cleaned, strict_domains, search_mode)
        if cleaned and key not in seen:
            seen.add(key)
            candidates.append({"query": cleaned, "strict_domains": strict_domains, "search_mode": search_mode})

    for query in search_plan.queries[:6]:
        add(_query_with_negative_terms(query, search_plan.negative_terms), strict_domains=False, search_mode="planner query")
    for domain in config.allowed_domains[:8]:
        for query in search_plan.queries[:2]:
            add(f"site:{domain} {_query_with_negative_terms(query, search_plan.negative_terms)}", strict_domains=True, search_mode="configured domain refinement")
    return candidates


def _searxng_search(query: str, config: ComputerFinderConfig) -> dict:
    params = {
        "q": query,
        "format": "json",
        "safesearch": "0",
        "language": "all",
    }
    if config.searxng_engines:
        params["engines"] = config.searxng_engines
    response = requests.get(
        f"{config.searxng_url}/search",
        params=params,
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
    if _domain_blocked(url, blocked_domains):
        return False
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_domains)


def _domain_blocked(url: str, blocked_domains: list[str]) -> bool:
    host = (urlparse(url).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return False
    return any(host == blocked or host.endswith(f".{blocked}") for blocked in blocked_domains)


def _result_relevant_to_spec(result: dict, computer_spec: str, allowed_domains: list[str]) -> bool:
    title_and_snippet = " ".join(
        [
            str(result.get("title") or ""),
            str(result.get("content") or result.get("snippet") or ""),
        ]
    ).lower()
    url = str(result.get("url") or "")
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    haystack = " ".join([title_and_snippet, url.lower()])
    if not haystack.strip():
        return False
    spec_lower = computer_spec.lower()
    if any(term in spec_lower for term in ["laptop", "notebook", "screen"]):
        non_laptop_terms = {
            "iphone",
            "ipad",
            "smartphone",
            "mobile phone",
            "cell phone",
            "youtube",
            "music video",
            "wikipedia",
            "number facts",
            "number fifteen",
        }
        if any(_search_term_present(title_and_snippet, term) or _search_term_present(parsed.path.lower(), term) for term in non_laptop_terms):
            return False
    strong_terms = {
        "laptop",
        "notebook",
        "business laptop",
        "probook",
        "elitebook",
        "thinkpad",
        "latitude",
        "vostro",
        "optiplex",
        "workstation",
    }
    spec_terms = {
        "16gb",
        "512gb",
        "ssd",
        "rj45",
        "windows 11",
        "windows 11 pro",
        "ryzen",
        "intel",
        "core i5",
        "i5",
        "7530u",
        "14th gen",
        "3 year",
        "warranty",
    }
    brand_terms = {domain.split(".")[0] for domain in allowed_domains}
    score = 0
    if any(_search_term_present(haystack, term) for term in strong_terms):
        score += 2
    score += sum(1 for term in spec_terms if _search_term_present(haystack, term))
    if any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
        score += 1
    score += sum(1 for term in brand_terms if term and _search_term_present(title_and_snippet, term))
    if "laptop" in spec_lower and _search_term_present(haystack, "laptop"):
        score += 1
    return score >= 2


def _search_term_present(text: str, term: str) -> bool:
    if not term:
        return False
    if re.search(r"[a-z0-9]", term):
        pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(part) for part in term.lower().split()) + r"(?![a-z0-9])"
        return re.search(pattern, text.lower()) is not None
    return term.lower() in text.lower()


def _build_page_context(search_results: list[dict], config: ComputerFinderConfig) -> tuple[str, list[str]]:
    sections: list[str] = []
    readable_pages = 0
    for index, result in enumerate(search_results[: config.max_pages_to_read], start=1):
        page_text = ""
        if result.get("search_mode") == "exact query":
            page_text = result.get("snippet", "")
        if not page_text:
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
                    f"Search mode: {result.get('search_mode') or '-'}",
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
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=8)
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
