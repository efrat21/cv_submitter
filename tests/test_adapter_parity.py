from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from job_agent.adapters.base import BoardAdapter
from job_agent.adapters.devbg_adapter import DevBgAdapter
from job_agent.adapters.registry import AdapterRegistry, create_default_registry
from job_agent.devbg.scraper import DevBgScraper
from job_agent.models import Job


FIXTURES = Path(__file__).parent / "fixtures" / "devbg"
JOB_URL = "https://dev.bg/company/jobads/101/"
LISTING_URL = "https://dev.bg/company/jobs/ml-ai-data/"


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


def test_devbg_adapter_matches_legacy_scraper_on_saved_job_page() -> None:
    scraper = DevBgScraper(headless=True, delay=0, max_pages=1)
    adapter = DevBgAdapter(scraper)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        _serve_fixture(page, JOB_URL, FIXTURES / "job_page.html")

        legacy_job = scraper.scrape_job(page, JOB_URL)
        adapter_job = adapter.scrape_job(page, JOB_URL)

        assert isinstance(adapter, BoardAdapter)
        assert adapter_job.to_dict() == legacy_job.to_dict()
        assert adapter_job == Job(
            url=JOB_URL,
            title="Senior Python Engineer",
            company="Acme Engineering",
            description=(
                "Python FastAPI\n\nBuild reliable Python services for data products.\n\n"
                "Requirements\n\nStrong Python experience\n\nProduction API development\n\n"
                "What we offer\n\nFlexible hybrid work"
            ),
            location="Sofia",
            employment_type="Full-time",
            work_model="Hybrid",
            requirements=["Strong Python experience", "Production API development"],
            benefits=["Flexible hybrid work"],
            tags=["Python", "FastAPI", "ML/AI/Data modelling"],
            date_text="Публикувана преди 2 дни",
            date_published="2026-11-14",
        )
        browser.close()


def test_devbg_adapter_discovery_matches_legacy_scraper_on_saved_listing() -> None:
    scraper = DevBgScraper(headless=True, delay=0, max_jobs=10, max_pages=1)
    adapter = DevBgAdapter(scraper)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        _serve_fixture(page, LISTING_URL, FIXTURES / "listing_page.html")

        legacy_urls = scraper.discover_job_urls(page, LISTING_URL)
        adapter_urls = adapter.discover_listing_urls(page, LISTING_URL)

        assert adapter_urls == legacy_urls == [
            "https://dev.bg/company/jobads/101/",
            "https://dev.bg/company/jobads/102/",
        ]
        browser.close()


def test_adapter_registry_resolves_devbg_and_rejects_unknown_sites() -> None:
    registry = create_default_registry()
    adapter = registry.get("DEVBG")

    assert adapter is registry.for_url("https://www.dev.bg/company/jobads/101/")
    try:
        registry.for_url("https://example.com/jobs")
    except KeyError as error:
        assert "No adapter registered" in str(error)
    else:
        raise AssertionError("Unknown board URL should not resolve to an adapter")


def test_registry_rejects_duplicate_domains() -> None:
    registry = AdapterRegistry()
    registry.register(DevBgAdapter())

    class OtherDevBgAdapter(DevBgAdapter):
        board_name = "other-devbg"

    with pytest.raises(ValueError, match="domains already registered"):
        registry.register(OtherDevBgAdapter())


def test_adapter_normalizes_mapping_without_mutating_it() -> None:
    source = {
        "url": JOB_URL,
        "title": "Engineer",
        "company": "Acme",
        "description": "Build software",
        "tags": ["Python"],
    }

    job = DevBgAdapter.normalize(source)

    assert job == Job(
        url=JOB_URL,
        title="Engineer",
        company="Acme",
        description="Build software",
        tags=["Python"],
    )
    assert source["tags"] == ["Python"]
