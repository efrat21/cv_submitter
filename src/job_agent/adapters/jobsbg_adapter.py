"""Jobs.bg adapter based on the board's observed job-page markup."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Locator, Page

from job_agent.models import Job


_JOB_PATH = re.compile(r"^/(?:[a-z]{2}/)?job/\d+/?$", re.IGNORECASE)


class JobsBgAdapter:
    """Discover Jobs.bg postings and extract their visible job details."""

    board_name = "jobsbg"
    domains = ("jobs.bg", "www.jobs.bg")

    def discover_listing_urls(
        self,
        page: Page,
        start_url: str,
        known_urls: set[str] | None = None,
    ) -> list[str]:
        """Find unique Jobs.bg job links on a search or listing page."""
        response = page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        if response is not None and response.status >= 400:
            raise RuntimeError(
                f"Jobs.bg returned HTTP {response.status} for listing URL: {start_url}"
            )

        known = {
            canonical
            for url in (known_urls or set())
            if (canonical := self._canonical_job_url(url)) is not None
        }
        discovered: list[str] = []
        seen: set[str] = set()
        for href in page.locator('a[href*="/job/"]').evaluate_all(
            "(elements) => elements.map((element) => element.href)"
        ):
            canonical = self._canonical_job_url(urljoin(start_url, href))
            if canonical is None or canonical in seen:
                continue
            seen.add(canonical)
            if canonical not in known:
                discovered.append(canonical)
        return discovered

    def scrape_job(self, page: Page, url: str) -> Job:
        """Extract a Jobs.bg posting using its job-view page elements."""
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if response is not None and response.status >= 400:
            raise RuntimeError(f"Jobs.bg returned HTTP {response.status} for job URL: {url}")

        title = self._required_text(page.locator(".job-view-title"), "title")
        description = self._required_text(
            page.locator(".job-view-description-text"), "description"
        )
        company = self._company_name(page)

        details = page.locator(".job-view-right-content").first
        date_text = self._optional_text(details.locator(".date"))
        location = ""
        employment_type = ""
        for option in details.locator(".options li").all():
            icon = self._optional_text(option.locator("i"))
            value = self._optional_text(option.locator("span"))
            if icon == "location_on":
                location = value
            elif icon == "schedule":
                employment_type = value

        return Job(
            url=url,
            title=title,
            company=company,
            description=description,
            location=location,
            employment_type=employment_type,
            requirements=self._section_bullets(
                description, "What We Are Looking For", "What We Offer"
            ),
            benefits=self._section_bullets(description, "What We Offer", "Join Us"),
            tags=[
                text
                for item in details.locator(".skills li").all()
                if (text := self._optional_text(item))
            ],
            date_text=date_text,
            date_published=self._parse_date(date_text),
        )

    @staticmethod
    def normalize(job: Job | Mapping[str, Any]) -> Job:
        """Return a Jobs.bg result as the shared ``Job`` model."""
        if isinstance(job, Job):
            return job
        return Job.from_dict(dict(job))

    @staticmethod
    def _canonical_job_url(url: str) -> str | None:
        parsed = urlparse(url)
        if (parsed.hostname or "").casefold().removeprefix("www.") != "jobs.bg":
            return None
        if not _JOB_PATH.fullmatch(parsed.path):
            return None
        return f"https://www.jobs.bg{parsed.path.rstrip('/')}"

    @staticmethod
    def _required_text(locator: Locator, field: str) -> str:
        value = JobsBgAdapter._optional_text(locator)
        if not value:
            raise ValueError(f"Jobs.bg page is missing required {field}")
        return value

    @staticmethod
    def _optional_text(locator: Locator) -> str:
        if locator.count() == 0:
            return ""
        return locator.first.inner_text().strip()

    @staticmethod
    def _company_name(page: Page) -> str:
        logo = page.locator('a[href*="/company/"] img[alt]').first
        company = logo.get_attribute("alt") if logo.count() else None
        if not company or not company.strip():
            raise ValueError("Jobs.bg page is missing the company name")
        return company.strip()

    @staticmethod
    def _section_bullets(description: str, start: str, end: str) -> list[str]:
        lines = description.splitlines()
        start_index = next(
            (index for index, line in enumerate(lines) if line.strip() == start),
            None,
        )
        if start_index is None:
            return []

        bullets: list[str] = []
        for line in lines[start_index + 1 :]:
            content = line.strip()
            if content == end:
                break
            if content.startswith("- "):
                bullets.append(content[2:].strip())
        return bullets

    @staticmethod
    def _parse_date(date_text: str) -> str:
        if not date_text:
            return ""
        try:
            return datetime.strptime(date_text, "%d.%m.%Y").date().isoformat()
        except ValueError:
            return ""
