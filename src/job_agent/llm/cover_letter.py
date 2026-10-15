"""Milestone 3: Tailored Cover Letter Generator for APPLY Jobs.

Generates concise, evidence-backed cover letters matching a candidate's verified
skills and projects to target job postings.
"""

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional

from ollama import Client

from ..models import CandidateProfile, CoverLetter, FinalDecision, Job

log = logging.getLogger(__name__)

COVER_LETTER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "salutation": {"type": "string"},
        "hook": {"type": "string"},
        "technical_alignment": {"type": "string"},
        "call_to_action": {"type": "string"},
        "full_letter": {"type": "string"},
    },
    "required": [
        "salutation",
        "hook",
        "technical_alignment",
        "call_to_action",
        "full_letter",
    ],
}

SYSTEM_PROMPT = """\
You are an expert technical career coach and hiring specialist. The user's CV is attached in the project sources. Read it carefully to extract relevant experience, skills, and tone.
Write a short, human cover letter for the specific job decriptio based on user CV. Follow these rules strictly:

# CANDIDATE FACTS & CONSTRAINTS
- Use ONLY facts provided in the <candidate_profile>. Never invent past employers, fake projects, or unlisted credentials. dont pretend that all experience years are in data science, this is a trasition candidate

# LETTER REQUIREMENTS
- Length: 250 - 350 words total across 3 to 4 clear paragraphs.
- Tone: Confident, Write like a person, not a template. No buzzwords. No lists. Active voice and short sentences. Do not invent anything — use only what's in the provided CV. Avoid generic filler (e.g., "I am writing to express my enthusiastic interest in your esteemed company").
- Structure:
  1. Hook & Introduction: Clearly name the target position and company. State direct alignment with the team's core technical focus.
  2. Technical Fit & Evidence: Highlight 1-2 real projects from the candidate's background that directly address challenges/technologies stated in the job description.
  3. Call to Action & Sign-off: Professional closing inviting a conversation. dont add "[Attachment: CV of <candidate_name>]" at the end.

# OUTPUT
Return ONLY valid JSON matching the schema provided.
`full_letter` must be the complete, ready-to-send markdown text including salutation, body paragraphs, and sign-off.
"""


