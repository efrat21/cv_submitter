"""MCP-service helpers for local email tracking."""

from __future__ import annotations

from typing import Any

from job_agent.database import JobDatabase
from job_agent.tracking.email_sync import MessageClient, sync_gmail as run_gmail_sync
from job_agent.tracking.gmail_client import GmailClient


def sync_application_emails(
    db: JobDatabase,
    *,
    client: MessageClient | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    gmail = client or GmailClient()
    result = run_gmail_sync(db, client=gmail, max_results=max_results)
    db.record_audit_event(
        "email.sync_completed",
        tool_name="job-agent.sync_application_emails",
        details={
            "messages_synced": result["synced"],
            "interview_proposals": len(result["interview_proposals"]),
            "gmail_modified": False,
        },
    )
    return result


def list_application_emails(
    db: JobDatabase, *, limit: int = 100
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    return db.get_tracked_emails(limit=limit)
