"""DEV.BG adapter that preserves the established scraper's behavior."""

from __future__ import annotations

from typing import Any, Mapping

from playwright.sync_api import Page

from job_agent.devbg.scraper import DevBgScraper
from job_agent.models import Job


class DevBgAdapter:
    """Adapter interface over the legacy DEV.BG scraper."""

    board_name = "devbg"
    domains = ("dev.bg", "www.dev.bg")

    def __init__(self, scraper: DevBgScraper | None = None) -> None:
        self.scraper = scraper or DevBgScraper()

    def discover_listing_urls(
        self,
        page: Page,
        start_url: str,
        known_urls: set[str] | None = None,
    ) -> list[str]:
        """Delegate discovery without changing URL filtering or pagination."""
        return self.scraper.discover_job_urls(page, start_url, known_urls)

    def scrape_job(self, page: Page, url: str) -> Job:
        """Delegate extraction and return the legacy normalized model."""
        return self.normalize(self.scraper.scrape_job(page, url))

    @staticmethod
    def normalize(job: Job | Mapping[str, Any]) -> Job:
        """Preserve existing ``Job`` objects and convert mapping results."""
        if isinstance(job, Job):
            return job
        return Job.from_dict(dict(job))
