"""Run the decision agent over a list of match results.

    uv run python run_decisions.py
    uv run python run_decisions.py --model llama3.1:8b --min-confidence 75
"""
import argparse
import csv
import json
import logging
from pathlib import Path

from job_agent.llm.decision_agent import DecisionAgent
from job_agent.models import CandidatePreferences, CandidateProfile, MatchResult

def load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default="data/candidate_profile.json")
    p.add_argument("--preferences", default="data/candidate_preferences.json")
    p.add_argument("--matches", default="data/match_results.json")
    p.add_argument("--model", default="qwen2.5:7b")
    p.add_argument("--min-confidence", type=int, default=70)
    p.add_argument("--out-dir", default="data")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    profile = CandidateProfile.from_dict(load_json(args.profile))
    prefs = CandidatePreferences.from_dict(load_json(args.preferences))
    matches = [MatchResult.from_dict(m) for m in load_json(args.matches)]

    # Enrich jobs with descriptions from jobs.db if missing in match_results.json
    db_file = Path("data/jobs.db")
    if db_file.exists():
        import sqlite3
        with sqlite3.connect(db_file) as conn:
            url_to_desc = dict(conn.execute("SELECT url, description FROM jobs").fetchall())
        for m in matches:
            if not m.job.description and m.job.url in url_to_desc:
                m.job.description = url_to_desc[m.job.url] or ""

    agent = DecisionAgent(model=args.model, min_confidence=args.min_confidence)

    results = []
    for i, match in enumerate(matches, 1):
        print(f"[{i}/{len(matches)}] {match.job.title} @ {match.job.company} ...", flush=True)
        d = agent.decide(profile, prefs, match)
        results.append(d)
        print(f"    -> {d.decision} ({d.confidence}%)  {d.rationale}\n")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "decisions.json").write_text(
        json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with open(out / "decisions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["decision", "confidence", "title", "company", "url", "rationale", "overrides"])
        for r in results:
            w.writerow(
                [r.decision, r.confidence, r.title, r.company, r.job_url,
                 r.rationale, " | ".join(r.overrides)]
            )

    n_apply = sum(r.decision == "APPLY" for r in results)
    print(f"Done: {n_apply} APPLY / {len(results) - n_apply} SKIP  ->  {out}/decisions.csv")


if __name__ == "__main__":
    main()