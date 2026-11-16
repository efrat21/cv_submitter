"""LinkedIn public job pages using the generic JSON-LD/recipe pipeline."""

from __future__ import annotations

import re

from job_agent.adapters.generic_adapter import GenericAdapter
from job_agent.adapters.recipe_adapter import ExtractionRecipe


_LINKEDIN_JOB_PATH = re.compile(r"/jobs/view/(?:[^/?#]*-)?\d+/?$", re.IGNORECASE)

_LINKEDIN_JOB_RECIPE = ExtractionRecipe(
    title="h1.top-card-layout__title",
    company="a.topcard__org-name-link",
    description=".description__text",
    location=".topcard__flavor--bullet",
    employment_type=(
        "li.description__job-criteria-item:"
        "has(.description__job-criteria-subheader:text-is('Employment type')) "
        ".description__job-criteria-text"
    ),
    date_text=".posted-time-ago__text",
)


class LinkedInAdapter(GenericAdapter):
    """Extract public LinkedIn job postings without sign-in or bypasses."""

    def __init__(self) -> None:
        super().__init__(
            "linkedin",
            ("linkedin.com",),
            recipe=_LINKEDIN_JOB_RECIPE,
            job_path_pattern=_LINKEDIN_JOB_PATH,
        )
