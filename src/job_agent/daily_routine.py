"""Daily job routine: scrape several URLs -> evaluate -> cover letters -> review & apply one by one.

    1. Scrape every URL in your list (already-known jobs are skipped).
    2. Evaluate all unprocessed jobs with the decision agent (+ your history).
    3. Write a cover letter for each recommended job.
    4. Open each recommended job pre-filled in the browser and WAIT for your
       a(pply) / s(kip) / q(uit). Nothing is submitted without you.

Needs review.py in the same package (it provides the review loop).

URL list file (data/daily_urls.txt): one listing per line, optionally with the CV
to use for jobs found there, separated by "|". Without a CV the --cv default is used.

    https://dev.bg/company/jobs/ml-ai-data/ | data/cv_ml.pdf
    https://dev.bg/company/jobs/python/     | data/cv_python.pdf
    https://dev.bg/company/jobs/devops/

Examples (run it the same way you run orchestrator.py):
    python -m job_agent.daily_routine --name "Your Name" --email you@mail.com
    python -m job_agent.daily_routine --wait-until 09:00        # sleep until 9am, then run
    python -m job_agent.daily_routine --no-review               # prepare only (unattended)
    python -m job_agent.daily_routine --review-only             # just review what is waiting
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.job_agent.config import DATA_DIR
from src.job_agent.database import JobDatabase
from src.job_agent.devbg.scraper import DevBgScraper
from src.job_agent.llm.cover_letter import CoverLetterAgent
from src.job_agent.llm.decision_agent import DecisionAgent
from src.job_agent.llm.evaluator import assess_job
from src.job_agent.models import CandidatePreferences, CandidateProfile, Job
from src.job_agent.review import letter_path_for, review_applications

DEFAULT_URLS_FILE = "data/daily_urls.txt"


def load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Tee:
    """Mirror everything printed to a log file (useful for the unattended 9am run)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()

    def __getattr__(self, name):  # encoding, isatty, ...
        return getattr(self.streams[0], name)


