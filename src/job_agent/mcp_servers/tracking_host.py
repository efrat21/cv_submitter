"""MCP tools for read-only email tracking and confirmed calendar writes."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel, Field

from job_agent.config import DEFAULT_DB_PATH
from job_agent.daily_digest import build_daily_digest
from job_agent.database import JobDatabase
from job_agent.mcp_servers.calendar import (
    confirm_interview_event as schedule_confirmed_interview,
    list_interview_proposals as get_pending_interviews,
    preview_interview_event,
)
from job_agent.mcp_servers.email_tracker import (
    list_application_emails,
    sync_application_emails as run_email_sync,
)

mcp = MCPServer(
    "job-agent-tracking",
    instructions=(
        "Email sync is read-only. Interview proposals are not added to a calendar "
        "until the human reviews and confirms them through elicitation. Calendar "
        "events have no attendees and do not send invitations. The daily digest "
        "is local output only; it is never emailed."
    ),
)


class InterviewConfirmation(BaseModel):
    confirmed: bool = Field(
        description="Confirm after reviewing the proposal and any calendar conflicts."
    )
    scheduled_for: str | None = Field(
        default=None,
        description="Optional corrected local ISO date-time, e.g. 2026-11-17T14:00.",
    )
    timezone: str | None = Field(
        default=None,
        description="Optional IANA timezone, e.g. Europe/Sofia; required if not extracted.",
    )
    duration_minutes: int | None = Field(
        default=None,
        ge=5,
        le=480,
        description="Optional corrected duration in minutes; default proposal is 60.",
    )


class ConflictConfirmation(BaseModel):
    confirmed: bool = Field(
        description="Confirm scheduling despite the newly found calendar conflicts."
    )


def _open_db() -> JobDatabase:
    path = os.environ.get("JOB_AGENT_DB_PATH")
    return JobDatabase(Path(path) if path else DEFAULT_DB_PATH)


@mcp.tool()
def sync_application_emails(max_results: int = 100) -> dict[str, Any]:
    """Fetch recent Gmail messages read-only, classify them, and find interview proposals.

    Requires local Google OAuth setup. Gmail labels and read/unread state are not changed.
    """
    if not 1 <= max_results <= 500:
        raise ValueError("max_results must be between 1 and 500")
    db = _open_db()
    try:
        return run_email_sync(db, max_results=max_results)
    finally:
        db.close()


@mcp.tool()
def get_tracked_application_emails(limit: int = 100) -> list[dict[str, Any]]:
    """List locally tracked email metadata and short snippets."""
    db = _open_db()
    try:
        return list_application_emails(db, limit=limit)
    finally:
        db.close()


@mcp.tool()
def get_pending_interview_proposals(limit: int = 100) -> list[dict[str, Any]]:
    """List interview proposals awaiting human confirmation or missing date/time details."""
    db = _open_db()
    try:
        return get_pending_interviews(db, limit=limit)
    finally:
        db.close()


@mcp.tool()
async def confirm_interview_calendar_event(
    interview_id: int, ctx: Context
) -> dict[str, Any]:
    """Review a proposal and create a private calendar event only after human confirmation.

    No attendees are added, and calendar invitations are not sent.
    """
    db = _open_db()
    try:
        preview = preview_interview_event(interview_id, db)
        proposal = preview["proposal"]
        conflicts = preview["conflicts"]
        prompt = (
            f"Review calendar proposal #{interview_id}: "
            f"{proposal.get('event_title') or 'Job interview'}; "
            f"date/time={proposal.get('scheduled_for') or 'not extracted'}; "
            f"timezone={proposal.get('timezone') or 'not extracted'}; "
            f"duration={proposal.get('duration_minutes') or 60} minutes. "
            f"Conflicts: {conflicts or 'none found'}. "
            "You may supply corrected date/time, IANA timezone, or duration. "
            "Confirming creates one private event with no attendees and sends no invitations. "
            "Declining or cancelling leaves the calendar unchanged."
        )
        response = await ctx.elicit(prompt, InterviewConfirmation)
        if response.action != "accept" or response.data is None:
            db.record_audit_event(
                "calendar.interview_confirmation_cancelled",
                actor="human",
                tool_name="job-agent.confirm_interview_calendar_event",
                details={"interview_id": interview_id, "status": response.action},
                approval_required=True,
                approved=False,
            )
            return {
                "interview_id": interview_id,
                "status": response.action,
                "calendar_write_performed": False,
            }
        confirmation = response.data
        if not confirmation.confirmed:
            db.record_audit_event(
                "calendar.interview_confirmation_declined",
                actor="human",
                tool_name="job-agent.confirm_interview_calendar_event",
                details={"interview_id": interview_id},
                approval_required=True,
                approved=False,
            )
            return {
                "interview_id": interview_id,
                "status": "not_confirmed",
                "calendar_write_performed": False,
            }
        effective_time = confirmation.scheduled_for or proposal.get("scheduled_for")
        effective_timezone = confirmation.timezone or proposal.get("timezone")
        effective_duration = confirmation.duration_minutes or proposal.get(
            "duration_minutes"
        )
        corrected = (
            effective_time != proposal.get("scheduled_for")
            or effective_timezone != proposal.get("timezone")
            or effective_duration != proposal.get("duration_minutes")
        )
        reviewed_conflicts = conflicts
        if corrected:
            corrected_preview = preview_interview_event(
                interview_id,
                db,
                scheduled_for=effective_time,
                timezone_name=effective_timezone,
                duration_minutes=effective_duration,
            )
            reviewed_conflicts = corrected_preview["conflicts"]
            if reviewed_conflicts:
                conflict_response = await ctx.elicit(
                    "The corrected interview time has calendar conflicts: "
                    f"{reviewed_conflicts}. Confirm only if you still want this "
                    "private event created despite those conflicts.",
                    ConflictConfirmation,
                )
                if (
                    conflict_response.action != "accept"
                    or conflict_response.data is None
                    or not conflict_response.data.confirmed
                ):
                    db.record_audit_event(
                        "calendar.interview_conflict_declined",
                        actor="human",
                        tool_name="job-agent.confirm_interview_calendar_event",
                        details={"interview_id": interview_id},
                        approval_required=True,
                        approved=False,
                    )
                    return {
                        "interview_id": interview_id,
                        "status": "conflict_not_confirmed",
                        "calendar_write_performed": False,
                        "conflicts": reviewed_conflicts,
                    }
        approval_reference = f"calendar-confirmation:{uuid.uuid4()}"
        result = schedule_confirmed_interview(
            interview_id,
            db,
            confirmed=True,
            approval_reference=approval_reference,
            scheduled_for=confirmation.scheduled_for,
            timezone_name=confirmation.timezone,
            duration_minutes=confirmation.duration_minutes,
            expected_conflicts=[
                str(
                    item.get("id")
                    or f"{item.get('summary')}|{item.get('start')}|{item.get('end')}"
                )
                for item in reviewed_conflicts
            ],
        )
        return {
            **result,
            "calendar_write_performed": result.get("status") == "scheduled",
        }
    finally:
        db.close()


@mcp.tool()
def get_daily_application_digest(upcoming_days: int = 7) -> dict[str, Any]:
    """Build the local-only daily application email and interview digest; never emails it."""
    if not 1 <= upcoming_days <= 90:
        raise ValueError("upcoming_days must be between 1 and 90")
    db = _open_db()
    try:
        return build_daily_digest(db, upcoming_days=upcoming_days)
    finally:
        db.close()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
