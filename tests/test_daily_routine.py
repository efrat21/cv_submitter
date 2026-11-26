from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from job_agent import daily_routine
from job_agent.database import JobDatabase
from job_agent.models import CandidateProfile


def test_daily_routine_backfills_only_missing_recommended_letters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db = JobDatabase(tmp_path / "jobs.db")
    recommended_urls = [
        "https://jobs.example/recommended-1",
        "https://jobs.example/recommended-2",
    ]
    for url in [*recommended_urls, "https://jobs.example/skipped"]:
        db.save_job(
            {
                "url": url,
                "title": "Engineer",
                "company": url.rsplit("/", 1)[-1],
                "description": "Python role",
            }
        )
    for url in recommended_urls:
        db.record_action(url, "RECOMMENDED")
    db.record_action("https://jobs.example/skipped", "NOT_RECOMMENDED")

    existing_letter = tmp_path / "letters" / "recommended-2.md"
    existing_letter.parent.mkdir()
    existing_letter.write_text("Existing letter", encoding="utf-8")
    monkeypatch.setattr(
        daily_routine,
        "letter_path_for",
        lambda job: tmp_path / "letters" / f"{job.company}.md",
    )
    generated_urls = []

    class StubCoverLetterAgent:
        def run(self, *, job, save_path, **kwargs):
            generated_urls.append(job.url)
            path = Path(save_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Generated letter", encoding="utf-8")
            return "Generated letter"

    monkeypatch.setattr(daily_routine, "CoverLetterAgent", StubCoverLetterAgent)
    args = SimpleNamespace(
        no_cover_letters=False,
        name="Candidate",
        profile="unused-profile.json",
    )
    profile = CandidateProfile(name="Candidate")

    try:
        result = daily_routine.generate_missing_cover_letters(args, db, profile)

        assert result == {"generated": 1, "errors": 0}
        assert generated_urls == [recommended_urls[0]]
        assert (tmp_path / "letters" / "recommended-1.md").is_file()

        second_result = daily_routine.generate_missing_cover_letters(args, db, profile)
        assert second_result == {"generated": 0, "errors": 0}
        assert generated_urls == [recommended_urls[0]]
    finally:
        db.close()
