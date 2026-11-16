from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from job_agent.config import DEFAULT_DB_PATH
from job_agent.database import JobDatabase

mcp = MCPServer("jobs-db")


def _open_db() -> JobDatabase:
    path = os.environ.get("JOB_AGENT_DB_PATH")
    db_path = Path(path) if path else DEFAULT_DB_PATH
    return JobDatabase(db_path)


@mcp.tool()
def db_stats() -> dict[str, Any]:
    """Return a quick summary of the tracked jobs and decisions."""
    db = _open_db()
    try:
        total_jobs = db.count_jobs()
        reviewed = db.connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE action IS NOT NULL AND action != ''"
        ).fetchone()[0]
        recent_feedback = db.get_feedback_history(limit=10)
        return {
            "database_path": str(db.path),
            "total_jobs": total_jobs,
            "reviewed_jobs": reviewed,
            "recent_feedback": recent_feedback,
        }
    finally:
        db.close()


@mcp.tool()
def list_jobs(limit: int = 25, action: str | None = None) -> list[dict[str, Any]]:
    """List jobs, optionally filtered by an existing action state."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    db = _open_db()
    try:
        jobs = db.list_jobs(limit=limit, action=action)
        return [
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "company": row.get("company"),
                "location": row.get("location"),
                "work_model": row.get("work_model"),
                "url": row.get("url"),
                "action": row.get("action"),
                "action_at": row.get("action_at"),
            }
            for row in jobs
        ]
    finally:
        db.close()


@mcp.tool()
def get_job(url: str) -> dict[str, Any] | None:
    """Fetch one job by URL including the raw fields already stored in the legacy jobs table."""
    db = _open_db()
    try:
        row = db.connection.execute(
            "SELECT * FROM jobs WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return None
        columns = [c[0] for c in db.connection.execute("SELECT * FROM jobs LIMIT 0").description]
        return dict(zip(columns, row))
    finally:
        db.close()


@mcp.tool()
def get_feedback_history(limit: int = 10) -> list[dict[str, Any]]:
    """Return my own decision history (APPLIED / SKIPPED), newest first."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    db = _open_db()
    try:
        return db.get_feedback_history(limit=limit)
    finally:
        db.close()


@mcp.tool()
def get_recent_audit(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent audit log entries for tool calls and approvals."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    db = _open_db()
    try:
        rows = db.get_audit_events(limit=limit)
        parsed: list[dict[str, Any]] = []
        for row in rows:
            payload = row.get("details_json")
            try:
                parsed_payload = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                parsed_payload = {"raw": payload}
            parsed.append({
                "timestamp": row.get("timestamp"),
                "actor": row.get("actor"),
                "event_type": row.get("event_type"),
                "tool_name": row.get("tool_name"),
                "details": parsed_payload,
                "approval_required": bool(row.get("approval_required")),
                "approved": bool(row.get("approved")),
                "approval_reference": row.get("approval_reference"),
            })
        return parsed
    finally:
        db.close()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
