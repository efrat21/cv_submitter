"""Human-supervised application loop, shared by the orchestrator-style scripts.

For each job: open the application page pre-filled (CV + cover letter) in a
visible browser, then wait for YOUR decision: [a]pply / [s]kip / [q]uit.
Nothing is submitted without you. Your choice (and an optional skip reason,
which feeds the decision agent's history) is recorded in the database.

Used by reevaluate_remote.py and daily_routine.py.

Each item passed in is a dict:
    {"job": Job, "letter": Path | None, "cv": str | None}
`cv` is the CV for that job; when empty, `args.cv` is the fallback.
`args` must provide: cv, name, email.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

from job_agent.config import DATA_DIR
from job_agent.database import JobDatabase
from job_agent.devbg.application import run as run_browser_application
from job_agent.llm.cover_letter import slugify
from job_agent.models import Job


def letter_path_for(job: Job) -> Path:
    # Same naming as the orchestrator
    return Path(DATA_DIR) / "cover_letters" / f"{slugify(job.company)}_{slugify(job.title)}.md"


async def review_applications(items: List[Dict[str, Any]], args: argparse.Namespace, db: JobDatabase) -> None:
    """Human-supervised application loop (same flow as orchestrator Step 3)."""
    if not args.name or not args.email:
        print("[WARN] --name / --email not set: those form fields will be empty.")

    for idx, item in enumerate(items, 1):
        job: Job = item["job"]
        letter: Optional[Path] = item.get("letter")
        print(f"\n--- Job {idx}/{len(items)}: {job.title} at {job.company} ---")
        print(f"    {job.url}")

        # Per-job CV (chosen by the listing URL the job came from), else the --cv default.
        cv_value = item.get("cv") or args.cv
        cv_path = Path(cv_value).expanduser().resolve() if cv_value else None
        if cv_path is None or not cv_path.is_file():
            print(f"    [ERROR] CV file not found: {cv_value!r} (looked at: {cv_path}). "
                  "Skipping this job; it stays RECOMMENDED.")
            continue

        letter_file = str(letter.resolve()) if letter and letter.exists() else None
        app_ns = argparse.Namespace(
            url=job.url,
            name=args.name,
            email=args.email,
            cv=str(cv_path),
            cover_letter_file=letter_file,
            open_apply=True,
            headed=True,
        )
        print(f"    CV:           {app_ns.cv}")
        print(f"    Cover letter: {letter_file or '(none)'}")
        try:
            await run_browser_application(app_ns)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] Browser automation error: {exc}")

        note: Optional[str] = None
        while True:
            choice = input("Action [a]pply / [s]kip / [q]uit: ").strip().lower()
            if choice in ("a", "apply"):
                status = "APPLIED"
                break
            if choice in ("s", "skip"):
                status = "SKIPPED"
                note = input("Why skip? (one line, Enter to leave blank): ").strip() or None
                break
            if choice in ("q", "quit"):
                print("[INFO] Stopping. Remaining jobs stay RECOMMENDED; "
                      "finish them later with --review-only.")
                return
            print("Invalid input. Please enter 'a', 's' or 'q'.")

        db.record_action(job.url, status, note)
        print(f"[RECORDED] {status}")
