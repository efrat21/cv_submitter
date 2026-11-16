"""Generic job-board adapter with JSON-LD-first extraction."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Page

from job_agent.adapters.jsonld_adapter import JsonLdAdapter
from job_agent.adapters.recipe_adapter import ExtractionRecipe, RecipeAdapter
from job_agent.models import Job


_DEFAULT_JOB_PATH = re.compile(r"/(?:jobs/view|job)/\d+/?$", re.IGNORECASE)


class GenericAdapter:
    """Extract jobs from supported hosts using structured data or a recipe."""

    def __init__(
        self,
        board_name: str,
        domains: tuple[str, ...],
        *,
        recipe: ExtractionRecipe | None = None,
        job_path_pattern: re.Pattern[str] = _DEFAULT_JOB_PATH,
    ) -> None:
        if not board_name.strip():
            raise ValueError("Adapter board_name must not be empty")
        if not domains or any(not domain.strip() for domain in domains):
            raise ValueError("Adapter domains must contain non-empty hostnames")

        self.board_name = board_name
        self.domains = domains
        self._job_path_pattern = job_path_pattern
        self._jsonld = JsonLdAdapter()
        self._recipe = RecipeAdapter(recipe) if recipe is not None else None

    def discover_listing_urls(
        self,
        page: Page,
        start_url: str,
        known_urls: set[str] | None = None,
    ) -> list[str]:
        """Find unique job links for this adapter's registered domains."""
        self._navigate(page, start_url)
        known = {
            canonical
            for url in (known_urls or set())
            if (canonical := self._canonical_job_url(url)) is not None
        }
        discovered: list[str] = []
        seen: set[str] = set()
        for href in page.locator("a[href]").evaluate_all(
            "(elements) => elements.map((element) => element.href)"
        ):
            canonical = self._canonical_job_url(href)
            if canonical is None or canonical in seen:
                continue
            seen.add(canonical)
            if canonical not in known:
                discovered.append(canonical)
        return discovered

    def scrape_job(self, page: Page, url: str) -> Job:
        """Prefer Schema.org JobPosting data, then use a configured recipe."""
        self._navigate(page, url)
        try:
            job = self._jsonld.extract_job(page, url)
        except ValueError as structured_error:
            if self._recipe is None:
                raise
            try:
                return self._recipe.extract_job(page, url)
            except ValueError as recipe_error:
                raise ValueError(
                    f"JSON-LD extraction failed ({structured_error}); "
                    f"recipe extraction failed ({recipe_error})"
                ) from recipe_error
        if job is not None:
            return job
        if self._recipe is not None:
            return self._recipe.extract_job(page, url)
        raise ValueError(
            f"No JobPosting JSON-LD or extraction recipe available for {url}"
        )

    @staticmethod
    def normalize(job: Job | Mapping[str, Any]) -> Job:
        """Return a board result in the common ``Job`` representation."""
        if isinstance(job, Job):
            return job
        return Job.from_dict(dict(job))

    def _canonical_job_url(self, url: str) -> str | None:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").casefold()
        domain = next(
            (
                registered.casefold().removeprefix("www.")
                for registered in self.domains
                if hostname == registered.casefold().removeprefix("www.")
                or hostname.endswith(
                    f".{registered.casefold().removeprefix('www.')}"
                )
            ),
            None,
        )
        if domain is None:
            return None
        if not self._job_path_pattern.search(parsed.path):
            return None
        return f"https://{domain}{parsed.path.rstrip('/')}"

    @staticmethod
    def _navigate(page: Page, url: str) -> None:
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if response is not None and response.status >= 400:
            raise RuntimeError(f"Board returned HTTP {response.status} for URL: {url}")
