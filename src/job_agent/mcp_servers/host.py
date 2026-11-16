"""M4 MCP tools for evaluation, cover letters, and human application review."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel, Field

from job_agent.config import DEFAULT_DB_PATH
from job_agent.database import JobDatabase
from job_agent.mcp_servers.application_review import (
    get_application_review as build_review_packet,
    record_human_application_review,
)
from job_agent.mcp_servers.cover_letters import (
    generate_cover_letter as generate_letter,
)
from job_agent.mcp_servers.evaluator import evaluate_job_fit as run_evaluation

log = logging.getLogger(__name__)
mcp = MCPServer(
    "job-agent-workflow",
    instructions=(
        "Evaluation results are recommendations, not application decisions. "
        "Always show the review packet and obtain explicit human elicitation "
        "before recording APPLIED or SKIPPED. This server never submits applications."
    ),
)


class HumanReviewResponse(BaseModel):
    """Human response required before updating APPLIED/SKIPPED feedback."""

    action: Literal["APPLIED", "SKIPPED"] = Field(
        description="Record APPLIED only after you submitted manually; otherwise choose SKIPPED or cancel."
    )
    confirmed: bool = Field(
        description="Confirm that this action matches your own reviewed decision."
    )
    note: str = Field(
        default="",
        description="Optional reason for skipping or a note about the manual review.",
    )


def _open_db() -> JobDatabase:
    path = os.environ.get("JOB_AGENT_DB_PATH")
    return JobDatabase(Path(path) if path else DEFAULT_DB_PATH)


def _record_failure(
    db: JobDatabase,
    tool_name: str,
    job_url: str,
    error: Exception,
) -> None:
    try:
        db.record_audit_event(
            "tool.failed",
            tool_name=tool_name,
            details={
                "job_url": job_url,
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
    except sqlite3.Error:
        log.exception("Could not audit failed tool call %s for %s", tool_name, job_url)


@mcp.tool()
def evaluate_job_fit(job_url: str) -> dict[str, Any]:
    """Run deterministic matching and guarded local-LLM evaluation for a stored job.

    This saves an agent recommendation only. It never sets APPLIED/SKIPPED and
    never submits an application.
    """
    db = _open_db()
    try:
        return run_evaluation(job_url, db)
    except Exception as error:
        _record_failure(db, "job-agent.evaluate_job_fit", job_url, error)
        raise
    finally:
        db.close()


@mcp.tool()
def generate_cover_letter(
    job_url: str,
    candidate_name: str = "",
    use_factchecker: bool = False,
) -> dict[str, Any]:
    """Generate an evidence-grounded letter for a job recommended for review.

    Uses the configured Gemini API; the candidate profile and job details are
    sent to that configured provider. The generated letter is a draft requiring
    human review, not an application submission.
    """
    db = _open_db()
    try:
        return generate_letter(
            job_url,
            db,
            candidate_name=candidate_name,
            use_factchecker=use_factchecker,
        )
    except Exception as error:
        _record_failure(db, "job-agent.generate_cover_letter", job_url, error)
        raise
    finally:
        db.close()


@mcp.tool()
def get_application_review(job_url: str) -> dict[str, Any]:
    """Return stored job details, recommendation, and any generated letter for review."""
    db = _open_db()
    try:
        return build_review_packet(job_url, db)
    except Exception as error:
        _record_failure(db, "job-agent.get_application_review", job_url, error)
        raise
    finally:
        db.close()


@mcp.tool()
async def review_application(job_url: str, ctx: Context) -> dict[str, Any]:
    """Ask the human to record APPLIED/SKIPPED after reviewing the application packet.

    APPLIED is valid only after the person has submitted manually. This tool
    records feedback and does not open or submit an application form.
    """
    db = _open_db()
    try:
        packet = build_review_packet(job_url, db)
        job = packet["job"]
        decision = packet["agent_decision"] or {}
        recommendation = decision.get("verdict") or "No agent recommendation"
        prompt = (
            f"Record your reviewed decision for {job['title']} at {job['company']} "
            f"({job_url}). Agent recommendation: {recommendation}. "
            "This tool will only record your feedback. It will not open or submit "
            "an application. Choose APPLIED only if you submitted the application "
            "yourself outside this tool; choose SKIPPED to record that you declined "
            "the opportunity, or cancel to leave the job unchanged."
        )
        response = await ctx.elicit(prompt, HumanReviewResponse)
        if response.action != "accept" or response.data is None:
            return {
                "job_url": job_url,
                "recorded": False,
                "status": response.action,
                "application_submitted_by_tool": False,
            }
        if not response.data.confirmed:
            return {
                "job_url": job_url,
                "recorded": False,
                "status": "confirmation_declined",
                "application_submitted_by_tool": False,
            }
        return record_human_application_review(
            job_url,
            response.data.action,
            db,
            confirmed=response.data.confirmed,
            note=response.data.note,
        )
    except Exception as error:
        _record_failure(db, "job-agent.review_application", job_url, error)
        raise
    finally:
        db.close()


@mcp.tool()
def get_decision_feedback(limit: int = 20) -> list[dict[str, Any]]:
    """Return human APPLIED/SKIPPED decisions used as future evaluation examples."""
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    db = _open_db()
    try:
        return db.get_feedback_history(limit=limit)
    finally:
        db.close()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
