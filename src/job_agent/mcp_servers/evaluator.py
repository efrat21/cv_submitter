"""M4 deterministic and guarded LLM evaluation workflow."""

from __future__ import annotations

import json
import os
from typing import Any

from job_agent.database import JobDatabase
from job_agent.llm.decision_agent import DecisionAgent
from job_agent.llm.evaluator import assess_job
from job_agent.models import CandidatePreferences, CandidateProfile
from job_agent.mcp_servers._workflow_common import load_job, load_preferences, load_profile


def evaluate_job_fit(
    job_url: str,
    db: JobDatabase,
    *,
    profile_data: dict[str, Any] | None = None,
    preferences_data: dict[str, Any] | None = None,
    agent: DecisionAgent | None = None,
) -> dict[str, Any]:
    """Evaluate one stored job and persist a recommendation, not a human action."""
    job = load_job(db, job_url)
    state = db.get_job_processing_state(job_url)
    if state is None:
        raise ValueError(f"Job is not stored in the database: {job_url}")
    action = (state["action"] or "").upper()
    verdict = (state["verdict"] or "").upper()
    application_status = (state["application_status"] or "").upper()
    already_processed = (
        bool(action and action != "EVAL_ERROR")
        or bool(verdict and verdict != "EVAL_ERROR")
        or application_status == "APPLIED"
    )
    if already_processed:
        details = json.loads(state["details_json"] or "{}")
        decision_data = details.get("decision") or {
            "decision": verdict or action or application_status,
            "rationale": state["rationale"] or "",
            "confidence": state["confidence"],
        }
        return {
            "job": {
                "url": job.url,
                "title": job.title,
                "company": job.company,
            },
            "match": details.get("match"),
            "decision": decision_data,
            "current_action": state["action"],
            "already_evaluated": True,
            "evaluation_skipped": True,
            "skip_reason": (
                "already_applied"
                if action == "APPLIED" or application_status == "APPLIED"
                else "already_processed"
            ),
            "application_submitted": False,
            "human_review_required": action == "RECOMMENDED",
        }

    profile_raw = profile_data if profile_data is not None else load_profile()
    preferences_raw = (
        preferences_data if preferences_data is not None else load_preferences()
    )
    profile = CandidateProfile.from_dict(profile_raw)
    preferences = CandidatePreferences.from_dict(preferences_raw)
    match = assess_job(job, profile)

    decision_agent = agent or DecisionAgent(
        model=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
        min_confidence=int(os.environ.get("JOB_AGENT_MIN_CONFIDENCE", "70")),
    )
    decision = decision_agent.decide(
        profile,
        preferences,
        match,
        history=db.get_feedback_history(),
    )
    if decision.error:
        raise RuntimeError(f"Decision evaluation failed for {job_url}: {decision.error}")

    decision_data = decision.to_dict()
    match_data = match.to_dict()
    db.record_evaluation(
        job_url,
        verdict=decision.decision,
        rationale=decision.rationale,
        model=decision_agent.model,
        confidence=decision.confidence,
        overrides=decision.overrides,
        details={"match": match_data, "decision": decision_data},
    )
    db.record_audit_event(
        "evaluation.completed",
        tool_name="job-agent.evaluate_job_fit",
        details={
            "job_url": job_url,
            "verdict": decision.decision,
            "confidence": decision.confidence,
            "prefilter_score": match.prefilter_score,
            "model": decision_agent.model,
        },
    )
    return {
        "job": {
            "url": job.url,
            "title": job.title,
            "company": job.company,
        },
        "match": match_data,
        "decision": decision_data,
        "already_evaluated": False,
        "evaluation_skipped": False,
        "human_review_required": True,
        "application_submitted": False,
    }