def slugify(text: str) -> str:
    """Convert text into a filesystem-safe slug."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "_", text)[:50]


class CoverLetterAgent:
    """Agent that produces role-specific cover letters using local Ollama."""

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        host: str = "http://localhost:11434",
        temperature: float = 0.3,
        num_ctx: int = 8192,
    ):
        self.client = Client(host=host)
        self.model = model
        self.temperature = temperature
        self.num_ctx = num_ctx

    def build_prompt(
        self,
        profile: CandidateProfile,
        job: Job,
        candidate_name: str,
        decision_context: Optional[FinalDecision] = None,
        max_description_chars: int = 5000,
    ) -> str:
        """Render prompt with candidate details and job posting."""
        profile_dict = profile.to_dict()
        profile_dict["name"] = candidate_name or profile.name or "Candidate"

        job_desc = job.description
        if len(job_desc) > max_description_chars:
            job_desc = job_desc[:max_description_chars] + " …[truncated]"

        job_data = {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "work_model": job.work_model,
            "description": job_desc,
        }

        context_data: Dict[str, Any] = {}
        if decision_context:
            context_data = {
                "decision": decision_context.decision,
                "confidence": decision_context.confidence,
                "rationale": decision_context.rationale,
            }
            if decision_context.llm:
                context_data["reasons_for"] = decision_context.llm.reasons_for
                context_data["role_fit"] = decision_context.llm.role_fit

        return (
            "Generate a tailored cover letter for this application.\n\n"
            f"<candidate_profile>\n{json.dumps(profile_dict, ensure_ascii=False, indent=2)}\n</candidate_profile>\n\n"
            f"<target_job>\n{json.dumps(job_data, ensure_ascii=False, indent=2)}\n</target_job>\n\n"
            f"<screening_context>\n{json.dumps(context_data, ensure_ascii=False, indent=2)}\n</screening_context>\n\n"
            "Return the JSON cover letter now."
        )

    def generate(
        self,
        profile: CandidateProfile,
        job: Job,
        candidate_name: str = "",
        decision_context: Optional[FinalDecision] = None,
        save_path: str = ""
    ):
        """Call Ollama and return a populated CoverLetter instance."""
        prompt = self.build_prompt(profile, job, candidate_name, decision_context)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        response = self.client.chat(
            model=self.model,
            messages=messages,
            format=COVER_LETTER_SCHEMA,
            options={"temperature": self.temperature, "num_ctx": self.num_ctx},
        )

        content = response["message"]["content"]
        data = json.loads(content)
        # save cover letter
        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(data["full_letter"], encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate tailored cover letters for APPLY jobs.")
    parser.add_argument("--decisions", default="data/decisions.json", help="Path to decisions.json")
    parser.add_argument("--profile", default="data/candidate_profile.json", help="Path to candidate profile")
    parser.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs.db")
    parser.add_argument("--out-dir", default="data/cover_letters", help="Output directory for cover letters")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model name")
    parser.add_argument("--candidate-name", default="Efrat", help="Candidate full name")
    parser.add_argument("--max-jobs", type=int, default=None, help="Optional limit on number of letters to generate")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # 1. Load Profile
    profile_data = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    profile = CandidateProfile.from_dict(profile_data)
    candidate_name = args.candidate_name or profile.name or "Efrat"

    # 2. Load Decisions and filter for APPLY
    decisions_path = Path(args.decisions)
    if not decisions_path.exists():
        print(f"Error: Decisions file not found at {decisions_path}. Run job_agent.llm.run_decisions first.")
        return

    decisions_data = json.loads(decisions_path.read_text(encoding="utf-8"))
    apply_jobs: List[Dict[str, Any]] = [d for d in decisions_data if d.get("decision") == "APPLY"]

    if not apply_jobs:
        print("No 'APPLY' jobs found in decisions file.")
        return

    if args.max_jobs:
        apply_jobs = apply_jobs[: args.max_jobs]

    print(f"Found {len(apply_jobs)} 'APPLY' jobs ready for cover letter generation.\n")

    # 3. Load full descriptions from database
    url_to_job: Dict[str, Dict[str, Any]] = {}
    db_path = Path(args.db)
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT url, title, company, location, work_model, description FROM jobs").fetchall()
            for r in rows:
                url_to_job[r["url"]] = dict(r)

    # 4. Initialize Agent
    agent = CoverLetterAgent(model=args.model)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated_letters: List[Dict[str, Any]] = []

    for i, dec in enumerate(apply_jobs, start=1):
        job_url = dec.get("job_url", "")
        title = dec.get("title", "Job")
        company = dec.get("company", "Company")

        # Get job data
        db_job = url_to_job.get(job_url, {})
        job = Job(
            url=job_url,
            title=title,
            company=company,
            description=db_job.get("description", ""),
            location=db_job.get("location", ""),
            work_model=db_job.get("work_model", ""),
        )

        decision_obj = FinalDecision(
            job_url=job_url,
            title=title,
            company=company,
            decision=dec.get("decision", "APPLY"),
            confidence=dec.get("confidence", 0),
            rationale=dec.get("rationale", ""),
        )

        print(f"[{i}/{len(apply_jobs)}] Generating cover letter for: {title} @ {company} ...", flush=True)

        try:
            letter = agent.generate(profile, job, candidate_name=candidate_name, decision_context=decision_obj)

            # Save markdown file
            slug = f"{slugify(company)}_{slugify(title)}"
            file_name = f"{slug}.md"
            file_path = out_dir / file_name

            file_content = letter.content

            file_path.write_text(file_content, encoding="utf-8")
            letter.file_path = str(file_path)
            generated_letters.append(letter.to_dict())

            print(f"    -> Saved to: {file_path}")
            print(f"    -> Subject: {letter.subject_line}\n")

        except Exception as e:
            log.error("Failed to generate cover letter for %s: %s", title, e)
            print(f"    -> ERROR: {e}\n")

    # 5. Save manifest
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(generated_letters, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Completed! {len(generated_letters)} cover letters saved to {out_dir}/ (manifest: {manifest_path})")


if __name__ == "__main__":
    main()
