"""Reusable, validated CSS-selector extraction recipes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping

from playwright.sync_api import Page

from job_agent.models import Job


@dataclass(frozen=True)
class ExtractionRecipe:
    """Board-specific selectors learned from a representative job page."""

    title: str
    company: str
    description: str
    location: str = ""
    employment_type: str = ""
    work_model: str = ""
    tags: str = ""
    date_text: str = ""

    def __post_init__(self) -> None:
        for field_name in ("title", "company", "description"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"Extraction recipe requires a {field_name} selector")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ExtractionRecipe:
        """Create a recipe from a decoded recipe JSON object."""
        allowed = set(cls.__dataclass_fields__)
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Unknown extraction recipe fields: {', '.join(sorted(unknown))}")
        if any(not isinstance(value, str) for value in data.values()):
            raise ValueError("Extraction recipe selectors must be strings")
        try:
            return cls(**dict(data))
        except TypeError as error:
            raise ValueError(f"Invalid extraction recipe: {error}") from error

    def to_mapping(self) -> dict[str, str]:
        """Return a JSON-serializable representation suitable for storage."""
        return asdict(self)


class RecipeAdapter:
    """Apply one reusable selector recipe to the currently loaded page."""

    def __init__(self, recipe: ExtractionRecipe) -> None:
        self.recipe = recipe

    def extract_job(self, page: Page, url: str) -> Job:
        """Extract a job from a page after its navigation has completed."""
        title = self._required_text(page, self.recipe.title, "title")
        company = self._required_text(page, self.recipe.company, "company")
        description = self._required_text(
            page, self.recipe.description, "description"
        )
        date_text = self._optional_text(page, self.recipe.date_text)
        return Job(
            url=url,
            title=title,
            company=company,
            description=description,
            location=self._optional_text(page, self.recipe.location),
            employment_type=self._optional_text(page, self.recipe.employment_type),
            work_model=self._optional_text(page, self.recipe.work_model),
            tags=self._optional_texts(page, self.recipe.tags),
            date_text=date_text,
            date_published=self._date_iso(date_text),
        )

    @classmethod
    def _required_text(cls, page: Page, selector: str, field: str) -> str:
        value = cls._optional_text(page, selector)
        if not value:
            raise ValueError(f"Extraction recipe did not find required {field}")
        return value

    @staticmethod
    def _optional_text(page: Page, selector: str) -> str:
        if not selector:
            return ""
        locator = page.locator(selector).first
        if locator.count() == 0:
            return ""
        return locator.inner_text().strip()

    @staticmethod
    def _optional_texts(page: Page, selector: str) -> list[str]:
        if not selector:
            return []
        return [
            text.strip()
            for text in page.locator(selector).all_inner_texts()
            if text.strip()
        ]

    @staticmethod
    def _date_iso(value: str) -> str:
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return ""
