"""
Job agent dashboard: shows how many jobs were APPLIED out of all scraped jobs.

Usage:
    python dashboard.py
    python dashboard.py --db data/jobs.db --recent 10
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Display order and descriptions for each action status
STATUS_ORDER = [
    ("APPLIED", "Applied"),
    ("RECOMMENDED", "Recommended (awaiting your decision)"),
    ("SKIPPED", "Skipped by you"),
    ("NOT_RECOMMENDED", "Not recommended by the agent"),
    ("LEGACY_PROCESSED", "Processed earlier (legacy)"),
    ("EVAL_ERROR", "Evaluation errors"),
    ("UNPROCESSED", "Not processed yet"),
]


def bar(part: int, whole: int, width: int = 30) -> str:
    filled = round(width * part / whole) if whole else 0
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:5.1f}%" if whole else "  0.0%"


def fetch_stats(db_path: Path, recent: int):
    if not db_path.exists():
        return 0, {}, [], []
    try:
        with sqlite3.connect(db_path) as conn:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
            ).fetchone()
            if not table_exists:
                return 0, {}, [], []
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            counts = dict(
                conn.execute(
                    """
                    SELECT COALESCE(NULLIF(action, ''), 'UNPROCESSED') AS status, COUNT(*)
                    FROM jobs
                    GROUP BY status
                    """
                ).fetchall()
            )
            recent_rows = conn.execute(
                """
                SELECT title, company, action_at
                FROM jobs
                WHERE action = 'APPLIED'
                ORDER BY action_at DESC
                LIMIT ?
                """,
                (recent,),
            ).fetchall()
            top_companies = conn.execute(
                """
                SELECT company, COUNT(*) AS n
                FROM jobs
                WHERE action = 'APPLIED'
                GROUP BY company
                ORDER BY n DESC, company
                LIMIT 5
                """
            ).fetchall()
        return total, counts, recent_rows, top_companies
    except sqlite3.OperationalError:
        return 0, {}, [], []


def render(total: int, counts: dict, recent_rows, top_companies) -> str:
    applied = counts.get("APPLIED", 0)
    lines = []
    lines.append("=" * 60)
    lines.append("JOB AGENT DASHBOARD")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Applied: {applied} / {total} scraped jobs  ({pct(applied, total).strip()})")
    lines.append(bar(applied, total, 40))
    lines.append("")
    lines.append("Breakdown")
    lines.append("-" * 60)

    known = {key for key, _ in STATUS_ORDER}
    rows = [(key, label, counts.get(key, 0)) for key, label in STATUS_ORDER]
    # Any status not listed above (e.g. custom actions) still gets shown
    rows += [(k, k, v) for k, v in sorted(counts.items()) if k not in known]

    for key, label, n in rows:
        if n == 0 and key not in ("APPLIED", "UNPROCESSED"):
            continue
        lines.append(f"{label:<38} {n:>5} {pct(n, total)}  {bar(n, total, 12)}")

    if top_companies:
        lines.append("")
        lines.append("Top companies applied to")
        lines.append("-" * 60)
        for company, n in top_companies:
            lines.append(f"{(company or 'Unknown'):<38} {n:>5}")

    if recent_rows:
        lines.append("")
        lines.append("Recent applications")
        lines.append("-" * 60)
        for title, company, action_at in recent_rows:
            when = (action_at or "")[:16].replace("T", " ")
            lines.append(f"{when}  {title} @ {company}")

    lines.append("")
    return "\n".join(lines)

def show_dashboard(db_path, recent: int = 5) -> None:
    """Print the dashboard. Called by the orchestrator after each batch."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    total, counts, recent_rows, top_companies = fetch_stats(Path(db_path), recent)
    print(render(total, counts, recent_rows, top_companies))


def main() -> None:
    parser = argparse.ArgumentParser(description="Applied vs. scraped jobs dashboard")
    parser.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    parser.add_argument("--recent", type=int, default=5, help="How many recent applications to list")
    args = parser.parse_args()

    # Bulgarian titles/company names on Windows consoles
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    db_path = Path(args.db)
    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")

    total, counts, recent_rows, top_companies = fetch_stats(db_path, args.recent)
    print(render(total, counts, recent_rows, top_companies))


if __name__ == "__main__":
    main()
