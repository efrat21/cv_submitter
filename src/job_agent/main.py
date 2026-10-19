"""
DEV.BG Job Discovery & Application Orchestrator Agent
Batch Workflow: Scrape -> Evaluate & Cover Letter -> Browser Apply -> Human Supervision -> Next Batch
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Set
from urllib.parse import urlsplit, urlunsplit

from job_agent.config import DATA_DIR
from job_agent.database import JobDatabase
from job_agent.devbg.scraper import DevBgScraper
from job_agent.devbg.application import run as run_browser_application
from job_agent.llm.evaluator import assess_job
from job_agent.llm.decision_agent import DecisionAgent
from job_agent.llm.cover_letter import CoverLetterAgent, slugify
from job_agent.models import CandidatePreferences, CandidateProfile, Job, LLMDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_skip_steps(raw_values: List[str]) -> List[int]:
    """Parse skip step arguments provided as [1,2], 1,2, or 1 2."""
    steps: List[int] = []
    for val in raw_values:
        cleaned = val.strip().strip("[]").replace(",", " ")
        for part in cleaned.split():
            if part.isdigit():
                steps.append(int(part))
    return steps


def normalize_url(url: str) -> str:
    """Normalize a job URL so trivial differences don't create 'new' jobs
    (trailing slash, fragment, scheme/host casing)."""
    parts = urlsplit((url or "").strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


# ---------------------------------------------------------------------------
# Database helpers (existing-job checks live here)
# ---------------------------------------------------------------------------

def ensure_actions_table(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_url TEXT NOT NULL UNIQUE,
                action TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def record_action(db_path: str | Path, url: str, action: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO job_actions (job_url, action) VALUES (?, ?)
            ON CONFLICT(job_url) DO UPDATE SET action = excluded.action,
                                               timestamp = CURRENT_TIMESTAMP
            """,
            (url, action),
        )
        conn.commit()


def get_job_urls(db_path: str | Path) -> Set[str]:
    """All job URLs currently stored in the jobs table (normalized)."""
    with sqlite3.connect(db_path) as conn:
        return {normalize_url(r[0]) for r in conn.execute("SELECT url FROM jobs") if r[0]}


def get_acted_urls(db_path: str | Path) -> Set[str]:
    """All job URLs that already have a recorded action (normalized)."""
    with sqlite3.connect(db_path) as conn:
        return {normalize_url(r[0]) for r in conn.execute("SELECT job_url FROM job_actions") if r[0]}


def has_action(db_path: str | Path, url: str) -> bool:
    """True if this job was already evaluated / applied to / skipped."""
    return normalize_url(url) in get_acted_urls(db_path)


