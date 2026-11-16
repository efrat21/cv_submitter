import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.job_agent.database import JobDatabase


def test_legacy_jobs_are_preserved_and_seed_advanced_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    db = JobDatabase(db_path)

    db.connection.execute(
        """
        INSERT INTO jobs (
            url, title, company, location, first_seen, last_seen, action, action_note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "https://dev.bg/company/jobads/123",
            "Senior Python Engineer",
            "Acme Tech",
            "Remote",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            "RECOMMENDED",
            "seeded",
        ),
    )
    db.connection.commit()

    db._migrate_advanced_schema()

    assert db.count_jobs() == 1
    assert db.connection.execute(
        "SELECT COUNT(*) FROM sources WHERE board = 'devbg'"
    ).fetchone()[0] == 1
    assert db.connection.execute(
        "SELECT COUNT(*) FROM listings WHERE url = 'https://dev.bg/company/jobads/123'"
    ).fetchone()[0] == 1

    db.record_audit_event(
        "tool.call",
        actor="user",
        tool_name="jobs-db.list_jobs",
        details={"limit": 10, "filter": "recommended"},
        approval_required=True,
        approved=True,
        approval_reference="approval-1",
    )

    assert db.connection.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type = 'tool.call'"
    ).fetchone()[0] == 1
    audit_row = db.connection.execute(
        "SELECT details_json, approval_required, approved, approval_reference FROM audit_log WHERE event_type = 'tool.call'"
    ).fetchone()
    assert 'limit' in audit_row[0]
    assert audit_row[1] == 1
    assert audit_row[2] == 1
    assert audit_row[3] == 'approval-1'

    jobs = db.list_jobs(limit=10)
    assert jobs[0]["url"] == "https://dev.bg/company/jobads/123"

    db.close()
