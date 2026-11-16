from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from job_agent.adapters.base import BoardAdapter
from job_agent.adapters.jobsbg_adapter import JobsBgAdapter
from job_agent.adapters.registry import create_default_registry
from job_agent.models import Job


FIXTURES = Path(__file__).parent / "fixtures" / "jobsbg"
JOB_URL = "https://www.jobs.bg/en/job/8667546"
LISTING_URL = "https://www.jobs.bg/en/front_job_search.php?subm=1"


def _serve_fixture(page, url: str, fixture: Path) -> None:
    html = fixture.read_text(encoding="utf-8")
    page.route(
        url,
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body=html,
        ),
    )


def test_jobsbg_adapter_extracts_posting_from_saved_page() -> None:
    adapter = JobsBgAdapter()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        _serve_fixture(page, JOB_URL, FIXTURES / "job_page.html")

        job = adapter.scrape_job(page, JOB_URL)

        assert isinstance(adapter, BoardAdapter)
        assert job == Job(
            url=JOB_URL,
            title="AI Automation Engineer Lead",
            company="SBT SOLUTIONS LTD",
            description=(
                "Build and operate production AI systems.\n"
                "What You Will Do\n"
                "- Architect and build AI agents.\n"
                "What We Are Looking For\n"
                "- 5+ years of backend engineering experience.\n"
                "- Strong Python and SQL skills.\n"
                "What We Offer\n"
                "- Hybrid working environment based in Sofia.\n"
                "Join Us\n"
                "Build systems with human oversight."
            ),
            location="Sofia",
            employment_type="Full time",
            requirements=[
                "5+ years of backend engineering experience.",
                "Strong Python and SQL skills.",
            ],
            benefits=["Hybrid working environment based in Sofia."],
            tags=["Python"],
            date_text="26.10.2026",
            date_published="2026-10-26",
        )
        browser.close()


def test_jobsbg_adapter_discovery_filters_and_deduplicates_urls() -> None:
    adapter = JobsBgAdapter()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        _serve_fixture(page, LISTING_URL, FIXTURES / "listing_page.html")

        urls = adapter.discover_listing_urls(
            page,
            LISTING_URL,
            known_urls={"https://www.jobs.bg/en/job/8667547"},
        )

        assert urls == ["https://www.jobs.bg/en/job/8667546"]
        browser.close()


def test_default_registry_resolves_jobsbg() -> None:
    registry = create_default_registry()

    assert isinstance(registry.get("JOBSBG"), JobsBgAdapter)
    assert registry.for_url(JOB_URL) is registry.get("jobsbg")
