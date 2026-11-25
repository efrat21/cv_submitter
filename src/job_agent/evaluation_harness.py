"""Read-only regression evaluation against stored human and legacy decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_agent.database import JobDatabase
from job_agent.llm.decision_agent import DecisionAgent
from job_agent.llm.evaluator import assess_job
from job_agent.models import CandidatePreferences, CandidateProfile, Job
from job_agent.mcp_servers._workflow_common import load_preferences, load_profile


def run_regression_evaluation(
    db: JobDatabase,
    *,
    agent: DecisionAgent,
    profile_data: dict[str, Any] | None = None,
    preferences_data: dict[str, Any] | None = None,
    profile_path: str | Path | None = None,
    preferences_path: str | Path | None = None,
) -> dict[str, Any]:
    """Re-evaluate historical cases without changing stored jobs or decisions.

    APPLIED/SKIPPED are treated as human reference labels. NOT_RECOMMENDED
    rows are reported separately as consistency checks, not as human feedback.
    """
    if profile_data is not None:
        profile_raw = profile_data
    elif profile_path:
        profile_raw = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    else:
        profile_raw = load_profile()

    if preferences_data is not None:
        preferences_raw = preferences_data
    elif preferences_path:
        preferences_raw = json.loads(Path(preferences_path).read_text(encoding="utf-8"))
    else:
        preferences_raw = load_preferences()
    profile = CandidateProfile.from_dict(profile_raw)
    preferences = CandidatePreferences.from_dict(preferences_raw)

    cursor = db.connection.execute(
        """
        SELECT * FROM jobs
        WHERE action IN ('APPLIED', 'SKIPPED', 'NOT_RECOMMENDED')
        ORDER BY id
        """
    )
    columns = [column[0] for column in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    if not rows:
        raise ValueError(
            "No APPLIED, SKIPPED, or NOT_RECOMMENDED jobs are available to evaluate"
        )

    history_cursor = db.connection.execute(
        """
        SELECT url, title, company, location, work_model, tags_json,
               action, action_note, action_at
        FROM jobs
        WHERE action IN ('APPLIED', 'SKIPPED')
        ORDER BY action_at DESC
        """
    )
    history_columns = [column[0] for column in history_cursor.description]
    human_history = [
        dict(zip(history_columns, row)) for row in history_cursor.fetchall()
    ]

    human_cases: list[dict[str, Any]] = []
    baseline_cases: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for row in rows:
        expected = "APPLY" if row["action"] == "APPLIED" else "SKIP"
        history = [item for item in human_history if item["url"] != row["url"]]
        try:
            job = Job.from_dict(row)
            decision = agent.decide(
                profile,
                preferences,
                assess_job(job, profile),
                history=history,
            )
            if getattr(decision, "error", None):
                raise RuntimeError(str(decision.error))
            predicted = decision.decision
            case = {
                "url": row["url"],
                "action": row["action"],
                "expected": expected,
                "predicted": predicted,
                "correct": predicted == expected,
            }
            if row["action"] == "NOT_RECOMMENDED":
                baseline_cases.append(case)
            else:
                human_cases.append(case)
        except Exception as error:
            errors.append(
                {
                    "url": str(row["url"]),
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )

    human_correct = sum(case["correct"] for case in human_cases)
    baseline_consistent = sum(case["correct"] for case in baseline_cases)
    return {
        "model": getattr(agent, "model", "unknown"),
        "cases": len(rows),
        "human_reference": {
            "cases": len(human_cases),
            "correct": human_correct,
            "accuracy": human_correct / len(human_cases) if human_cases else None,
            "results": human_cases,
        },
        "legacy_agent_consistency": {
            "cases": len(baseline_cases),
            "consistent": baseline_consistent,
            "rate": (
                baseline_consistent / len(baseline_cases)
                if baseline_cases
                else None
            ),
            "results": baseline_cases,
        },
        "errors": errors,
        "database_modified": False,
    }
