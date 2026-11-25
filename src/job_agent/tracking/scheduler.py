"""Queries for pending and upcoming interview proposals."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from job_agent.database import JobDatabase


def pending_interview_proposals(
    db: JobDatabase, *, limit: int = 100
) -> list[dict[str, Any]]:
    return [
        proposal
        for proposal in db.list_interviews(limit=limit)
        if proposal["status"] in {"needs_details", "pending_confirmation"}
    ]


def upcoming_interviews(
    db: JobDatabase,
    *,
    now: datetime | None = None,
    days: int = 14,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if days < 1 or days > 90:
        raise ValueError("days must be between 1 and 90")
    current = now or datetime.now().astimezone()
    end = current + timedelta(days=days)
    upcoming = []
    for interview in db.list_interviews(status="scheduled", limit=limit):
        scheduled_for = interview.get("scheduled_for")
        if not scheduled_for:
            continue
        try:
            start = datetime.fromisoformat(scheduled_for)
        except ValueError:
            continue
        timezone_name = interview.get("timezone")
        if start.tzinfo is None and timezone_name:
            from zoneinfo import ZoneInfo

            start = start.replace(tzinfo=ZoneInfo(timezone_name))
        if start.tzinfo is None:
            continue
        if current <= start <= end:
            upcoming.append(interview)
    return upcoming
