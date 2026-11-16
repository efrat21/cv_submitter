"""M4 cover-letter generation for jobs recommended for human review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from job_agent.config import DATA_DIR
from job_agent.database import JobDatabase
from job_agent.llm.cover_letter import CoverLetterAgent, slugify
from job_agent.models import CandidateProfile, FinalDecision
from job_agent.mcp_servers._workflow_common import load_job, load_profile


def generate_cover_letter(
    job_url: str,
    db: JobDatabase,
    *,
    candidate_name: str = "",
    use_factchecker: bool = False,
    output_dir: Path | None = None,
    profile_data: dict[str, Any] | None = None,
    agent: CoverLetterAgent | None = None,
) -> dict[str, Any]:
    """Generate and save a letter only for an APPLY/RECOMMENDED job."""
    row = db.connection.execute(
        """
        SELECT verdict, rationale, confidence
        FROM job_decisions
        WHERE job_url = ?
        """,
        (job_url,),
    ).fetchone()
    if row is None or row[0] not in {"APPLY", "RECOMMENDED"}:
        raise ValueError(
            "Cover letters require an APPLY recommendation; evaluate the job first"
        )

    profile_raw = profile_data if profile_data is not None else load_profile()
    profile = CandidateProfile.from_dict(profile_raw)
    job = load_job(db, job_url)
    final_decision = FinalDecision(
        job_url=job.url,
        title=job.title,
        company=job.company,
        decision="APPLY",
        confidence=int(row[2] or 0),
        rationale=row[1] or "Previously recommended for human review",
    )
    destination = output_dir or DATA_DIR / "cover_letters"
    path = destination / f"{slugify(job.company)}_{slugify(job.title)}.md"
    cover_letter_agent = agent or CoverLetterAgent()
    content = cover_letter_agent.run(
        profile=profile,
        job=job,
        candidate_name=candidate_name or profile.name,
        decision_context=final_decision,
        save_path=path,
        use_factchecker=use_factchecker,
    )
    if not content.strip():
        raise ValueError(f"Cover-letter generator returned empty content for {job_url}")
    if not path.is_file():
        raise RuntimeError(f"Cover-letter generator did not save its output: {path}")

    db.record_cover_letter_path(job_url, str(path))
    db.record_audit_event(
        "cover_letter.generated",
        tool_name="job-agent.generate_cover_letter",
        details={
            "job_url": job_url,
            "file_path": str(path),
            "model": cover_letter_agent.model,
            "fact_checked": use_factchecker,
        },
    )
    return {
        "job_url": job_url,
        "file_path": str(path),
        "content": content,
        "human_review_required": True,
    }
