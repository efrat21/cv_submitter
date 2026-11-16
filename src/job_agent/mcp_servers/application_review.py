"""M4 application review packet and human decision persistence."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from job_agent.database import JobDatabase
from job_agent.mcp_servers._workflow_common import load_job


_HUMAN_ACTIONS = {"APPLIED", "SKIPPED"}


def get_application_review(job_url: str, db: JobDatabase) -> dict[str, Any]:
    """Build a review packet without changing job or application state."""
    job = load_job(db, job_url)
    row = db.connection.execute(
        """
        SELECT verdict, guardrail_overrides, rationale, confidence,
               details_json, cover_letter_path, decided_at
        FROM job_decisions
        WHERE job_url = ?
        """,
        (job_url,),
    ).fetchone()
    decision: dict[str, Any] | None = None
    letter_path = ""
    letter_content = ""
    if row is not None:
        try:
            overrides = json.loads(row[1] or "[]")
            details = json.loads(row[4] or "{}")
        except json.JSONDecodeError as error:
            raise ValueError(f"Stored review data is invalid JSON for {job_url}") from error
        decision = {
            "verdict": row[0],
            "guardrail_overrides": overrides,
            "rationale": row[2],
            "confidence": row[3],
            "details": details,
            "decided_at": row[6],
        }
        letter_path = row[5] or ""
        if letter_path:
            path = Path(letter_path)
            if path.is_file():
                letter_content = path.read_text(encoding="utf-8")

    return {
        "job": job.to_dict(),
        "agent_decision": decision,
        "cover_letter_path": letter_path,
        "cover_letter": letter_content,
        "current_action": db.get_action(job_url),
        "application_submitted_by_tool": False,
        "human_review_required": True,
    }


def record_human_application_review(
    job_url: str,
    action: str,
    db: JobDatabase,
    *,
    confirmed: bool,
    note: str = "",
) -> dict[str, Any]:
    """Persist an explicit human APPLIED/SKIPPED action for feedback."""
    normalized_action = action.strip().upper()
    if normalized_action not in _HUMAN_ACTIONS:
        raise ValueError("Human review action must be APPLIED or SKIPPED")
    if not confirmed:
        raise ValueError("Human confirmation is required to record this review")
    if not db.record_action(job_url, normalized_action, note.strip() or None):
        raise ValueError(f"Cannot record review for unknown job: {job_url}")

    reference = f"human-review:{uuid.uuid4()}"
    db.record_audit_event(
        "application.reviewed",
        actor="human",
        tool_name="job-agent.record_application_review",
        details={
            "job_url": job_url,
            "action": normalized_action,
            "note": note.strip(),
            "application_submitted_by_tool": False,
        },
        approval_required=True,
        approved=True,
        approval_reference=reference,
    )
    return {
        "job_url": job_url,
        "action": normalized_action,
        "note": note.strip(),
        "human_confirmed": True,
        "application_submitted_by_tool": False,
        "approval_reference": reference,
    }
