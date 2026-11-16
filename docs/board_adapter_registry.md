# Board Adapter Registry

The adapter layer gives each job board a common interface while leaving the
existing DEV.BG scraping behavior in place. The contract is defined by
[`BoardAdapter`](../src/job_agent/adapters/base.py), and
[`AdapterRegistry`](../src/job_agent/adapters/registry.py) resolves adapters
by board name, exact hostname, or an explicitly registered wildcard domain.

## DEV.BG adapter

[`DevBgAdapter`](../src/job_agent/adapters/devbg_adapter.py) delegates listing
discovery and job extraction to the existing `DevBgScraper`. This keeps the
legacy CLI and scraping behavior unchanged while allowing new callers to use
the shared adapter contract:

```python
from job_agent.adapters.devbg_adapter import DevBgAdapter

adapter = DevBgAdapter()
job = adapter.scrape_job(page, job_url)
new_urls = adapter.discover_listing_urls(page, listing_url, known_urls)
```

`normalize` accepts either an existing `Job` or a mapping and returns a `Job`.
The registry's `create_default_registry()` factory registers DEV.BG, Jobs.bg,
and LinkedIn; `get(board_name)` resolves by board name and `for_url(url)`
resolves by hostname. Unknown names or hosts raise `KeyError`; duplicate names
or domains raise `ValueError`.

## Generic extraction and recipes

[`GenericAdapter`](../src/job_agent/adapters/generic_adapter.py) loads a
posting once and tries Schema.org `JobPosting` JSON-LD first. It traverses
single objects, lists, and `@graph`, normalizes common fields into `Job`, and
raises an explicit error when required structured fields are missing and no
recipe can recover them. If no usable JobPosting block exists, it uses an optional
[`ExtractionRecipe`](../src/job_agent/adapters/recipe_adapter.py), a
JSON-serializable set of CSS selectors for required and optional fields.
Recipes are reusable, board-specific selectors learned from observed markup;
they are configuration, not an automatic model-training system.

## LinkedIn adapter

[`LinkedInAdapter`](../src/job_agent/adapters/linkedin_adapter.py) uses the
generic JSON-LD-first flow with a selector recipe for LinkedIn's public job
pages. It recognizes regional `*.linkedin.com` hosts for public job URLs and
search results. It does not sign in, submit applications, or bypass access
controls. Listing discovery processes the page provided and does not paginate
automatically.

## Adding a board

Implement `BoardAdapter` with a stable `board_name`, one or more `domains`,
listing URL discovery, job extraction, and normalization. Register it with an
`AdapterRegistry`, then add saved listing and job HTML fixtures with parity or
golden tests. Adapter tests should remain offline and verify that extracted
`Job` values and discovered URLs preserve the board's expected behavior.

Run the DEV.BG contract and parity tests with:

```bash
uv run pytest tests/test_adapter_parity.py -q
```

## Jobs.bg adapter

[`JobsBgAdapter`](../src/job_agent/adapters/jobsbg_adapter.py) extracts the
title, company, description, date, location, employment type, skill tags,
requirements, and benefits from Jobs.bg's job-view markup. It also discovers
job links from a search or listing page. The default registry recognizes both
`jobs.bg` and `www.jobs.bg`.

The saved-page tests exercise the observed page structure without depending on
Jobs.bg being reachable during test runs:

```bash
uv run pytest tests/test_jobsbg_adapter.py -q
```

Run the generic JSON-LD/recipe and LinkedIn fixture validation with:

```bash
uv run pytest tests/test_generic_adapters.py -q
```
