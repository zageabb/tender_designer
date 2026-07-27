from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
import trafilatura
from ddgs import DDGS

from services.ollama_client import OllamaClient


SEARCH_HEADERS = {
    "User-Agent": "TenderDesignerResearchAgent/2.0 (+procurement research)",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.8,*/*;q=0.5",
}


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    query: str


@dataclass(frozen=True)
class Evidence:
    source_id: int
    title: str
    url: str
    text: str
    query: str


class DDGSSearchProvider:
    """Metasearch adapter kept separate so another provider can be swapped in."""

    def __init__(self, region: str = "wt-wt", backend: str = "auto", timeout: int = 12) -> None:
        self.region = region
        self.backend = backend
        self.timeout = timeout

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        rows = DDGS(timeout=self.timeout).text(
            query,
            region=self.region,
            safesearch="moderate",
            max_results=max_results,
            backend=self.backend,
        )
        return [
            SearchResult(
                title=str(row.get("title") or row.get("href") or "Untitled result"),
                url=str(row.get("href") or ""),
                snippet=str(row.get("body") or ""),
                query=query,
            )
            for row in rows
            if row.get("href")
        ]


class WebPageReader:
    def __init__(self, timeout: int = 15, max_characters: int = 12000) -> None:
        self.timeout = timeout
        self.max_characters = max_characters

    def read(self, result: SearchResult, source_id: int) -> Evidence | None:
        if not _safe_public_url(result.url):
            return None
        try:
            response = requests.get(
                result.url,
                headers=SEARCH_HEADERS,
                timeout=self.timeout,
                allow_redirects=True,
            )
            response.raise_for_status()
            if not _safe_public_url(response.url):
                return None
        except requests.RequestException:
            return self._snippet_evidence(result, source_id)

        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type:
            return self._snippet_evidence(result, source_id)
        extracted = trafilatura.extract(
            response.text,
            url=response.url,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        text = " ".join((extracted or "").split())
        if len(text) < 80:
            return self._snippet_evidence(result, source_id)
        return Evidence(source_id, result.title, response.url, text[: self.max_characters], result.query)

    @staticmethod
    def _snippet_evidence(result: SearchResult, source_id: int) -> Evidence | None:
        snippet = " ".join(result.snippet.split())
        if not snippet:
            return None
        return Evidence(source_id, result.title, result.url, snippet, result.query)


class OllamaWebResearchAgent:
    def __init__(
        self,
        ollama_url: str,
        model: str,
        search_provider: DDGSSearchProvider,
        page_reader: WebPageReader,
        allowed_domains: list[str],
        blocked_domains: list[str],
        max_rounds: int = 3,
        max_pages: int = 10,
        results_per_query: int = 6,
    ) -> None:
        self.client = OllamaClient(ollama_url)
        self.model = model
        self.search_provider = search_provider
        self.page_reader = page_reader
        self.allowed_domains = allowed_domains
        self.blocked_domains = blocked_domains
        self.max_rounds = max(1, min(max_rounds, 5))
        self.max_pages = max(1, min(max_pages, 20))
        self.results_per_query = max(2, min(results_per_query, 10))

    def research(self, specification: str, market: str, current_date: str) -> dict:
        queries, requirements, planning_step = self._plan(specification, market)
        evidence: list[Evidence] = []
        seen_urls: set[str] = set()
        steps = [planning_step]

        for round_number in range(1, self.max_rounds + 1):
            candidates = self._search_round(queries, seen_urls)
            remaining = self.max_pages - len(evidence)
            if remaining <= 0:
                break
            opened = self._read_pages(candidates[:remaining], len(evidence) + 1)
            evidence.extend(opened)
            steps.append(
                f"Research round {round_number}: ran {len(queries)} queries, found "
                f"{len(candidates)} new results, and retained {len(opened)} readable sources."
            )
            if round_number >= self.max_rounds or len(evidence) >= self.max_pages:
                break
            queries, complete, assessment = self._assess_and_refine(
                specification, requirements, evidence, market
            )
            steps.append(assessment)
            if complete or not queries:
                break

        if not evidence:
            raise ValueError("The research agent found no readable product evidence.")
        answer = self._synthesise(specification, requirements, evidence, market, current_date)
        return {
            "answer": answer,
            "sources": [
                {"title": item.title, "url": item.url, "source_id": item.source_id}
                for item in evidence
            ],
            "steps": [f"Ollama research model: {self.model}", *steps],
        }

    def _plan(self, specification: str, market: str) -> tuple[list[str], dict, str]:
        prompt = f"""You are planning web research for a computer procurement request.
Return JSON only:
{{
  "requirements": {{"requirement_name": "required value"}},
  "queries": ["focused product search query"]
}}
Create 3-6 distinct queries. Include exact technical constraints and the market. Use model families,
manufacturer datasheets, business resellers, warranty and availability queries where helpful.
Do not include site: filters.

Market: {market}
Specification:
{specification}"""
        parsed, raw, error = self.client.generate_json(self.model, prompt)
        if parsed and isinstance(parsed.get("queries"), list):
            queries = _clean_queries(parsed["queries"])
            requirements = parsed.get("requirements") if isinstance(parsed.get("requirements"), dict) else {}
            if queries:
                return queries[:6], requirements, f"Ollama planned {len(queries[:6])} targeted search queries."
        fallback = [
            f"{specification} {market} business computer",
            f"{specification} manufacturer datasheet",
            f"{specification} price availability warranty {market}",
        ]
        detail = error or raw or "empty response"
        return _clean_queries(fallback), {}, f"Used deterministic search planning because Ollama planning was unusable: {detail[:160]}"

    def _search_round(self, queries: list[str], seen_urls: set[str]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for query in queries:
            try:
                rows = self.search_provider.search(query, self.results_per_query)
            except Exception:
                continue
            for row in rows:
                url = _normalise_url(row.url)
                if not url or url in seen_urls or not self._domain_permitted(url):
                    continue
                seen_urls.add(url)
                results.append(SearchResult(row.title, url, row.snippet, row.query))
        return results

    def _read_pages(self, results: list[SearchResult], first_source_id: int) -> list[Evidence]:
        if not results:
            return []
        indexed = list(enumerate(results, start=first_source_id))
        evidence: list[Evidence] = []
        with ThreadPoolExecutor(max_workers=min(5, len(indexed))) as executor:
            futures = {
                executor.submit(self.page_reader.read, result, source_id): source_id
                for source_id, result in indexed
            }
            for future in as_completed(futures):
                try:
                    item = future.result()
                except Exception:
                    item = None
                if item:
                    evidence.append(item)
        return sorted(evidence, key=lambda item: item.source_id)

    def _assess_and_refine(
        self,
        specification: str,
        requirements: dict,
        evidence: list[Evidence],
        market: str,
    ) -> tuple[list[str], bool, str]:
        prompt = f"""Assess the evidence collected for a computer procurement search.
Return JSON only:
{{
  "complete": true,
  "missing_facts": ["fact"],
  "follow_up_queries": ["focused query"]
}}
Set complete true only when at least three plausible exact models can be compared and the important
requirements are supported or explicitly identified as unknown. Produce no more than 4 follow-up queries.

Market: {market}
Specification: {specification}
Parsed requirements: {requirements}
Evidence:
{_evidence_context(evidence, 22000)}"""
        parsed, raw, error = self.client.generate_json(self.model, prompt)
        if not parsed:
            return [], True, f"Stopped refinement because Ollama returned an unusable evidence assessment: {(error or raw)[:160]}"
        queries = _clean_queries(parsed.get("follow_up_queries") or [])[:4]
        missing = [str(item) for item in (parsed.get("missing_facts") or [])[:8]]
        complete = bool(parsed.get("complete"))
        summary = "Evidence assessment"
        if missing:
            summary += " identified gaps: " + ", ".join(missing)
        if queries and not complete:
            summary += f"; planned {len(queries)} follow-up queries."
        else:
            summary += "; research was sufficient."
        return queries, complete, summary

    def _synthesise(
        self,
        specification: str,
        requirements: dict,
        evidence: list[Evidence],
        market: str,
        current_date: str,
    ) -> str:
        prompt = f"""You are a careful computer procurement analyst. Write the final recommendation using
only the numbered evidence below. Cite factual claims with source IDs exactly like [1] or [2].
Do not cite a source that does not support the claim. Never invent specifications, configurations,
prices, availability, licensing, hardware hashes, or warranty terms.

Return Markdown with:
1. A short recommendation.
2. A comparison table for up to five exact models: model, CPU, RAM, storage, screen/form factor,
ports, operating system, warranty, price/availability, compliance, and sources.
3. Confirmed fit, configurable/uncertain items, and procurement risks.
4. A concise next-action recommendation.

If fewer than three credible models were found, say so rather than padding the result.

Current date: {current_date}
Market: {market}
Specification: {specification}
Parsed requirements: {requirements}
Evidence:
{_evidence_context(evidence, 50000)}"""
        answer = self.client.generate_text(self.model, prompt)
        if not answer:
            raise ValueError("Ollama returned an empty final recommendation.")
        return answer

    def _domain_permitted(self, url: str) -> bool:
        host = _hostname(url)
        if not host:
            return False
        if any(host == domain or host.endswith(f".{domain}") for domain in self.blocked_domains):
            return False
        if not self.allowed_domains:
            return True
        return any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains)


def _evidence_context(evidence: list[Evidence], limit: int) -> str:
    sections = [
        f"[{item.source_id}] {item.title}\nURL: {item.url}\nFound via: {item.query}\nContent: {item.text}"
        for item in evidence
    ]
    return "\n\n---\n\n".join(sections)[:limit]


def _clean_queries(values) -> list[str]:
    if not isinstance(values, list):
        return []
    queries: list[str] = []
    for value in values:
        query = " ".join(str(value or "").split())[:300]
        if query and query.lower() not in {item.lower() for item in queries}:
            queries.append(query)
    return queries


def _normalise_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return parsed._replace(fragment="").geturl()


def _hostname(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def _safe_public_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".local"):
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            return False
    return True
