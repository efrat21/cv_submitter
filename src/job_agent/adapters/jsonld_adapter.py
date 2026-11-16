"""Schema.org JobPosting extraction."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any

from playwright.sync_api import Page

from job_agent.models import Job


class _DescriptionParser(HTMLParser):
    """Convert HTML descriptions to readable text while preserving paragraphs."""

    _BLOCK_TAGS = {
        "address",
        "br",
        "div",
        "li",
        "ol",
        "p",
        "section",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        del _attrs
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class JsonLdAdapter:
    """Extract Job records from one or more JSON-LD script blocks."""

    def extract_job(self, page: Page, url: str) -> Job | None:
        """Return a JobPosting from the current page, if one is present."""
        for raw_json in page.locator('script[type="application/ld+json"]').all_text_contents():
            try:
                document = json.loads(raw_json)
            except json.JSONDecodeError:
                continue
            posting = self._find_job_posting(document)
            if posting is not None:
                return self._to_job(posting, url)
        return None

    @classmethod
    def _find_job_posting(cls, value: Any) -> dict[str, Any] | None:
        if isinstance(value, list):
            for item in value:
                posting = cls._find_job_posting(item)
                if posting is not None:
                    return posting
        elif isinstance(value, dict):
            types = value.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if any(str(item).rsplit("/", 1)[-1] == "JobPosting" for item in types):
                return value
            for item in value.values():
                posting = cls._find_job_posting(item)
                if posting is not None:
                    return posting
        return None

    @classmethod
    def _to_job(cls, posting: dict[str, Any], url: str) -> Job:
        title = cls._as_text(posting.get("title") or posting.get("name"))
        organization = posting.get("hiringOrganization")
        company = cls._as_text(organization)
        description = cls._html_to_text(cls._as_text(posting.get("description")))
        if not title or not company or not description:
            missing = [
                name
                for name, value in (
                    ("title", title),
                    ("hiringOrganization.name", company),
                    ("description", description),
                )
                if not value
            ]
            raise ValueError(f"JobPosting JSON-LD is missing required fields: {', '.join(missing)}")

        date_text = cls._as_text(posting.get("datePosted"))
        return Job(
            url=url,
            title=title,
            company=company,
            description=description,
            location=cls._location(posting.get("jobLocation")),
            employment_type=", ".join(cls._as_texts(posting.get("employmentType"))),
            requirements=cls._as_lines(
                posting.get("qualifications") or posting.get("experienceRequirements")
            ),
            benefits=cls._as_lines(posting.get("jobBenefits")),
            tags=cls._as_texts(posting.get("skills")),
            date_text=date_text,
            date_published=cls._date_iso(date_text),
        )

    @classmethod
    def _location(cls, value: Any) -> str:
        locations = value if isinstance(value, list) else [value]
        result: list[str] = []
        for location in locations:
            if not isinstance(location, dict):
                text = cls._as_text(location)
                if text and text not in result:
                    result.append(text)
                continue
            address = location.get("address")
            if isinstance(address, dict):
                parts = [
                    cls._as_text(address.get(key))
                    for key in ("addressLocality", "addressRegion", "addressCountry")
                ]
                text = ", ".join(part for part in parts if part)
            else:
                text = cls._as_text(address or location.get("name"))
            if text and text not in result:
                result.append(text)
        return "; ".join(result)

    @classmethod
    def _as_text(cls, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return cls._as_text(value.get("name") or value.get("text") or value.get("value"))
        if isinstance(value, (int, float)):
            return str(value)
        return ""

    @classmethod
    def _as_texts(cls, value: Any) -> list[str]:
        values = value if isinstance(value, list) else [value]
        result: list[str] = []
        for item in values:
            text = cls._as_text(item)
            if text and text not in result:
                result.append(text)
        return result

    @classmethod
    def _as_lines(cls, value: Any) -> list[str]:
        texts = cls._as_texts(value)
        lines: list[str] = []
        for text in texts:
            parsed = cls._html_to_text(text)
            for line in parsed.splitlines():
                cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
                if cleaned and cleaned not in lines:
                    lines.append(cleaned)
        return lines

    @staticmethod
    def _html_to_text(value: str) -> str:
        parser = _DescriptionParser()
        parser.feed(value)
        parser.close()
        text = re.sub(r"[ \t]+\n", "\n", "".join(parser.parts))
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def _date_iso(value: str) -> str:
        if not value:
            return ""
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                return ""
