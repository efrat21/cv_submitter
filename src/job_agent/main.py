"""
DEV.BG Job Discovery & Application Orchestrator Agent
Batch Workflow: Scrape 10 -> Evaluate & Cover Letter -> Browser Apply -> Human Supervision -> Next Batch
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

try:
    from job_agent.config import DATA_DIR
    from job_agent.database import JobDatabase
    from job_agent.devbg.scraper import DevBgScraper
    from job_agent.devbg.application import run as run_browser_application
    from job_agent.llm.evaluator import assess_job
    from job_agent.llm.decision_agent import DecisionAgent
    from job_agent.llm.cover_letter import CoverLetterAgent, slugify
    from job_agent.models import (CandidatePreferences, CandidateProfile, CoverLetter, Job, LLMDecision, MatchResult,
    )
except ImportError:
    from src.job_agent.database import JobDatabase
    from src.job_agent.devbg.scraper import DevBgScraper
    from src.job_agent.devbg.application import run as run_browser_application
    from src.job_agent.models import CandidatePreferences, CandidateProfile, MatchResult, CoverLetter, Job, LLMDecision
    from src.job_agent.llm.evaluator import assess_job
    from src.job_agent.llm.decision_agent import DecisionAgent
    from src.job_agent.llm.cover_letter import CoverLetterAgent


def load_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def parse_skip_steps(raw_values: List[str]) -> List[int]:
    """Parse skip step arguments provided as [1,2], 1,2, or 1 2."""
    steps = []
    for val in raw_values:
        cleaned = val.strip().strip("[]").replace(",", " ")
        for part in cleaned.split():
            if part.isdigit():
                steps.append(int(part))
    return steps

def get_batch_jobs(db_path: str | Path, batch_size: int, skip_scrape: bool) -> List[Job]:
    """Connect to SQLite database and retrieve jobs for the current batch."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        
        # Primary query: Fetch jobs that haven't been acted upon yet
        rows = conn.execute(
            """
            SELECT * FROM jobs 
            WHERE url NOT IN (SELECT job_url FROM job_actions)
            ORDER BY id DESC 
            LIMIT ?
            """,
            (batch_size,)
        ).fetchall()


    return [Job.from_dict(dict(row)) for row in rows]

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

    if 1 in skip_steps:
        print("[INFO] Skipping Step 1: Scraping batch of new jobs.")
    else:
        print("\n========================================")
        print("STEP 1: Scraping batch of new jobs...")
        print("========================================")
        await asyncio.to_thread(scraper.run, start_url=args.url, database=db)

    # Fetch jobs from DB using helper function
# Fetch batch as Job model objects
    batch_jobs: List[Job] = get_batch_jobs(db.path, args.batch_size, skip_scrape=(1 in skip_steps))
    if not batch_jobs:
        print("[INFO] No jobs found to process. Run without skipping Step 1 first.")
        return False

    print(f"[INFO] Found {len(batch_jobs)} jobs to process in this batch.\n")

    print("========================================")
    print("STEP 2: Evaluating jobs & generating cover letters...")
    print("========================================")

    evaluated_batch = []
    if 2 in skip_steps:
        print("[INFO] Skipping step 2: Evaluating jobs & generating cover letters...")
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
        evaluated_batch.append({
                "job": job,
                "decision": dummy_decision,
                "cover_letter": None,
            })
    else:
        cover_letters_dir = Path("data/cover_letters")
        cover_letters_dir.mkdir(parents=True, exist_ok=True)

        for i, job in enumerate(batch_jobs, 1):
            print(f"[{i}/{len(batch_jobs)}] Evaluating: {job.title} @ {job.company}...")
            # Construct MatchResult via evaluator
            match_result = assess_job(job, profile)
            
            # Run LLM Decision Agent
            decision = decision_agent.decide(profile, prefs, match_result)
            print("[info] evalation finished with decision: ", decision.decision)
            cover_letter_path = ""
            if decision.decision == "APPLY":
                # Save markdown file
                slug = f"{slugify(job.company)}_{slugify(job.title)}"
                file_name = f"{slug}.md"
                cover_letter_path = cover_letters_dir / file_name
                # Generate tailored cover letter
                cover_letter_agent = CoverLetterAgent(model=args.model)
                cover_letter_agent.generate(profile=profile, job=job, candidate_name=args.name, decision_context=decision, save_path=cover_letter_path)

            evaluated_batch.append({
                "job": job,
                "decision": decision,
                "cover_letter_path": cover_letter_path
            })
            print(f"[INFO] Cover letter saved to: {cover_letter_path}")

        # Record jobs that were evaluated but not recommended.
        for item in evaluated_batch:
            if item["decision"].decision != "APPLY":
                job = item["job"]
                db.record_action(job.url, "NOT_RECOMMENDED")
            else:
                db.record_action(job.url, "RECOMMENDED")

    print("\n========================================")
    print("STEP 3: Human Supervision & Applications...")
    print("========================================")

    if 3 in skip_steps:
        print("[INFO] Skipping Step 3: Human Supervision & Applications.")
        return True
    else:
        apply_items = [
            item for item in evaluated_batch
            if item["decision"].decision == "APPLY"
        ]

        if not apply_items:
            print("[INFO] No jobs recommended for application in this batch.")
            return True
        else:
            print(f"[INFO] {len(apply_items)} jobs recommended for application. Launching browser review...\n")
            for idx, item in enumerate(apply_items, 1):
                job: Job = item["job"]
                cover_letter_path: Path | None = item["cover_letter_path"]
                print(f"--- Job {idx}/{len(apply_items)}: {job.title} at {job.company} ---")

                # Prepare arguments for application.py runner
                app_ns = argparse.Namespace(
                    url=job.url,
                    name=args.name,
                    email=args.email,
                    cv=args.cv,
                    cover_letter_file=str(cover_letter_path) if cover_letter_path else None,
                    open_apply=True,
                    headed=True
                )

                # Open browser, prefill, and wait for human review/action
                try:
                    await run_browser_application(app_ns)
                except Exception as exc:
                    print(f"[ERROR] Browser automation error: {exc}")

                # Simple terminal prompt interface
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

                # Save action to DB
                db.record_action(job.url, action_status)
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
    parser.add_argument("--skip_step", nargs="*",default=[], help="Steps to skip (e.g., --skip_step [1,2] or --skip_step 1 2)")

    args = parser.parse_args()

    print("========================================")
    print("DEV.BG JOB AGENT - BATCH ORCHESTRATOR")
    print("========================================")

    db = JobDatabase(path=args.db)
    # Ensure action logging table exists
    with sqlite3.connect(db.path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_url TEXT NOT NULL UNIQUE,
                action TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    # Extend JobDatabase helper if not already present
    if not hasattr(db, "record_action"):
        def record_action(self, url: str, action: str):
            with sqlite3.connect(self.path) as c:
                c.execute(
                    "INSERT INTO job_actions (job_url, action) VALUES (?, ?) ON CONFLICT(job_url) DO UPDATE SET action = excluded.action",
                    (url, action)
                )
                c.commit()
        JobDatabase.record_action = record_action

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