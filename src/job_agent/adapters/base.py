"""Shared contract for job-board adapters."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from playwright.sync_api import Page

from job_agent.models import Job


@runtime_checkable
class BoardAdapter(Protocol):
    """Translate a board's pages into the common ``Job`` model."""

    board_name: str
    domains: tuple[str, ...]

    def discover_listing_urls(
        self,
        page: Page,
        start_url: str,
        known_urls: set[str] | None = None,
    ) -> list[str]:
        """Find new job URLs on a board's listing pages."""
        ...

    def scrape_job(self, page: Page, url: str) -> Job:
        """Extract one job page into the common model."""
        ...

    def normalize(self, job: Job | Mapping[str, Any]) -> Job:
        """Return a board result in the common ``Job`` representation."""
        ...