def banner(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def read_urls(args: argparse.Namespace) -> List[Tuple[str, Optional[str]]]:
    """Return [(listing_url, cv_path_or_None)], first occurrence of a URL wins."""
    entries: List[Tuple[str, Optional[str]]] = [(u.strip(), None) for u in (args.url or [])]
    path = Path(args.urls_file)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = re.split(r"\s+#", line, maxsplit=1)[0]  # trailing " # comment"
            url, _, cv = line.partition("|")
            entries.append((url.strip(), cv.strip().strip('"') or None))

    seen, unique = set(), []
    for url, cv in entries:
        if url and url not in seen:
            seen.add(url)
            unique.append((url, cv))
    return unique


def wait_until(hhmm: str) -> None:
    hh, mm = (int(x) for x in hhmm.split(":"))
    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    print(f"[INFO] Waiting until {target:%Y-%m-%d %H:%M} ({(target - now).total_seconds() / 3600:.1f} h). "
          "Keep this window open. Ctrl+C to cancel.")
    time.sleep((target - now).total_seconds())


def jobs_with_action(db: JobDatabase, action: str, limit: int = 500) -> List[Job]:
    cur = db.connection.execute(
        "SELECT * FROM jobs WHERE action = ? ORDER BY id DESC LIMIT ?", (action, limit)
    )
    cols = [c[0] for c in cur.description]
    return [Job.from_dict(dict(zip(cols, row))) for row in cur.fetchall()]


# ------------------------------------------------------------------ steps

def scrape_all(args: argparse.Namespace, db: JobDatabase, targets: List[Tuple[str, Optional[str]]]) -> None:
    banner(f"STEP 1: Scraping {len(targets)} URL(s)")
    scraper = DevBgScraper(
        headless=not args.headed_scrape,
        max_jobs=args.max_jobs_per_url,
        max_pages=args.max_pages,
    )
    for n, (url, cv) in enumerate(targets, 1):
        cv_abs = str(Path(cv or args.cv).expanduser().resolve())
        print(f"\n[{n}/{len(targets)}] {url}")
        print(f"    CV for these jobs: {cv_abs}{'' if cv else ' (default)'}")
        known_before = db.known_urls()
        try:
            scraper.run(start_url=url, database=db)
        except Exception as exc:  # noqa: BLE001 - one bad URL must not stop the routine
            print(f"[ERROR] Scrape failed for {url}: {exc}")
        new_urls = db.known_urls() - known_before
        if cv_abs and new_urls:
            db.set_cv_path(new_urls, cv_abs)  # remembered until the job is reviewed
        print(f"[INFO] {len(new_urls)} new job(s) from this URL.")


def evaluate_unprocessed(
    args: argparse.Namespace,
    db: JobDatabase,
    profile: CandidateProfile,
    prefs: CandidatePreferences,
    agent: DecisionAgent,
) -> Dict[str, int]:
    banner("STEP 2: Evaluating unprocessed jobs & writing cover letters")
    stats = {"evaluated": 0, "recommended": 0, "rejected": 0, "errors": 0}
    rows = db.get_unprocessed_jobs(args.max_evaluate)
    if not rows:
        print("[INFO] Nothing new to evaluate.")
        return stats

    print(f"[INFO] {len(rows)} unprocessed job(s) (cap: --max-evaluate {args.max_evaluate}).")
    history = db.get_feedback_history()
    (Path(DATA_DIR) / "cover_letters").mkdir(parents=True, exist_ok=True)
    letter_agent = CoverLetterAgent()

    for i, row in enumerate(rows, 1):
        job = Job.from_dict(row)
        print(f"\n[{i}/{len(rows)}] {job.title} @ {job.company}")
        try:
            match = assess_job(job, profile)
            decision = agent.decide(profile, prefs, match, history=history)
            if getattr(decision, "error", None):
                raise RuntimeError(decision.error)

            if decision.decision == "APPLY":
                path = letter_path_for(job)
                letter_agent.run(profile=profile, job=job, candidate_name=args.name,
                                 decision_context=decision, save_path=path)
                db.record_action(job.url, "RECOMMENDED")
                stats["recommended"] += 1
                print(f"    -> APPLY (conf {decision.confidence}); letter: {path.name}")
            else:
                db.record_action(job.url, "NOT_RECOMMENDED")
                stats["rejected"] += 1
                why = "; ".join(decision.overrides) if decision.overrides else decision.rationale
                print(f"    -> SKIP: {why[:150]}")
            stats["evaluated"] += 1
        except Exception as exc:  # noqa: BLE001
            print(f"    [ERROR] {exc}")
            db.record_action(job.url, "EVAL_ERROR")
            stats["errors"] += 1
    return stats


def review_queue(args: argparse.Namespace, db: JobDatabase) -> None:
    banner("STEP 3: Review & apply (one by one, with your approval)")
    queue = [
        {"job": j, "letter": letter_path_for(j), "cv": db.get_cv_path(j.url)}
        for j in jobs_with_action(db, "RECOMMENDED")
    ]
    if not queue:
        print("[INFO] No recommended jobs waiting.")
        return

    print(f"[INFO] {len(queue)} recommended job(s) waiting:")
    for it in queue:
        flag = "" if it["letter"].exists() else "  [no cover letter file]"
        cv_name = Path(it["cv"] or args.cv).name
        print(f"  - {it['job'].title} @ {it['job'].company}  (CV: {cv_name}){flag}")

    if args.no_review:
        print("[INFO] --no-review: leaving them RECOMMENDED. Run with --review-only when ready.")
        return
    if input(f"\nReview and apply to {len(queue)} job(s) now? [y/n]: ").strip().lower() not in ("y", "yes"):
        print("[INFO] OK. Run with --review-only whenever you are ready.")
        return
    asyncio.run(review_applications(queue, args, db))


# -------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="Daily job routine")
    ap.add_argument("--url", action="append", help="Listing URL to check (repeatable)")
    ap.add_argument("--urls-file", default=DEFAULT_URLS_FILE,
                    help=f"Text file with one URL per line, # for comments (default: {DEFAULT_URLS_FILE})")
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--profile", default="data/candidate_profile.json")
    ap.add_argument("--preferences", default="data/candidate_preferences.json")
    ap.add_argument("--cv", default=r"C:\Users\efrat\OneDrive\עבודה\חיפוש עבודה\Efrat Miyara data scientist _compressed.pdf")
    ap.add_argument("--name", default="Efrat Miyara")
    ap.add_argument("--email", default="efrat.miyara@gmail.com")
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--min-confidence", type=int, default=70)
    ap.add_argument("--max-pages", type=int, default=5, help="Listing pages to scan per URL")
    ap.add_argument("--max-jobs-per-url", type=int, default=30, help="Max NEW jobs scraped per URL")
    ap.add_argument("--max-evaluate", type=int, default=40, help="Max jobs evaluated per run")
    ap.add_argument("--headed-scrape", action="store_true", help="Show the browser while scraping")
    ap.add_argument("--wait-until", metavar="HH:MM", help="Sleep until this time (e.g. 09:00), then run once")
    ap.add_argument("--skip-scrape", action="store_true", help="Don't scrape, only evaluate/review")
    ap.add_argument("--no-review", action="store_true", help="Prepare only; don't open the browser")
    ap.add_argument("--review-only", action="store_true", help="Skip scraping and evaluation")
    args = ap.parse_args()

    # Log everything to data/logs/daily_YYYY-MM-DD.log as well as the console
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    log_dir = Path(DATA_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    if args.wait_until:
        wait_until(args.wait_until)

    log_file = open(log_dir / f"daily_{datetime.now():%Y-%m-%d}.log", "a", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)

    banner(f"DAILY JOB ROUTINE  {datetime.now():%Y-%m-%d %H:%M}")
    db = JobDatabase(path=args.db)
    try:
        if not args.review_only:
            targets = read_urls(args)
            missing = [cv for _, cv in targets if cv and not Path(cv).expanduser().is_file()]
            if missing:
                sys.exit("CV file(s) not found: " + ", ".join(sorted(set(missing))))
            if not targets and not args.skip_scrape:
                sys.exit(f"No URLs given. Pass --url or create {args.urls_file} (one URL per line).")

            profile = CandidateProfile.from_dict(load_json(args.profile))
            prefs = CandidatePreferences.from_dict(load_json(args.preferences))
            agent = DecisionAgent(model=args.model, min_confidence=args.min_confidence)
            try:  # fail early if Ollama isn't running
                agent.client.list()
            except Exception as exc:  # noqa: BLE001
                sys.exit(f"Cannot reach Ollama ({exc}). Start it first (e.g. `ollama serve`).")

            if not args.skip_scrape:
                scrape_all(args, db, targets)
            stats = evaluate_unprocessed(args, db, profile, prefs, agent)
            print(f"\n[SUMMARY] evaluated {stats['evaluated']} | recommended {stats['recommended']} "
                  f"| rejected {stats['rejected']} | errors {stats['errors']}")

        review_queue(args, db)

        try:
            from job_agent.dashboard import show_dashboard
            show_dashboard(db.path)
        except ImportError:
            pass
    finally:
        db.close()
        log_file.close()
        sys.stdout = sys.__stdout__


if __name__ == "__main__":
    main()