"""Re-evaluate previously rejected "Fully Remote" jobs and review/apply to the good fits.

Phase 1 (unattended): re-run the decision agent on every matching job.
Phase 2 (you in the loop): for each job that is now APPLY, generate a cover
letter, open the browser pre-filled, and wait for your a/s/q decision,
exactly like Step 3 of the orchestrator. Nothing is submitted without you.

Examples (run it the same way you run orchestrator.py):
    python -m job_agent.reevaluate_remote --dry-run          # evaluate only, change nothing
    python -m job_agent.reevaluate_remote --name "Your Name" --email you@mail.com
    python -m job_agent.reevaluate_remote --no-apply         # evaluate + cover letters, no browser
    python -m job_agent.reevaluate_remote --review-only      # finish reviewing earlier RECOMMENDED jobs
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from job_agent.config import DATA_DIR
from job_agent.database import JobDatabase
from job_agent.devbg.application import run as run_browser_application
from job_agent.llm.cover_letter import CoverLetterAgent, slugify
from job_agent.llm.decision_agent import DecisionAgent
from job_agent.llm.evaluator import assess_job
from job_agent.models import CandidatePreferences, CandidateProfile, Job


def load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def select_jobs(db_path: str, work_model: str, actions: List[str], limit: int) -> List[Job]:
    """Jobs with the given work model whose current action is one of `actions`."""
    placeholders = ",".join("?" for _ in actions)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT * FROM jobs
            WHERE (LOWER(work_model) = LOWER(?) OR LOWER(location) LIKE '%' || LOWER(?) || '%')
              AND action IN ({placeholders})
            ORDER BY id DESC
            LIMIT ?
            """,
            (work_model, work_model, *actions, limit),
        ).fetchall()
    return [Job.from_dict(dict(r)) for r in rows]


def letter_path_for(job: Job) -> Path:
    # Same naming as the orchestrator
    return Path(DATA_DIR) / "cover_letters" / f"{slugify(job.company)}_{slugify(job.title)}.md"


async def review_applications(items: List[Dict[str, Any]], args: argparse.Namespace, db: JobDatabase) -> None:
    """Human-supervised application loop (same flow as orchestrator Step 3)."""
    for idx, item in enumerate(items, 1):
        job: Job = item["job"]
        letter: Optional[Path] = item.get("letter")
        print(f"\n--- Job {idx}/{len(items)}: {job.title} at {job.company} ---")
        print(f"    {job.url}")

        app_ns = argparse.Namespace(
            url=job.url,
            name=args.name,
            email=args.email,
            cv=args.cv,
            cover_letter_file=str(letter) if letter and letter.exists() else None,
            open_apply=True,
            headed=True,
        )
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-evaluate rejected Fully Remote jobs")
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--profile", default="data/candidate_profile.json")
    ap.add_argument("--preferences", default="data/candidate_preferences.json")
    ap.add_argument("--cv", default="data/cv.pdf")
    ap.add_argument("--name", default="")
    ap.add_argument("--email", default="")
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--min-confidence", type=int, default=70)
    ap.add_argument("--work-model", default="Fully Remote", help="Work model to re-evaluate")
    ap.add_argument("--actions", default="NOT_RECOMMENDED,EVAL_ERROR",
                    help="Comma-separated current actions to re-evaluate")
    ap.add_argument("--limit", type=int, default=200, help="Max jobs to re-evaluate")
    ap.add_argument("--dry-run", action="store_true",
                    help="Evaluate and print results only: no DB writes, no cover letters, no browser")
    ap.add_argument("--no-apply", action="store_true",
                    help="Evaluate, write cover letters and mark RECOMMENDED, but don't open the browser")
    ap.add_argument("--review-only", action="store_true",
                    help="Skip evaluation; go through jobs already marked RECOMMENDED")
    ap.add_argument("--no-history", action="store_true", help="Ignore your past APPLIED/SKIPPED decisions")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    db = JobDatabase(path=args.db)
    try:
        # ------------------------------------------------ review-only mode
        if args.review_only:
            jobs = select_jobs(args.db, args.work_model, ["RECOMMENDED"], args.limit)
            print(f"[INFO] {len(jobs)} RECOMMENDED '{args.work_model}' job(s) awaiting review.")
            items = [{"job": j, "letter": letter_path_for(j)} for j in jobs]
            for it in items:
                if not it["letter"].exists():
                    print(f"[WARN] No cover letter file for {it['job'].title} @ {it['job'].company}")
            asyncio.run(review_applications(items, args, db))
            return

        # ------------------------------------------------ phase 1: re-evaluate
        actions = [a.strip() for a in args.actions.split(",") if a.strip()]
        jobs = select_jobs(args.db, args.work_model, actions, args.limit)
        print("========================================")
        print(f"RE-EVALUATING {len(jobs)} '{args.work_model}' job(s) currently in {actions}")
        if args.dry_run:
            print("DRY RUN: nothing will be written")
        print("========================================")
        if not jobs:
            return

        profile = CandidateProfile.from_dict(load_json(args.profile))
        prefs = CandidatePreferences.from_dict(load_json(args.preferences))
        agent = DecisionAgent(model=args.model, min_confidence=args.min_confidence)
        history = [] if args.no_history else db.get_feedback_history()

        letters_dir = Path(DATA_DIR) / "cover_letters"
        letter_agent: Optional[CoverLetterAgent] = None
        flipped: List[Dict[str, Any]] = []
        errors = 0

        for i, job in enumerate(jobs, 1):
            old = db.get_action(job.url)
            print(f"\n[{i}/{len(jobs)}] {job.title} @ {job.company}  (was {old})")
            try:
                match = assess_job(job, profile)
                decision = agent.decide(profile, prefs, match, history=history)
            except Exception as exc:  # noqa: BLE001
                print(f"    [ERROR] {exc}")
                errors += 1
                continue

            if getattr(decision, "error", None):
                print(f"    [ERROR] agent error: {decision.error} (action left unchanged)")
                errors += 1
                continue

            if decision.decision != "APPLY":
                why = "; ".join(decision.overrides) if decision.overrides else decision.rationale
                print(f"    -> still SKIP (conf {decision.confidence}): {why[:200]}")
                continue

            print(f"    -> NOW APPLY (conf {decision.confidence}): {decision.rationale[:200]}")
            item: Dict[str, Any] = {"job": job, "decision": decision, "letter": None}
            flipped.append(item)

            if args.dry_run:
                continue

            letters_dir.mkdir(parents=True, exist_ok=True)
            letter_agent = letter_agent or CoverLetterAgent()
            path = letter_path_for(job)
            try:
                letter_agent.run(profile=profile, job=job, candidate_name=args.name,
                                 decision_context=decision, save_path=path)
                item["letter"] = path
                print(f"    cover letter: {path}")
            except Exception as exc:  # noqa: BLE001
                print(f"    [WARN] cover letter failed: {exc}")
            db.record_action(job.url, "RECOMMENDED")

        print("\n========================================")
        print(f"Re-evaluated {len(jobs)} | now APPLY: {len(flipped)} | errors: {errors}")
        print("========================================")

        # ------------------------------------------------ phase 2: human review
        if args.dry_run or args.no_apply or not flipped:
            if flipped and args.no_apply:
                print("[INFO] Marked RECOMMENDED. Review them later with --review-only.")
            return
        print(f"\n[INFO] {len(flipped)} job(s) look like a good fit. Launching browser review...")
        asyncio.run(review_applications(flipped, args, db))
    finally:
        db.close()


if __name__ == "__main__":
    main()
