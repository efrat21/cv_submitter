"""Google Calendar client and confirmation-gated interview event creation."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from job_agent.config import DATA_DIR
from job_agent.database import JobDatabase

CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class CalendarClient(Protocol):
    def find_conflicts(
        self, start: datetime, end: datetime, timezone_name: str
    ) -> list[dict[str, Any]]: ...

    def create_event(
        self, event_id: str, event: dict[str, Any]
    ) -> dict[str, Any]: ...


class GoogleCalendarClient:
    """Calendar API client that never adds attendees or sends invitations."""

    def __init__(self, *, service: Any | None = None, calendar_id: str = "primary"):
        self._service = service
        self.calendar_id = calendar_id

    def _build_service(self) -> Any:
        if self._service is not None:
            return self._service
        credentials_path = Path(
            os.environ.get(
                "JOB_AGENT_GOOGLE_OAUTH_CLIENT",
                DATA_DIR / "google_oauth_client.json",
            )
        )
        token_path = Path(
            os.environ.get(
                "JOB_AGENT_CALENDAR_TOKEN_PATH", DATA_DIR / "calendar_token.json"
            )
        )
        if not credentials_path.is_file():
            raise FileNotFoundError(
                f"Google OAuth client file not found: {credentials_path}"
            )

        credentials = None
        if token_path.is_file():
            credentials = Credentials.from_authorized_user_file(
                str(token_path), [CALENDAR_EVENTS_SCOPE]
            )
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), [CALENDAR_EVENTS_SCOPE]
                )
                credentials = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(credentials.to_json(), encoding="utf-8")

        self._service = build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        )
        return self._service

    def find_conflicts(
        self, start: datetime, end: datetime, timezone_name: str
    ) -> list[dict[str, Any]]:
        zone = ZoneInfo(timezone_name)
        response = (
            self._build_service()
            .events()
            .list(
                calendarId=self.calendar_id,
                timeMin=start.replace(tzinfo=zone).isoformat(),
                timeMax=end.replace(tzinfo=zone).isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            )
            .execute()
        )
        return [
            {
                "id": item.get("id"),
                "summary": item.get("summary", "(untitled event)"),
                "start": item.get("start", {}).get("dateTime")
                or item.get("start", {}).get("date"),
                "end": item.get("end", {}).get("dateTime")
                or item.get("end", {}).get("date"),
            }
            for item in response.get("items", [])
        ]

    def create_event(
        self, event_id: str, event: dict[str, Any]
    ) -> dict[str, Any]:
        service = self._build_service()
        try:
            return (
                service.events()
                .insert(
                    calendarId=self.calendar_id,
                    body={"id": event_id, **event},
                    sendUpdates="none",
                )
                .execute()
            )
        except Exception as error:
            # A deterministic event id makes retries safe after a timeout.
            if getattr(error, "resp", None) is None or error.resp.status != 409:
                raise
            return (
                service.events()
                .get(calendarId=self.calendar_id, eventId=event_id)
                .execute()
            )


def _validated_interval(
    scheduled_for: str,
    timezone_name: str,
    duration_minutes: int,
) -> tuple[datetime, datetime, ZoneInfo]:
    if not 5 <= duration_minutes <= 480:
        raise ValueError("Interview duration must be between 5 and 480 minutes")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"Unknown IANA timezone: {timezone_name}") from error
    try:
        start = datetime.fromisoformat(scheduled_for)
    except ValueError as error:
        raise ValueError("scheduled_for must be an ISO 8601 date-time") from error
    if start.tzinfo is not None:
        start = start.astimezone(zone).replace(tzinfo=None)
    return start, start + timedelta(minutes=duration_minutes), zone


def interview_conflicts(
    proposal: dict[str, Any],
    calendar: CalendarClient,
    *,
    scheduled_for: str | None = None,
    timezone_name: str | None = None,
    duration_minutes: int | None = None,
) -> list[dict[str, Any]]:
    start_text = scheduled_for or proposal.get("scheduled_for")
    zone_name = timezone_name or proposal.get("timezone")
    duration = (
        duration_minutes
        if duration_minutes is not None
        else proposal.get("duration_minutes") or 60
    )
    if not start_text or not zone_name:
        return []
    start, end, _ = _validated_interval(start_text, zone_name, duration)
    return calendar.find_conflicts(start, end, zone_name)


def confirm_interview_event(
    interview_id: int,
    db: JobDatabase,
    calendar: CalendarClient,
    *,
    confirmed: bool,
    approval_reference: str,
    scheduled_for: str | None = None,
    timezone_name: str | None = None,
    duration_minutes: int | None = None,
    expected_conflicts: list[str] | None = None,
) -> dict[str, Any]:
    """Write a calendar event only after an affirmative human confirmation."""
    proposal = db.get_interview(interview_id)
    if proposal is None:
        raise ValueError(f"Interview proposal not found: {interview_id}")
    if proposal["status"] == "scheduled" and proposal["confirmed"]:
        return {
            "interview_id": interview_id,
            "status": "scheduled",
            "calendar_event_id": proposal["calendar_event_id"],
            "already_scheduled": True,
        }
    if proposal["status"] not in {"needs_details", "pending_confirmation"}:
        raise ValueError(f"Interview proposal is not confirmable: {proposal['status']}")
    if not confirmed:
        return {"interview_id": interview_id, "status": "not_confirmed", "created": False}

    start_text = scheduled_for or proposal.get("scheduled_for")
    zone_name = timezone_name or proposal.get("timezone")
    duration = (
        duration_minutes
        if duration_minutes is not None
        else proposal.get("duration_minutes") or 60
    )
    if not start_text or not zone_name:
        raise ValueError(
            "A date/time and IANA timezone must be supplied or confirmed before scheduling"
        )
    start, end, zone = _validated_interval(start_text, zone_name, duration)
    conflicts = calendar.find_conflicts(start, end, zone_name)
    conflict_ids = [
        str(item.get("id") or f"{item.get('summary')}|{item.get('start')}|{item.get('end')}")
        for item in conflicts
    ]
    if expected_conflicts is not None and sorted(conflict_ids) != sorted(
        expected_conflicts
    ):
        raise RuntimeError(
            "Calendar availability changed since review; preview the proposal again before confirming"
        )
    event_id = "job" + hashlib.sha256(
        f"{interview_id}:{start_text}:{zone_name}:{duration}".encode("utf-8")
    ).hexdigest()[:32]
    description_parts = [
        f"Job URL: {proposal['job_url']}" if proposal.get("job_url") else "",
        f"Format: {proposal['interview_format']}"
        if proposal.get("interview_format")
        else "",
        f"Meeting link: {proposal['meeting_link']}"
        if proposal.get("meeting_link")
        else "",
        f"Contact: {proposal['contact_person']}"
        if proposal.get("contact_person")
        else "",
    ]
    event = {
        "summary": proposal.get("event_title") or "Job interview",
        "description": "\n".join(part for part in description_parts if part),
        "start": {
            "dateTime": start.replace(tzinfo=zone).isoformat(),
            "timeZone": zone_name,
        },
        "end": {
            "dateTime": end.replace(tzinfo=zone).isoformat(),
            "timeZone": zone_name,
        },
        "location": proposal.get("location") or "",
    }
    # No attendees are added, so this records a private event without notifying
    # recruiters or sending invitations.
    calendar_event = calendar.create_event(event_id, event)
    recorded = db.record_scheduled_interview(
        interview_id,
        scheduled_for=start.isoformat(timespec="minutes"),
        timezone_name=zone_name,
        duration_minutes=duration,
        calendar_event_id=str(calendar_event.get("id") or event_id),
        approval_reference=approval_reference,
    )
    if not recorded:
        updated_proposal = db.get_interview(interview_id)
        if (
            updated_proposal
            and updated_proposal["status"] == "scheduled"
            and updated_proposal["calendar_event_id"]
        ):
            return {
                "interview_id": interview_id,
                "status": "scheduled",
                "calendar_event_id": updated_proposal["calendar_event_id"],
                "already_scheduled": True,
            }
        raise RuntimeError(
            "Calendar event was created, but the proposal changed before it could be recorded"
        )
    db.record_audit_event(
        "calendar.interview_scheduled",
        actor="human",
        tool_name="job-agent.confirm_interview_event",
        details={
            "interview_id": interview_id,
            "job_url": proposal.get("job_url"),
            "calendar_event_id": calendar_event.get("id") or event_id,
            "conflicts_found": len(conflicts),
            "attendees_added": False,
        },
        approval_required=True,
        approved=True,
        approval_reference=approval_reference,
    )
    return {
        "interview_id": interview_id,
        "status": "scheduled",
        "calendar_event_id": calendar_event.get("id") or event_id,
        "conflicts": conflicts,
        "attendees_added": False,
        "approval_reference": approval_reference,
    }
