"""MCP-service helpers for human-confirmed interview calendar events."""

from __future__ import annotations

from typing import Any

from job_agent.database import JobDatabase
from job_agent.tracking.calendar_proposals import (
    CalendarClient,
    GoogleCalendarClient,
    confirm_interview_event as create_confirmed_event,
    interview_conflicts,
)
from job_agent.tracking.scheduler import pending_interview_proposals


def list_interview_proposals(
    db: JobDatabase, *, limit: int = 100
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    return pending_interview_proposals(db, limit=limit)


def preview_interview_event(
    interview_id: int,
    db: JobDatabase,
    *,
    scheduled_for: str | None = None,
    timezone_name: str | None = None,
    duration_minutes: int | None = None,
    calendar: CalendarClient | None = None,
) -> dict[str, Any]:
    proposal = db.get_interview(interview_id)
    if proposal is None:
        raise ValueError(f"Interview proposal not found: {interview_id}")
    conflicts = []
    if proposal.get("scheduled_for") and proposal.get("timezone"):
        conflicts = interview_conflicts(
            proposal,
            calendar or GoogleCalendarClient(),
            scheduled_for=scheduled_for,
            timezone_name=timezone_name,
            duration_minutes=duration_minutes,
        )
    return {"proposal": proposal, "conflicts": conflicts, "write_performed": False}


def confirm_interview_event(
    interview_id: int,
    db: JobDatabase,
    *,
    confirmed: bool,
    approval_reference: str,
    scheduled_for: str | None = None,
    timezone_name: str | None = None,
    duration_minutes: int | None = None,
    expected_conflicts: list[str] | None = None,
    calendar: CalendarClient | None = None,
) -> dict[str, Any]:
    return create_confirmed_event(
        interview_id,
        db,
        calendar or GoogleCalendarClient(),
        confirmed=confirmed,
        approval_reference=approval_reference,
        scheduled_for=scheduled_for,
        timezone_name=timezone_name,
        duration_minutes=duration_minutes,
        expected_conflicts=expected_conflicts,
    )
