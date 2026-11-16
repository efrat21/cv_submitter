"""Shared local configuration and job loading for workflow tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from job_agent.config import DATA_DIR
from job_agent.database import JobDatabase
from job_agent.models import Job


def load_profile() -> dict[str, Any]:
    path = Path(os.environ.get("JOB_AGENT_PROFILE_PATH", DATA_DIR / "candidate_profile.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def load_preferences() -> dict[str, Any]:
    path = Path(
        os.environ.get(
            "JOB_AGENT_PREFERENCES_PATH",
            DATA_DIR / "candidate_preferences.json",
        )
    )
    return json.loads(path.read_text(encoding="utf-8"))


def load_job(db: JobDatabase, url: str) -> Job:
    row = db.connection.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
    if row is None:
        raise ValueError(f"Job is not stored in the database: {url}")
    columns = [
        column[0]
        for column in db.connection.execute("SELECT * FROM jobs LIMIT 0").description
    ]
    data = dict(zip(columns, row))
    tags_json = data.pop("tags_json", None)
    if tags_json:
        tags = json.loads(tags_json)
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError(f"Stored job tags must be a JSON string list: {url}")
    else:
        tags = []
    data["tags"] = tags
    return Job.from_dict(data)
