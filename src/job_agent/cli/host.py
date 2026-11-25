"""Command-line entry point for the M6 agent host."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from job_agent.agent_host import daily_mode, interactive_chat
from job_agent.config import DEFAULT_DB_PATH
from job_agent.database import JobDatabase
from job_agent.evaluation_harness import run_regression_evaluation
from job_agent.llm.decision_agent import DecisionAgent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("chat", help="Start interactive natural-language MCP chat")

    daily = commands.add_parser(
        "daily", help="Prepare jobs, sync email, and print the local digest"
    )
    daily.add_argument("--name", default="")
    daily.add_argument("--email", default="")
    daily.add_argument(
        "--skip-job-prep",
        action="store_true",
        help="Skip legacy discovery/evaluation/letter preparation",
    )
    daily.add_argument(
        "--skip-email-sync",
        action="store_true",
        help="Do not access Gmail; still print the local digest",
    )
    daily.add_argument(
        "--allow-remote-letters",
        action="store_true",
        help="Allow cover-letter generation to send candidate/job data to Gemini",
    )

    regression = commands.add_parser(
        "evaluate-regressions",
        help="Evaluate stored human decisions with the configured local model",
    )
    regression.add_argument("--db", default=str(DEFAULT_DB_PATH))
    regression.add_argument("--profile", default=None)
    regression.add_argument("--preferences", default=None)
    regression.add_argument("--model", default=None)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "chat":
        asyncio.run(interactive_chat())
        return
    if args.command == "daily":
        result = asyncio.run(
            daily_mode(
                name=args.name,
                email=args.email,
                skip_job_prep=args.skip_job_prep,
                skip_email_sync=args.skip_email_sync,
                allow_remote_letters=args.allow_remote_letters,
            )
        )
        if args.skip_email_sync:
            print("Email sync skipped.")
        else:
            sync_data = json.loads(result["email_sync"])
            print(f"Email sync completed; {sync_data.get('synced', 0)} messages processed.")
        try:
            digest = json.loads(result["digest"])
        except json.JSONDecodeError:
            print(result["digest"])
        else:
            print(digest.get("text") or json.dumps(digest, ensure_ascii=False, indent=2))
        return

    db = JobDatabase(args.db)
    try:
        agent = DecisionAgent(
            model=args.model or os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
        )
        report = run_regression_evaluation(
            db,
            agent=agent,
            profile_path=args.profile,
            preferences_path=args.preferences,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["errors"]:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
