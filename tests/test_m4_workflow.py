from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from job_agent.database import JobDatabase
from job_agent.llm.cover_letter import CoverLetterAgent
from job_agent.llm.decision_agent import DecisionAgent
from job_agent.models import (
    CandidatePreferences,
    CandidateProfile,
    FinalDecision,
    Job,
    MatchResult,
)
from job_agent.mcp_servers import application_review, cover_letters, evaluator, host


JOB_URL = "https://jobs.example/jobs/101"
PROFILE = {
    "name": "Test Candidate",
    "skills": {
        "Python": [{"context": "professional", "text": "Built Python services."}],
        "Machine Learning": [{"context": "professional", "text": "Built ML systems."}],
    },
}
PREFERENCES = {
    "target_roles": ["AI Engineer"],
    "locations": ["Remote", "Sofia"],
    "work_models": ["Remote", "Hybrid"],
}


class StubDecisionAgent(DecisionAgent):
    def __init__(self, *, error: str = "") -> None:
        self.model = "test-model"
        self.error = error
        self.history = None

    def decide(
        self,
        profile: CandidateProfile,
        preferences: CandidatePreferences,
        match: MatchResult,
        history: list[dict[str, object]] | None = None,
    ) -> FinalDecision:
        self.history = history
        return FinalDecision(
            job_url=match.job.url,
            title=match.job.title,
            company=match.job.company,
            decision="APPLY",
            confidence=91,
            rationale="Relevant Python and ML experience.",
            overrides=[],
            error=self.error,
        )


class StubCoverLetterAgent(CoverLetterAgent):
    def __init__(self) -> None:
        self.model = "test-letter-model"

    def run(
        self,
        profile: CandidateProfile,
        job: Job,
        candidate_name: str = "",
        decision_context: FinalDecision | None = None,
        save_path: str | Path = "",
        use_factchecker: bool = False,
    ) -> str:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        Path(save_path).write_text("Evidence-based draft letter.", encoding="utf-8")
        return "Evidence-based draft letter."


def _database(tmp_path: Path) -> JobDatabase:
    db = JobDatabase(tmp_path / "jobs.db")
    db.save_job(
        {
            "url": JOB_URL,
            "title": "AI Engineer",
            "company": "Example Corp",
            "location": "Sofia",
            "work_model": "Hybrid",
            "tags": ["Python", "Machine Learning"],
            "description": "Build Python and machine learning systems.",
        }
    )
    return db


def test_evaluation_persists_recommendation_without_changing_human_action(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path)
    db.save_job(
        {
            "url": "https://jobs.example/jobs/100",
            "title": "Earlier Role",
            "company": "Other Corp",
            "description": "Earlier experience",
            "tags": [],
        }
    )
    db.record_action("https://jobs.example/jobs/100", "SKIPPED", "Not a fit")
    agent = StubDecisionAgent()

    try:
        result = evaluator.evaluate_job_fit(
            JOB_URL,
            db,
            profile_data=PROFILE,
            preferences_data=PREFERENCES,
            agent=agent,
        )

        assert result["decision"]["decision"] == "APPLY"
        assert result["human_review_required"] is True
        assert result["application_submitted"] is False
        assert agent.history[0]["action"] == "SKIPPED"
        assert db.get_action(JOB_URL) is None
        stored = db.connection.execute(
            "SELECT verdict, confidence, model FROM job_decisions WHERE job_url = ?",
            (JOB_URL,),
        ).fetchone()
        assert stored == ("APPLY", 91, "test-model")
        assert db.connection.execute(
            "SELECT COUNT(*) FROM audit_log WHERE event_type = 'evaluation.completed'"
        ).fetchone()[0] == 1
    finally:
        db.close()


def test_evaluation_errors_are_not_saved_as_skip(tmp_path: Path) -> None:
    db = _database(tmp_path)
    agent = StubDecisionAgent(error="Ollama unavailable")
    try:
        with pytest.raises(RuntimeError, match="Ollama unavailable"):
            evaluator.evaluate_job_fit(
                JOB_URL,
                db,
                profile_data=PROFILE,
                preferences_data=PREFERENCES,
                agent=agent,
            )
        assert db.connection.execute(
            "SELECT COUNT(*) FROM job_decisions WHERE job_url = ?", (JOB_URL,)
        ).fetchone()[0] == 0
        assert db.get_action(JOB_URL) is None
    finally:
        db.close()


