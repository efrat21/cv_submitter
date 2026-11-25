"""Local-only daily digest for tracked application email and interviews."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from job_agent.config import DEFAULT_DB_PATH
from job_agent.database import JobDatabase
from job_agent.tracking.scheduler import pending_interview_proposals, upcoming_interviews


def build_daily_digest(
    db: JobDatabase,
    *,
    now: datetime | None = None,
    upcoming_days: int = 7,
) -> dict[str, Any]:
    """Build a digest for local viewing; this function never sends email."""
    local_now = now or datetime.now().astimezone()
    today = local_now.date()
    today_emails = []
    for email in db.get_tracked_emails(limit=500):
        try:
            received = datetime.fromisoformat(email["received_at"])
        except (TypeError, ValueError):
            continue
        if received.tzinfo is None:
            received = received.replace(tzinfo=local_now.tzinfo)
        if received.astimezone(local_now.tzinfo).date() == today:
            today_emails.append(email)

    pending = pending_interview_proposals(db, limit=500)
    upcoming = upcoming_interviews(
        db, now=local_now, days=upcoming_days, limit=500
    )
    lines = [
        f"Daily application digest — {today.isoformat()}",
        "",
        f"Email updates today: {len(today_emails)}",
    ]
    for email in today_emails:
        company_ref = email.get("matched_job_url") or email.get("job_url")
        lines.append(
            f"- [{email['classification']}] {email.get('subject') or '(no subject)'}"
            + (f" — {company_ref}" if company_ref else " — unmatched")
        )
    lines.extend(["", f"Interview proposals needing review: {len(pending)}"])
    for proposal in pending:
        when = proposal.get("scheduled_for") or "date/time needs details"
        zone = proposal.get("timezone") or "timezone needs confirmation"
        lines.append(
            f"- #{proposal['id']} {proposal.get('event_title') or 'Job interview'}"
            f" — {when} {zone} [{proposal['status']}]"
        )
    lines.extend(["", f"Confirmed interviews in the next {upcoming_days} days: {len(upcoming)}"])
    for interview in upcoming:
        lines.append(
            f"- {interview.get('scheduled_for')} {interview.get('timezone')}: "
            f"{interview.get('event_title') or 'Job interview'}"
        )
    return {
        "date": today.isoformat(),
        "email_count": len(today_emails),
        "pending_interview_count": len(pending),
        "upcoming_interview_count": len(upcoming),
        "emails": today_emails,
        "pending_interviews": pending,
        "upcoming_interviews": upcoming,
        "text": "\n".join(lines),
        "delivery": "local_only",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the local application-tracking digest.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--upcoming-days", type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.upcoming_days <= 90:
        parser.error("--upcoming-days must be between 1 and 90")
    db = JobDatabase(args.db)
    try:
        print(build_daily_digest(db, upcoming_days=args.upcoming_days)["text"])
    finally:
        db.close()


if __name__ == "__main__":
    main()
