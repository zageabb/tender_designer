# Equipment Research

Tender Designer's former Computer Finder workflow is now presented as **Equipment Research**. The existing `/computer-finder` routes are retained for compatibility, but the research objective is broader: find real equipment against tender technical requirements, compare compliance from sourced evidence, and keep commercial information separate from the technical decision.

## Research behaviour

Equipment Research now:

- treats the tender specification as authoritative;
- extracts mandatory, preferred and ambiguous requirements before searching;
- plans equipment-category-aware searches for OEM pages, datasheets, manuals, catalogues and procurement evidence;
- searches the open web by default rather than forcing the old computer-supplier allowlist;
- reads HTML first and uses structured JSON-LD product metadata when available;
- reads public PDF datasheets directly with `pypdf`;
- can use a bounded Playwright/Chromium fallback for JavaScript-heavy pages when the lightweight result does not contain enough technical evidence;
- can supplement web search with a local free public-procurement index built from Find a Tender and Sell2Wales OCDS data;
- performs evidence-gap searches when important technical requirements remain unresolved;
- classifies requirements as Pass, Partial / Engineering review, Fail or Unknown;
- ranks candidates by technical compliance and evidence quality, not by price;
- reports price, availability, warranty or other commercial facts only as a separate optional section when the evidence contains them;
- keeps General Search on its existing general-purpose planning and refinement behaviour.

The existing IT machine specification-sheet generator remains available for computer procurements. It is labelled separately in the Equipment Research UI because that document template is computer-specific.

## Install dependencies

After pulling the upgrade:

```bash
cd tender_designer
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

On a new Ubuntu host, Playwright's operating-system libraries may also need to be installed once by an administrator:

```bash
sudo .venv/bin/python -m playwright install-deps chromium
```

The application does not try to bypass logins, CAPTCHAs, bot challenges or other access controls. If Chromium is unavailable, Equipment Research falls back to the lightweight HTTP/PDF evidence path rather than failing the whole search.

## Browser fallback controls

The dynamic-page fallback is intentionally bounded. Optional environment variables are:

```bash
TENDER_RESEARCH_BROWSER_FALLBACK=1
TENDER_RESEARCH_BROWSER_MAX_PAGES=3
TENDER_RESEARCH_BROWSER_TIMEOUT_MS=15000
TENDER_RESEARCH_BROWSER_SETTLE_MS=1200
```

Limits are clamped in code. Images, media, fonts and common advertising/analytics hosts are blocked during rendered-page retrieval, and public-URL checks remain in force for browser requests.

### Restrict Equipment Research to configured sites

Open-web search is the default because industrial/HV evidence is commonly spread across OEM sites, technical documents and public procurement sources. To restore the old allowlist-only behaviour for Equipment Research, set:

```bash
TENDER_RESEARCH_ALLOWED_SITES_ONLY=1
```

The existing `computer_finder_allowed_domains` setting supplies that allowlist. General Search keeps its own existing allowed-sites toggle behaviour.

## Optional public procurement index

Equipment Research works without a local procurement index. To add UK public procurement evidence, build or refresh it with:

```bash
cd tender_designer
source .venv/bin/activate
python procurement_ingest.py
```

The default database is:

```text
instance/procurement.sqlite3
```

The ingestion utility currently indexes recent Find a Tender OCDS releases and completed Sell2Wales calendar months. Search results from this index are treated as supporting evidence; published procurement values, when present, remain commercial metadata and do not affect technical compliance.

Example refresh with wider history:

```bash
python procurement_ingest.py \
  --find-tender-days 180 \
  --find-tender-max-pages 50 \
  --sell2wales-months 12
```

## Example equipment workflow

Input:

```text
11 kV AIS switchboard
3000 A busbar
25 kA short-circuit rating
2 x 2000 A incomers
1 x 1600 A bus coupler
8 x 630 A feeders
4 x 1200 A feeders
IEC 62271-200
```

The expected research flow is:

1. Parse the ratings, configuration and standard as technical requirements.
2. Search exact requirements and sensible OEM/product-family equivalents.
3. Prefer OEM datasheets and technical catalogues; add utility/procurement evidence where useful.
4. Read HTML, structured product metadata and PDFs; render shortlisted dynamic pages only when required.
5. Compare each supported candidate against every important tender requirement.
6. Continue with focused searches for unresolved mandatory facts.
7. Return a technical compliance matrix, supported candidates, deviations/unknowns, engineering-review points and next actions.
8. Show commercial information only when found and explicitly state that it did not influence technical compliance.

## Compatibility

Internal Python names and URLs still contain `computer_finder` so existing links, saved workflows and APIs do not need an immediate migration. The user-facing navigation and tender-selection workflow use **Equipment Research** terminology.
