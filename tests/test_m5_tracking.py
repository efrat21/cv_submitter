from __future__ import annotations

import asyncio
import base64
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from job_agent.daily_digest import build_daily_digest
from job_agent.database import JobDatabase
from job_agent.mcp_servers import tracking_host
from job_agent.mcp_servers import host as workflow_host
from job_agent.mcp_servers.calendar import confirm_interview_event
from job_agent.tracking.email_classifier import classify_email
from job_agent.tracking.email_sync import sync_gmail
from job_agent.tracking.gmail_client import GmailClient
from job_agent.tracking.interview_extractor import extract_interview_proposal
from job_agent.tracking.matcher import match_email_to_job


JOB_URL = "https://jobs.example/jobs/python-engineer"


def _database(tmp_path) -> JobDatabase:
    db = JobDatabase(tmp_path / "jobs.db")
    db.save_job(
        {
            "url": JOB_URL,
            "title": "Python Engineer",
            "company": "Acme",
            "description": "Python role",
            "tags": ["Python"],
        }
    )
    db.record_action(JOB_URL, "APPLIED")
    return db


class FakeMessageClient:
    def __init__(self, messages):
        self.messages = messages
        self.arguments = None

    def list_recent_messages(self, *, max_results=100, query="newer_than:30d"):
        self.arguments = (max_results, query)
        return self.messages


class FakeCalendar:
    def __init__(self, conflicts=None):
        self.conflicts = conflicts or []
        self.created = []

    def find_conflicts(self, start, end, timezone_name):
        return self.conflicts

    def create_event(self, event_id, event):
        self.created.append((event_id, event))
        return {"id": event_id}


def _proposal(db: JobDatabase, *, status="pending_confirmation") -> int:
    return db.save_interview_proposal(
        {
            "job_url": JOB_URL,
            "email_message_id": "mail-1",
            "scheduled_for": "2026-11-18T14:30",
            "timezone": "Europe/Sofia",
            "interview_format": "Google Meet",
            "meeting_link": "https://meet.example/room",
            "contact_person": "recruiter@acme.example",
            "event_title": "Interview: Acme - Python Engineer",
            "status": status,
        }
    )


def test_email_classification_is_local_and_prioritizes_offer() -> None:
    assert classify_email("Interview", "We would like to schedule an interview") == "interview"
    assert classify_email("Good news", "We are pleased to offer you the role") == "offer"
    assert classify_email("Update", "We decided to proceed with another candidate") == "rejection"
    assert classify_email("Thanks", "Your application has been received") == "acknowledgement"
    assert classify_email("Hello", "Please see the attached file") == "other"


def test_interview_extractor_leaves_missing_date_and_timezone_explicit() -> None:
    parsed = extract_interview_proposal(
        "Interview",
        "Can we meet on November 18, 2026 at 2:30 PM EET? Google Meet https://meet.example/abc",
        sender="Recruiter <recruiter@acme.example>",
    )
    assert parsed["scheduled_for"] == "2026-11-18T14:30"
    assert parsed["timezone"] == "Europe/Sofia"
    assert parsed["meeting_link"] == "https://meet.example/abc"
    assert parsed["contact_person"] == "Recruiter"

    incomplete = extract_interview_proposal("Interview", "Let's find a time next week")
    assert incomplete["scheduled_for"] is None
    assert incomplete["timezone"] == ""

    european = extract_interview_proposal(
        "Interview",
        "18 November 2026, Time: 14:30",
        today=datetime(2026, 11, 16).date(),
    )
    assert european["scheduled_for"] == "2026-11-18T14:30"


def test_email_matching_requires_application_and_disambiguates(tmp_path) -> None:
    db = _database(tmp_path)
    try:
        assert match_email_to_job(
            "recruiter@acme.example",
            "Interview for Python Engineer",
            "Let's talk about the Python Engineer role at Acme.",
            db,
        ) == (JOB_URL, 100)

        db.save_job(
            {
                "url": "https://jobs.example/jobs/other",
                "title": "Python Engineer",
                "company": "Acme",
                "description": "Another role",
            }
        )
        db.record_action("https://jobs.example/jobs/other", "APPLIED")
        assert match_email_to_job(
            "recruiter@acme.example", "Interview", "Let's talk.", db
        ) == (None, None)
    finally:
        db.close()


