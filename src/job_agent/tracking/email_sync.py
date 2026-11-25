"""Read-only Gmail synchronization into the local tracking database."""

from __future__ import annotations

from typing import Any, Protocol

from job_agent.database import JobDatabase
from job_agent.tracking.email_classifier import classify_email
from job_agent.tracking.interview_extractor import extract_interview_proposal
from job_agent.tracking.matcher import match_email_to_job


class MessageClient(Protocol):
    def list_recent_messages(
        self, *, max_results: int = 100, query: str = "newer_than:30d"
    ) -> list[dict[str, Any]]: ...


def sync_gmail(
    db: JobDatabase,
    *,
    client: MessageClient,
    max_results: int = 100,
    query: str = "newer_than:30d -in:trash -in:spam",
) -> dict[str, Any]:
    """Classify and persist recent messages; never mark, move, or send messages."""
    messages = client.list_recent_messages(max_results=max_results, query=query)
    proposals: list[dict[str, Any]] = []
    for message in messages:
        message_id = str(message["message_id"])
        subject = str(message.get("subject", ""))
        text = str(message.get("text", ""))
        sender = str(message.get("sender", ""))
        classification = classify_email(subject, text)
        job_url, confidence = match_email_to_job(sender, subject, text, db)
        db.save_tracked_email(
            {
                **message,
                "message_id": message_id,
                "classification": classification,
                "matched_job_url": job_url,
                "match_confidence": confidence,
            }
        )
        if classification != "interview":
            continue

        extracted = extract_interview_proposal(subject, text, sender=sender)
        job_title = ""
        company = ""
        if job_url:
            row = db.connection.execute(
                "SELECT title, company FROM jobs WHERE url = ?", (job_url,)
            ).fetchone()
            if row:
                job_title, company = row
        is_schedulable = bool(extracted["scheduled_for"])
        proposal = {
            "job_url": job_url,
            "email_message_id": message_id,
            **extracted,
            "event_title": (
                f"Interview: {company} - {job_title}"
                if job_title
                else f"Interview: {subject or company or 'Job application'}"
            ),
            "status": "pending_confirmation" if is_schedulable else "needs_details",
        }
        interview_id = db.save_interview_proposal(proposal)
        persisted_proposal = db.get_interview(interview_id)
        if persisted_proposal is None:
            raise RuntimeError(
                f"Interview proposal disappeared after saving: {interview_id}"
            )
        proposals.append(persisted_proposal)

    return {
        "synced": len(messages),
        "interview_proposals": proposals,
        "gmail_modified": False,
    }
