"""Debug the decision process for ONE job URL, step by step.

Nothing is written to the database and no cover letter is made unless you ask.

Examples (run it the same way you run orchestrator.py):
    python -m job_agent.debug_decision https://dev.bg/company/jobads/xyz/
    python -m job_agent.debug_decision <url> --show-prompt
    python -m job_agent.debug_decision <url> --rescrape --no-history
    python -m job_agent.debug_decision <url> --cover-letter --name "Your Name"
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

from .config import DATA_DIR
from .database import JobDatabase
from .devbg.scraper import DevBgScraper
from .llm.cover_letter import CoverLetterAgent, slugify
from .llm.decision_agent import DecisionAgent, select_examples
from .llm.evaluator import assess_job
from .llm.prompts import format_history
from .models import CandidatePreferences, CandidateProfile, Job


def header(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def as_dict(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return dict(vars(obj))


def pretty(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_job_from_db(db_path: str, url: str) -> Job | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
    return Job.from_dict(dict(row)) if row else None


def scrape_one(url: str, headed: bool) -> Job:
    from playwright.sync_api import sync_playwright

    scraper = DevBgScraper(headless=not headed)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        try:
            context = browser.new_context(locale="bg-BG", viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            return scraper.scrape_job(page, url)
        finally:
            browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Debug the APPLY/SKIP decision for one job URL")
    ap.add_argument("url", help="DEV.BG job URL")
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--profile", default="data/candidate_profile.json")
    ap.add_argument("--preferences", default="data/candidate_preferences.json")
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--min-confidence", type=int, default=70)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--rescrape", action="store_true", help="Scrape the page even if it is in the DB")
    ap.add_argument("--headed", action="store_true", help="Show the browser while scraping")
    ap.add_argument("--no-history", action="store_true", help="Ignore your past APPLIED/SKIPPED decisions")
    ap.add_argument("--show-prompt", action="store_true", help="Print the full system + user prompt")
    ap.add_argument("--save", action="store_true", help="Save the scraped job to the DB (never records an action)")
    ap.add_argument("--cover-letter", action="store_true", help="Also generate a cover letter if the result is APPLY")
    ap.add_argument("--name", default="", help="Candidate name (for the cover letter)")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    db = JobDatabase(path=args.db)
    profile = CandidateProfile.from_dict(load_json(args.profile))
    prefs = CandidatePreferences.from_dict(load_json(args.preferences))

    # ---------------------------------------------------------- 1. job
    header("1. JOB")
    job = None if args.rescrape else load_job_from_db(args.db, args.url)
    if job:
        print(f"Loaded from DB ({args.db}). Use --rescrape to fetch it again.")
    else:
        print("Scraping the page...")
        job = scrape_one(args.url, args.headed)
        if args.save:
            db.save_job(job)
            print("Saved to DB (no action recorded).")
    print(f"Title:      {job.title}")
    print(f"Company:    {job.company}")
    print(f"Location:   {job.location}")
    print(f"Work model: {job.work_model}")
    print(f"Tags:       {job.tags}")
    print(f"Description: {len(job.description or '')} chars")
    print(f"Existing action in DB: {db.get_action(args.url)!r}")

    # ---------------------------------------------------------- 2. pre-match
    header("2. KEYWORD PRE-MATCH (assess_job)")
    match = assess_job(job, profile)
    md = copy.deepcopy(as_dict(match))
    desc = md.get("job", {}).get("description")
    if isinstance(desc, str) and len(desc) > 300:
        md["job"]["description"] = desc[:300] + f" ...[{len(desc)} chars total]"
    print(pretty(md))

    # ---------------------------------------------------------- 3. history
    header("3. YOUR PAST DECISIONS SENT TO THE MODEL")
    history: List[Dict[str, Any]] = [] if args.no_history else db.get_feedback_history()
    print(f"{len(history)} past APPLIED/SKIPPED decision(s) in DB"
          + (" (ignored: --no-history)" if args.no_history else ""))
    examples = select_examples(history, match)
    print(format_history(examples) or "(none selected)")

    # ---------------------------------------------------------- 4-6. LLM + guardrails
    agent = DecisionAgent(model=args.model, min_confidence=args.min_confidence, num_ctx=args.num_ctx)

    # Record every LLM exchange without changing behaviour
    exchanges: List[tuple] = []
    original_chat = agent._chat

    def traced_chat(messages):
        out = original_chat(messages)
        exchanges.append((copy.deepcopy(messages), out))
        return out

    agent._chat = traced_chat

    header("4. LLM CALL")
    final = agent.decide(profile, prefs, match, history=history)

    if args.show_prompt and exchanges:
        first = exchanges[0][0]
        print("\n--- SYSTEM PROMPT ---\n" + first[0]["content"])
        print("\n--- USER PROMPT ---\n" + first[1]["content"])
    elif exchanges:
        user_len = len(exchanges[0][0][1]["content"])
        print(f"(user prompt: {user_len} chars; add --show-prompt to print it)")

    for i, (_, raw) in enumerate(exchanges, 1):
        print(f"\n--- RAW LLM OUTPUT (attempt {i}/{len(exchanges)}) ---")
        print(raw)
    if len(exchanges) > 1:
        print(f"\n[!] The model needed {len(exchanges)} attempts: earlier outputs failed validation.")

    if final.error:
        header("RESULT: AGENT ERROR")
        print(f"Error: {final.error}")
        print("Final decision: SKIP (fail-safe)")
        db.close()
        return

    header("5. MODEL'S OWN VERDICT (before guardrails)")
    llm = final.llm
    print(pretty(as_dict(llm)))

    header("6. GUARDRAILS (Python has the final say)")
    if final.overrides:
        print(f"Model said {llm.decision}; guardrails changed it to SKIP because:")
        for reason in final.overrides:
            print(f"  - {reason}")
    elif llm.decision == "APPLY":
        print("No guardrail fired: the APPLY stands.")
    else:
        print("Model said SKIP; guardrails only act on APPLY, so nothing to check.")

    header("FINAL DECISION")
    print(f"Decision:   {final.decision}")
    print(f"Confidence: {final.confidence} (threshold {args.min_confidence})")
    print(f"Rationale:  {final.rationale}")

    # ---------------------------------------------------------- optional cover letter
    if args.cover_letter:
        header("7. COVER LETTER")
        if final.decision != "APPLY":
            print("Skipped: the final decision is not APPLY.")
        else:
            out_dir = Path(DATA_DIR) / "cover_letters"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"debug_{slugify(job.company)}_{slugify(job.title)}.md"
            CoverLetterAgent().run(
                profile=profile, job=job, candidate_name=args.name,
                decision_context=final, save_path=path,
            )
            print(f"Saved to: {path}\n")
            print(path.read_text(encoding="utf-8"))

    db.close()


if __name__ == "__main__":
    main()