def test_gmail_sync_persists_metadata_and_pending_interview_only(tmp_path) -> None:
    db = _database(tmp_path)
    message = {
        "message_id": "gmail-123",
        "thread_id": "thread-1",
        "sender": "Recruiter <recruiter@acme.example>",
        "subject": "Interview: Python Engineer",
        "received_at": "2026-11-16T08:00:00+00:00",
        "snippet": "Let's speak on November 18, 2026 at 2:30 PM EET.",
        "text": (
            "We would like to schedule an interview for the Python Engineer "
            "role at Acme on November 18, 2026 at 2:30 PM EET."
        ),
    }
    client = FakeMessageClient([message, message])
    try:
        result = sync_gmail(db, client=client, max_results=25)
        assert result["synced"] == 2
        assert result["gmail_modified"] is False
        assert client.arguments == (25, "newer_than:30d -in:trash -in:spam")
        assert len(db.get_tracked_emails()) == 1
        tracked = db.get_tracked_emails()[0]
        assert tracked["classification"] == "interview"
        assert tracked["matched_job_url"] == JOB_URL
        assert tracked["raw_snippet"] == message["snippet"]
        assert tracked["raw_snippet"] != message["text"]
        proposals = db.list_interviews()
        assert len(proposals) == 1
        assert proposals[0]["status"] == "pending_confirmation"
        assert proposals[0]["confirmed"] == 0
    finally:
        db.close()


def test_gmail_api_client_uses_read_only_list_and_get_calls() -> None:
    encoded = base64.urlsafe_b64encode(
        b"We would like to schedule an interview."
    ).decode().rstrip("=")
    calls = []

    class Request:
        def __init__(self, value):
            self.value = value

        def execute(self):
            return self.value

    class Messages:
        def list(self, **kwargs):
            calls.append(("list", kwargs))
            return Request({"messages": [{"id": "m1"}]})

        def get(self, **kwargs):
            calls.append(("get", kwargs))
            return Request(
                {
                    "id": "m1",
                    "threadId": "t1",
                    "internalDate": "1794816000000",
                    "snippet": "interview snippet",
                    "payload": {
                        "mimeType": "text/plain",
                        "headers": [
                            {"name": "From", "value": "Recruiter <r@example.com>"},
                            {"name": "Subject", "value": "Interview"},
                        ],
                        "body": {"data": encoded},
                    },
                }
            )

    class Users:
        def messages(self):
            return Messages()

    class Service:
        def users(self):
            return Users()

    messages = GmailClient(service=Service()).list_recent_messages(max_results=4)
    assert len(messages) == 1
    assert messages[0]["text"] == "We would like to schedule an interview."
    assert messages[0]["sender"] == "Recruiter <r@example.com>"
    assert calls == [
        ("list", {"userId": "me", "q": "newer_than:30d -in:trash -in:spam", "maxResults": 4}),
        ("get", {"userId": "me", "id": "m1", "format": "full"}),
    ]


def test_calendar_event_requires_confirmation_and_has_no_attendees(tmp_path) -> None:
    db = _database(tmp_path)
    interview_id = _proposal(db)
    calendar = FakeCalendar()
    try:
        declined = confirm_interview_event(
            interview_id,
            db,
            confirmed=False,
            approval_reference="declined",
            calendar=calendar,
        )
        assert declined["created"] is False
        assert calendar.created == []
        assert db.get_interview(interview_id)["status"] == "pending_confirmation"

        result = confirm_interview_event(
            interview_id,
            db,
            confirmed=True,
            approval_reference="human-confirmed",
            calendar=calendar,
        )
        assert result["status"] == "scheduled"
        event = calendar.created[0][1]
        assert "attendees" not in event
        assert "sendUpdates" not in event
        assert event["start"]["timeZone"] == "Europe/Sofia"
        assert db.get_interview(interview_id)["confirmed"] == 1
        assert db.connection.execute(
            """
            SELECT actor, approval_required, approved, approval_reference
            FROM audit_log WHERE event_type = 'calendar.interview_scheduled'
            """
        ).fetchone() == ("human", 1, 1, "human-confirmed")
        repeated = confirm_interview_event(
            interview_id,
            db,
            confirmed=True,
            approval_reference="second-confirmation",
            calendar=calendar,
        )
        assert repeated["already_scheduled"] is True
        assert len(calendar.created) == 1
    finally:
        db.close()


def test_calendar_confirmation_checks_conflicts_and_requires_timezone(tmp_path) -> None:
    db = _database(tmp_path)
    interview_id = _proposal(db)
    conflict = {"id": "busy1", "summary": "Existing event", "start": "x", "end": "y"}
    calendar = FakeCalendar([conflict])
    try:
        with pytest.raises(RuntimeError, match="availability changed"):
            confirm_interview_event(
                interview_id,
                db,
                confirmed=True,
                approval_reference="approval",
                expected_conflicts=[],
                calendar=calendar,
            )
        assert calendar.created == []

        result = confirm_interview_event(
            interview_id,
            db,
            confirmed=True,
            approval_reference="approval",
            expected_conflicts=["busy1"],
            calendar=calendar,
        )
        assert result["conflicts"] == [conflict]

        incomplete_id = db.save_interview_proposal(
            {
                "email_message_id": "mail-2",
                "event_title": "Interview",
                "status": "needs_details",
            }
        )
        with pytest.raises(ValueError, match="IANA timezone"):
            confirm_interview_event(
                incomplete_id,
                db,
                confirmed=True,
                approval_reference="approval",
                scheduled_for="2026-11-18T14:30",
                calendar=FakeCalendar(),
            )
    finally:
        db.close()