def get_batch_jobs(db_path: str | Path, batch_size: int) -> List[Job]:
    """Return up to `batch_size` jobs that have not been acted upon yet.

    - Excludes any job whose (normalized) URL is already in job_actions.
    - De-duplicates rows in `jobs` that point to the same normalized URL.
    - Newest jobs first.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        acted = {normalize_url(r["job_url"]) for r in conn.execute("SELECT job_url FROM job_actions")}
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()

    batch: List[Job] = []
    seen: Set[str] = set()
    already_processed = 0

    for row in rows:
        data = dict(row)
        key = normalize_url(data.get("url", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        if key in acted:
            already_processed += 1
            continue
        batch.append(Job.from_dict(data))
        if len(batch) >= batch_size:
            break

    if already_processed:
        print(f"[INFO] Ignored {already_processed} job(s) already processed in the DB.")
    return batch


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

async def process_batch(
    db: JobDatabase,
    scraper: DevBgScraper,
    profile: CandidateProfile,
    prefs: CandidatePreferences,
    decision_agent: DecisionAgent,
    args: argparse.Namespace,
) -> bool:
    """Scrape, evaluate, generate cover letters, and supervise application for a batch of jobs."""

    skip_steps = parse_skip_steps(args.skip_step)

    # ---------------- STEP 1: scrape ----------------
    if 1 in skip_steps:
        print("[INFO] Skipping Step 1: Scraping batch of new jobs.")
    else:
        print("\n========================================")
        print("STEP 1: Scraping batch of new jobs...")
        print("========================================")
        known_before = get_job_urls(db.path)
        await asyncio.to_thread(scraper.run, start_url=args.url, database=db)
        known_after = get_job_urls(db.path)
        new_urls = known_after - known_before
        print(f"[INFO] Scrape finished: {len(new_urls)} new job(s) added "
              f"({len(known_after)} total in DB).")

    # Only jobs that have not been acted upon yet
    batch_jobs: List[Job] = get_batch_jobs(db.path, args.batch_size)
    if not batch_jobs:
        print("[INFO] No unprocessed jobs found. Everything in the DB has been handled already; "
              "try a different --url or more --max-pages.")
        return False

    print(f"[INFO] Found {len(batch_jobs)} unprocessed job(s) in this batch.\n")

    # ---------------- STEP 2: evaluate + cover letters ----------------
    print("========================================")
    print("STEP 2: Evaluating jobs & generating cover letters...")
    print("========================================")

    evaluated_batch: List[Dict[str, Any]] = []

    if 2 in skip_steps:
        print("[INFO] Skipping Step 2: Evaluating jobs & generating cover letters.")
        for job in batch_jobs:
            dummy_decision = LLMDecision(
                role_fit="strong",
                seniority_fit="good",
                location_fit="good",
                hard_blockers=[],
                critical_missing_skills=[],
                reasons_for=["Skipped step 2 via CLI"],
                reasons_against=[],
                confidence=100,
                decision="APPLY",
                rationale="Evaluation step skipped.",
            )
            evaluated_batch.append({"job": job, "decision": dummy_decision, "cover_letter_path": None})
    else:
        cover_letters_dir = Path(DATA_DIR) / "cover_letters"
        cover_letters_dir.mkdir(parents=True, exist_ok=True)
        cover_letter_agent = CoverLetterAgent()

        for i, job in enumerate(batch_jobs, 1):
            # Re-check right before doing expensive LLM work
            if has_action(db.path, job.url):
                print(f"[{i}/{len(batch_jobs)}] Already processed, skipping: {job.title} @ {job.company}")
                continue

            print(f"[{i}/{len(batch_jobs)}] Evaluating: {job.title} @ {job.company}...")

            try:
                match_result = assess_job(job, profile)

                print("[TIMING] Starting decision evaluation...", flush=True)
                start = time.perf_counter()
                decision = decision_agent.decide(profile, prefs, match_result)
                print(
                    f"[TIMING] Decision completed in {time.perf_counter() - start:.1f}s "
                    f"(decision={decision.decision})",
                    flush=True,
                )

                cover_letter_path: Path | None = None
                if decision.decision == "APPLY":
                    slug = f"{slugify(job.company)}_{slugify(job.title)}"
                    cover_letter_path = cover_letters_dir / f"{slug}.md"
                    cover_letter_agent.run(
                        profile=profile,
                        job=job,
                        candidate_name=args.name,
                        decision_context=decision,
                        save_path=cover_letter_path,
                    )
                    print(f"[INFO] Cover letter saved to: {cover_letter_path}")
            except Exception as exc:
                print(f"[ERROR] Evaluation failed for {job.title} @ {job.company}: {exc}")
                record_action(db.path, job.url, "EVAL_ERROR")
                continue

            # Record immediately so a crash/quit later doesn't lose progress
            record_action(db.path, job.url, "RECOMMENDED" if decision.decision == "APPLY" else "NOT_RECOMMENDED")
            evaluated_batch.append({"job": job, "decision": decision, "cover_letter_path": cover_letter_path})

    # ---------------- STEP 3: human supervision ----------------
    if 3 in skip_steps:
        print("[INFO] Skipping Step 3: Human Supervision & Applications.")
        return True

    print("\n========================================")
    print("STEP 3: Human Supervision & Applications...")
    print("========================================")

    apply_items = [item for item in evaluated_batch if item["decision"].decision == "APPLY"]
    if not apply_items:
        print("[INFO] No jobs recommended for application in this batch.")
        return True

    print(f"[INFO] {len(apply_items)} jobs recommended for application. Launching browser review...\n")
    for idx, item in enumerate(apply_items, 1):
        job: Job = item["job"]
        cover_letter_path: Path | None = item["cover_letter_path"]
        print(f"--- Job {idx}/{len(apply_items)}: {job.title} at {job.company} ---")

        app_ns = argparse.Namespace(
            url=job.url,
            name=args.name,
            email=args.email,
            cv=args.cv,
            cover_letter_file=str(cover_letter_path) if cover_letter_path else None,
            open_apply=True,
            headed=True,
        )

        try:
            await run_browser_application(app_ns)
        except Exception as exc:
            print(f"[ERROR] Browser automation error: {exc}")

        while True:
            choice = input("Action [a]pply / [s]kip / [q]uit: ").strip().lower()
            if choice in ("a", "apply"):
                action_status = "APPLIED"
                break
            elif choice in ("s", "skip"):
                action_status = "SKIPPED"
                break
            elif choice in ("q", "quit"):
                print("[INFO] Exiting agent session.")
                return False
            else:
                print("Invalid input. Please enter 'a' (apply), 's' (skip), or 'q' (quit).")

        record_action(db.path, job.url, action_status)
        print(f"[RECORDED] Job status saved as: {action_status}\n")

    return True


def main():
    parser = argparse.ArgumentParser(description="DEV.BG Job Discovery & Application Agent")
    parser.add_argument("--url", default="https://dev.bg/company/jobs/ml-ai-data/", help="Start URL to scrape")
    parser.add_argument("--batch-size", type=int, default=10, help="Jobs per batch (default: 10)")
    parser.add_argument("--max-pages", type=int, default=1, help="Maximum pages to scrape per batch")
    parser.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    parser.add_argument("--profile", default="data/candidate_profile.json", help="Candidate profile JSON")
    parser.add_argument("--preferences", default="data/candidate_preferences.json", help="Candidate preferences JSON")
    parser.add_argument("--cv", default="data/cv.pdf", help="Path to candidate CV PDF/DOCX")
    parser.add_argument("--email", default="", help="Candidate email for application forms")
    parser.add_argument("--name", default="", help="Candidate full name")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model name")
    parser.add_argument("--min-confidence", type=int, default=70, help="Minimum confidence threshold")
    parser.add_argument("--headless", action="store_true", default=False, help="Run scraper in headless mode")
    parser.add_argument("--skip_step", nargs="*", default=[],
                        help="Steps to skip (e.g., --skip_step [1,2] or --skip_step 1 2)")

    args = parser.parse_args()

    print("========================================")
    print("DEV.BG JOB AGENT - BATCH ORCHESTRATOR")
    print("========================================")

    db = JobDatabase(path=args.db)
    ensure_actions_table(db.path)

    scraper = DevBgScraper(headless=args.headless, max_jobs=args.batch_size, max_pages=args.max_pages)
    profile = CandidateProfile.from_dict(load_json(args.profile))
    prefs = CandidatePreferences.from_dict(load_json(args.preferences))
    decision_agent = DecisionAgent(model=args.model, min_confidence=args.min_confidence)

    try:
        while True:
            should_continue = asyncio.run(
                process_batch(db, scraper, profile, prefs, decision_agent, args)
            )
            if not should_continue:
                break

            cont = input("Continue to next batch of jobs? (y/n): ").strip().lower()
            if cont not in ("y", "yes"):
                print("[INFO] Stopping batch session. Goodbye!")
                break
    finally:
        db.close()


if __name__ == "__main__":
    main()