def test_cover_letter_requires_apply_recommendation_and_persists_path(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path)
    output_dir = tmp_path / "letters"
    try:
        with pytest.raises(ValueError, match="evaluate the job first"):
            cover_letters.generate_cover_letter(
                JOB_URL,
                db,
                output_dir=output_dir,
                profile_data=PROFILE,
                agent=StubCoverLetterAgent(),
            )

        db.record_evaluation(
            JOB_URL,
            verdict="APPLY",
            rationale="Good match",
            model="test-model",
            confidence=91,
            overrides=[],
            details={},
        )
        result = cover_letters.generate_cover_letter(
            JOB_URL,
            db,
            candidate_name="Test Candidate",
            output_dir=output_dir,
            profile_data=PROFILE,
            agent=StubCoverLetterAgent(),
        )

        assert result["content"] == "Evidence-based draft letter."
        assert result["human_review_required"] is True
        assert Path(result["file_path"]).read_text(encoding="utf-8") == result["content"]
        stored_path = db.connection.execute(
            "SELECT cover_letter_path FROM job_decisions WHERE job_url = ?",
            (JOB_URL,),
        ).fetchone()[0]
        assert stored_path == result["file_path"]
    finally:
        db.close()


def test_cover_letter_agent_run_returns_the_saved_content(
    tmp_path: Path,
) -> None:
    class StubGenerator(CoverLetterAgent):
        def __init__(self) -> None:
            pass

        def generate(self, prompt: str) -> str:
            return "Generated letter"

    agent = StubGenerator()
    path = tmp_path / "letter.md"
    content = agent.run(
        profile=CandidateProfile(name="Test Candidate"),
        job=Job(
            url=JOB_URL,
            title="AI Engineer",
            company="Example Corp",
            description="Build AI systems.",
        ),
        save_path=path,
    )
    assert content == "Generated letter"
    assert path.read_text(encoding="utf-8") == content


def test_application_review_requires_confirmation_and_updates_feedback(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path)
    try:
        packet = application_review.get_application_review(JOB_URL, db)
        assert packet["human_review_required"] is True
        assert packet["application_submitted_by_tool"] is False
        assert db.get_action(JOB_URL) is None

        with pytest.raises(ValueError, match="Human confirmation is required"):
            application_review.record_human_application_review(
                JOB_URL, "SKIPPED", db, confirmed=False
            )
        assert db.get_action(JOB_URL) is None

        result = application_review.record_human_application_review(
            JOB_URL,
            "SKIPPED",
            db,
            confirmed=True,
            note="Role scope is not a fit",
        )
        assert result["application_submitted_by_tool"] is False
        assert db.get_action(JOB_URL) == "SKIPPED"
        assert db.get_feedback_history(limit=1)[0]["action_note"] == "Role scope is not a fit"
        assert db.connection.execute(
            """
            SELECT actor, approval_required, approved
            FROM audit_log
            WHERE event_type = 'application.reviewed'
            """
        ).fetchone() == ("human", 1, 1)
    finally:
        db.close()


def test_mcp_review_cancellation_does_not_change_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _database(tmp_path)
    monkeypatch.setattr(host, "_open_db", lambda: JobDatabase(db.path))

    class DeclinedContext:
        async def elicit(self, message, schema):
            assert JOB_URL in message
            return SimpleNamespace(action="cancel", data=None)

    try:
        result = asyncio.run(host.review_application(JOB_URL, DeclinedContext()))
        assert result["recorded"] is False
        assert result["status"] == "cancel"
        assert db.get_action(JOB_URL) is None
    finally:
        db.close()


def test_record_action_for_unknown_url_has_no_side_effects(tmp_path: Path) -> None:
    db = _database(tmp_path)
    try:
        assert not db.record_action("https://jobs.example/missing", "SKIPPED")
        assert db.connection.execute(
            "SELECT COUNT(*) FROM job_status_history WHERE job_url = ?",
            ("https://jobs.example/missing",),
        ).fetchone()[0] == 0
        assert db.connection.execute(
            "SELECT COUNT(*) FROM job_decisions WHERE job_url = ?",
            ("https://jobs.example/missing",),
        ).fetchone()[0] == 0
    finally:
        db.close()
