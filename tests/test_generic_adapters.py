from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from job_agent.adapters.base import BoardAdapter
from job_agent.adapters.generic_adapter import GenericAdapter
from job_agent.adapters.linkedin_adapter import LinkedInAdapter
from job_agent.adapters.recipe_adapter import ExtractionRecipe
from job_agent.adapters.registry import create_default_registry
from job_agent.models import Job


FIXTURES = Path(__file__).parent / "fixtures"
JSONLD_URL = "https://example.test/jobs/101"
RECIPE_URL = "https://example.test/jobs/102"
LINKEDIN_URL = "https://www.linkedin.com/jobs/view/python-engineer-at-example-4487158438"
LINKEDIN_LISTING_URL = "https://www.linkedin.com/jobs/search/?keywords=Python"


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


def test_generic_adapter_prefers_jsonld_and_normalizes_job_posting() -> None:
    adapter = GenericAdapter(
        "example",
        ("example.test",),
        recipe=ExtractionRecipe(
            title="h1",
            company=".company",
            description=".description",
        ),
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        _serve_fixture(page, JSONLD_URL, FIXTURES / "generic" / "sample_page.html")

        job = adapter.scrape_job(page, JSONLD_URL)

        assert isinstance(adapter, BoardAdapter)
        assert job == Job(
            url=JSONLD_URL,
            title="Platform Engineer",
            company="Example Corp",
            description="Build reliable services.\n\nPython\n\nAPIs",
            location="Sofia, BG",
            employment_type="FULL_TIME, CONTRACTOR",
            requirements=["Strong Python skills", "API experience"],
            benefits=["Flexible schedule"],
            tags=["Python", "REST APIs"],
            date_text="2026-10-26",
            date_published="2026-10-26",
        )
        browser.close()


def test_generic_adapter_uses_recipe_when_jsonld_is_absent() -> None:
    recipe = ExtractionRecipe.from_mapping(
        {
            "title": "h1.job-title",
            "company": ".employer",
            "description": ".job-description",
            "location": ".job-location",
            "employment_type": ".job-type",
            "tags": ".skills li",
        }
    )
    adapter = GenericAdapter("example", ("example.test",), recipe=recipe)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        _serve_fixture(page, RECIPE_URL, FIXTURES / "generic" / "recipe_page.html")

        job = adapter.scrape_job(page, RECIPE_URL)

        assert job == Job(
            url=RECIPE_URL,
            title="Recipe-driven Engineer",
            company="Recipe Example",
            description="Use stable selectors as a reviewed recipe.",
            location="Sofia, Bulgaria",
            employment_type="Full-time",
            tags=["Python", "PostgreSQL"],
        )
        assert recipe.to_mapping()["title"] == "h1.job-title"
        browser.close()


def test_generic_adapter_falls_back_when_jsonld_is_incomplete() -> None:
    adapter = GenericAdapter(
        "example",
        ("example.test",),
        recipe=ExtractionRecipe(
            title="h1.job-title",
            company=".employer",
            description=".job-description",
        ),
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        _serve_fixture(
            page,
            RECIPE_URL,
            FIXTURES / "generic" / "incomplete_jsonld_page.html",
        )

        job = adapter.scrape_job(page, RECIPE_URL)

        assert job.title == "Recipe-driven Engineer"
        assert job.company == "Recipe Example"
        assert job.description == "Use the reviewed selector recipe."
        browser.close()


def test_generic_adapter_fails_explicitly_without_jsonld_or_recipe() -> None:
    adapter = GenericAdapter("example", ("example.test",))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        _serve_fixture(page, RECIPE_URL, FIXTURES / "generic" / "recipe_page.html")

        with pytest.raises(ValueError, match="No JobPosting JSON-LD or extraction recipe"):
            adapter.scrape_job(page, RECIPE_URL)
        browser.close()


def test_linkedin_adapter_extracts_public_job_page_using_recipe() -> None:
    adapter = LinkedInAdapter()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        _serve_fixture(page, LINKEDIN_URL, FIXTURES / "linkedin" / "job_page.html")

        job = adapter.scrape_job(page, LINKEDIN_URL)

        assert isinstance(adapter, BoardAdapter)
        assert job == Job(
            url=LINKEDIN_URL,
            title="Python Engineer",
            company="Example Company",
            description="Design and maintain reliable Python services.",
            location="Sofia, Bulgaria",
            employment_type="Full-time",
            date_text="2 weeks ago",
        )
        browser.close()


def test_linkedin_adapter_discovers_and_deduplicates_regional_job_links() -> None:
    adapter = LinkedInAdapter()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        _serve_fixture(
            page,
            LINKEDIN_LISTING_URL,
            FIXTURES / "linkedin" / "listing_page.html",
        )

        urls = adapter.discover_listing_urls(
            page,
            LINKEDIN_LISTING_URL,
            known_urls={
                "https://linkedin.com/jobs/view/data-engineer-4487158439"
            },
        )

        assert urls == [
            "https://linkedin.com/jobs/view/python-engineer-at-example-4487158438"
        ]
        browser.close()


def test_default_registry_resolves_linkedin_regional_hosts() -> None:
    registry = create_default_registry()

    assert registry.for_url(LINKEDIN_URL) is registry.get("linkedin")
    assert (
        registry.for_url("https://bg.linkedin.com/jobs/view/4487158438")
        is registry.get("linkedin")
    )