def test_cancelled_mcp_confirmation_does_not_write_calendar(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _database(tmp_path)
    interview_id = db.save_interview_proposal(
        {
            "email_message_id": "cancelled-proposal",
            "event_title": "Interview",
            "status": "needs_details",
        }
    )
    monkeypatch.setattr(tracking_host, "_open_db", lambda: JobDatabase(db.path))

    class CancelledContext:
        async def elicit(self, message, schema):
            assert "no attendees" in message
            return SimpleNamespace(action="cancel", data=None)

    try:
        result = asyncio.run(
            tracking_host.confirm_interview_calendar_event(
                interview_id, CancelledContext()
            )
        )
        assert result["calendar_write_performed"] is False
        assert db.get_interview(interview_id)["status"] == "needs_details"
        assert db.connection.execute(
            """
            SELECT approved FROM audit_log
            WHERE event_type = 'calendar.interview_confirmation_cancelled'
            """
        ).fetchone() == (0,)
    finally:
        db.close()


def test_daily_digest_is_local_and_includes_pending_and_upcoming(tmp_path) -> None:
    db = _database(tmp_path)
    now = datetime(2026, 11, 16, 10, 0, tzinfo=ZoneInfo("Europe/Sofia"))
    db.save_tracked_email(
        {
            "message_id": "digest-email",
            "subject": "Application received",
            "classification": "acknowledgement",
            "received_at": now.astimezone(ZoneInfo("UTC")).isoformat(),
            "snippet": "Thanks for applying",
            "matched_job_url": JOB_URL,
        }
    )
    _proposal(db)
    scheduled_id = db.save_interview_proposal(
        {
            "email_message_id": "digest-scheduled",
            "scheduled_for": "2026-11-18T14:30",
            "timezone": "Europe/Sofia",
            "event_title": "Interview: Acme",
            "status": "pending_confirmation",
        }
    )
    db.record_scheduled_interview(
        scheduled_id,
        scheduled_for="2026-11-18T14:30",
        timezone_name="Europe/Sofia",
        duration_minutes=60,
        calendar_event_id="evt1",
        approval_reference="human",
    )
    try:
        digest = build_daily_digest(db, now=now)
        assert digest["email_count"] == 1
        assert digest["pending_interview_count"] == 1
        assert digest["upcoming_interview_count"] == 1
        assert digest["delivery"] == "local_only"
        assert "unmatched" not in digest["text"]
    finally:
        db.close()


def test_tracking_mcp_tools_register() -> None:
    from job_agent.mcp_servers.tracking_host import mcp

    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "sync_application_emails",
        "get_tracked_application_emails",
        "get_pending_interview_proposals",
        "confirm_interview_calendar_event",
        "get_daily_application_digest",
    }


def test_workflow_and_tracking_servers_share_existing_database_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing_db_path = tmp_path / "existing-jobs.db"
    monkeypatch.delenv("JOB_AGENT_DB_PATH", raising=False)
    monkeypatch.setattr(workflow_host, "DEFAULT_DB_PATH", existing_db_path)
    monkeypatch.setattr(tracking_host, "DEFAULT_DB_PATH", existing_db_path)

    workflow_db = workflow_host._open_db()
    tracking_db = tracking_host._open_db()
    try:
        assert workflow_db.path == existing_db_path
        assert tracking_db.path == existing_db_path
    finally:
        workflow_db.close()
        tracking_db.close()


def test_legacy_email_and_interview_tables_are_migrated(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE emails (
            id INTEGER PRIMARY KEY,
            message_id TEXT NOT NULL UNIQUE,
            thread_id TEXT,
            job_url TEXT,
            sender TEXT,
            subject TEXT,
            classification TEXT,
            received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            raw_snippet TEXT
        );
        CREATE TABLE interviews (
            id INTEGER PRIMARY KEY,
            application_id INTEGER,
            job_url TEXT,
            scheduled_for TEXT,
            timezone TEXT,
            interview_format TEXT,
            meeting_link TEXT,
            contact_person TEXT,
            calendar_event_id TEXT,
            confirmed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    connection.close()

    db = JobDatabase(db_path)
    try:
        email_columns = {
            row[1] for row in db.connection.execute("PRAGMA table_info(emails)")
        }
        interview_columns = {
            row[1] for row in db.connection.execute("PRAGMA table_info(interviews)")
        }
        assert {"matched_job_url", "match_confidence"} <= email_columns
        assert {
            "email_message_id",
            "event_title",
            "location",
            "duration_minutes",
            "status",
            "approval_reference",
        } <= interview_columns
        db.save_tracked_email(
            {
                "message_id": "after-migration",
                "subject": "Application received",
                "classification": "acknowledgement",
                "matched_job_url": JOB_URL,
            }
        )
        assert db.get_tracked_emails()[0]["message_id"] == "after-migration"
    finally:
        db.close()
