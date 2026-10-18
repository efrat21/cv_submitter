"""Milestone 3: Tailored Cover Letter Generator for APPLY Jobs.

Generates concise, evidence-backed cover letters matching a candidate's verified
skills and projects to target job postings.
"""
import time
import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional

from ..models import CandidateProfile, CoverLetter, FinalDecision, Job

log = logging.getLogger(__name__)
from dotenv import load_dotenv
load_dotenv()
from google import genai
from google.genai import types 

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
SYSTEM_PROMPT_writer = """Write a concise, personalized cover letter using the candidate profile and job description.

CRITICAL: The candidate profile is the ONLY source of facts about the candidate. The job description describes the employer's needs, NOT the candidate's experience.

FACTUAL RULES:
- Before mentioning any skill, technology, project, responsibility, or achievement, verify that it is explicitly supported by the candidate profile.
- NEVER assume experience with a technology just because it appears in the job description. For example, if graph analytics or fraud detection is not explicitly documented in the profile, do not mention it as candidate experience.
- Never invent projects, business outcomes, metrics, or claims of impact.
- Do not turn general skills into specific project experience.
- Accurately distinguish total career experience from AI/ML experience.
- When a requirement is not supported, identify the closest relevant, documented transferable experience instead. Do not pretend it is equivalent experience.

WRITING:
- Write 2–3 short paragraphs, under 180 words.
- Open with the candidate's strongest verified qualification for this specific role.
- Select 2–3 concrete examples from the profile and explain their relevance.
- Highlight the combination of hands-on ML development and technical R&D leadership where relevant.
- Be direct, natural, confident, and specific.
- Avoid clichés, generic enthusiasm, buzzwords, repetition, and exaggerated claims.
- Close with one brief invitation to discuss the opportunity.

OUTPUT: Return ONLY valid JSON matching the supplied schema. The full_letter field must contain the complete, ready-to-send letter. Do not include commentary or extra fields.
"""


SYSTEM_PROMPT_factcheck = """Cover Letter Fact-Checking & Alignment Assistant

## ROLE & OBJECTIVE
You are an expert HR Analyst and Technical Copyeditor. Your primary task is to review a candidate's Cover Letter against their provided Profile (Resume/CV, LinkedIn summary, or bio). 

You must identify and remove or modify any claims, achievements, skills, titles, or metrics in the Cover Letter that are **not supported by or derivable from** the Candidate Profile. Once verified, you will rewrite and retune the Cover Letter so it remains professional, engaging, and polished.

---

## INPUTS
You will receive two pieces of text:
1. **[CANDIDATE PROFILE]**: The ground-truth source of facts, employment history, skills, and accomplishments.
2. **[COVER LETTER]**: The original document draft to be verified and tuned.

---

## VERIFICATION & AUDIT RULES

1. **Strict Ground-Truth Adherence**:
   - **Supported Claim**: A statement that directly matches facts in the Profile or is a reasonable, direct inference from them (e.g., claiming "experience in data analysis" when the Profile lists 5 years as a Data Analyst).
   - **Unsupported Claim (Fact/Metric/Title)**: Any specific tool, degree, company name, project result, key performance indicator (KPI), percentage, or title mentioned in the Cover Letter that is missing from the Profile.
   - **Exaggerated Claim**: Framing an individual entry-level task in the Profile as leading or directing a team.

2. **Handling Unsupported Claims**:
   - **Remove**: Erase specific metrics, dates, companies, or tools that do not exist in the Profile.
   - **Softened Alternative**: If a statement conveys a relevant soft skill or enthusiasm that fits the candidate's general background, reframe it into a broader, factual statement without false specifics.

3. **Retuning Guidelines**:
   - Ensure seamless narrative flow after removing unsupported statements.
   - Maintain a professional, confident, and professional tone.
   - Fix grammar, active voice, and formatting to present the candidate in the strongest authentic light.
   - **Do NOT invent or extrapolate** new factual details to fill gaps.

---

## WORKFLOW

1. **Audit Phase**: Read both inputs thoroughly. List all discrepancies, unsupported claims, or exaggerations found in the Cover Letter.
2. **Correction Phase**: Remove or modify the identified sections.
3. **Refinement Phase**: Re-craft the sentences surrounding the edits so the Cover Letter flows naturally and maintains high narrative impact.

---

## OUTPUT FORMAT

Always structure your response into the following two sections:

### 1. Audit Summary & Discrepancy Log
Provide a brief breakdown of what was modified or removed and why:
* **Removed / Modified Claim**: "[Original text from Cover Letter]"
  * **Reason**: [Explain why it is unsupported based on the Profile]
  * **Action Taken**: [Removed completely / Reworded to match factual background]

*(If no discrepancies are found, explicitly state: "All claims in the cover letter are supported by the profile.")*

---

### 2. Revised Cover Letter
Provide the final, fully corrected, and retuned Cover Letter text ready for use.
"""
def slugify(text: str) -> str:
    """Convert text into a filesystem-safe slug."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "_", text)[:50]


class FactCheckerAgent:
    def __init__(
        self,
        model: str = "gemini-3.8-flash",
        temperature: float = 0.3,
        num_ctx: int = 8192,
    ):
        self.client = genai.Client()
        self.model = model
        self.temperature = temperature
        self.num_ctx = num_ctx

    def check(
        self,
        profile: CandidateProfile,
        cover_letter: CoverLetter,
    ) -> bool:
        
        print(
            f"[TIMING] fact-check started | model={self.model} "
            f"| prompt_chars={len(prompt)} | num_ctx={self.num_ctx}",
            flush=True,
        )
   
        start = time.perf_counter()
        breakpoint()
        response = self.client.create(
            model=self.model,
            contents= f"Profile:\n{profile}\n\nCover Letter:\n{cover_letter}",
            format=COVER_LETTER_SCHEMA,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT_factcheck,
                temperature=self.temperature,
            ),
        )
        print(
            f"[TIMING] fact-check call completed in "
            f"{time.perf_counter() - start:.1f}s",
            flush=True,
        )
        content = strip_cover_letter(response.text)
        return content

class CoverLetterAgent:
    """Agent that produces role-specific cover letters using local Ollama."""

    def __init__(
        self,
        model: str = "gemini-3.8-flash",
        temperature: float = 0.3,
        num_ctx: int = 8192,
    ):
        self.client = genai.Client()
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
            # f"<screening_context>\n{json.dumps(context_data, ensure_ascii=False, indent=2)}\n</screening_context>\n\n"
            "Return the JSON cover letter now."
        )

    def generate(
        self,
        prompt: str,
    ):
        """Call LLM (LLama or Gemini) and return a populated CoverLetter instance."""

        print(
            f"[TIMING] Cover letter started | model={self.model} "
            f"| prompt_chars={len(prompt)} | num_ctx={self.num_ctx}",
            flush=True,
        )
        start = time.perf_counter()

        interaction = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT_writer,
            temperature=self.temperature,
            ),
        )

        print(
            f"[TIMING] cover-letter call completed in "
            f"{time.perf_counter() - start:.1f}s",
            flush=True,
        )
        content = strip_cover_letter(interaction)
        return content

    def run(
        self,
        profile: CandidateProfile,
        job: Job,
        candidate_name: str = "",
        decision_context: Optional[FinalDecision] = None,
        save_path: str = "",
        use_factchecker: bool = False
    ):
        # Build the prompt for the cover letter
        prompt = self.build_prompt(profile, job, candidate_name, decision_context)
        # Generate the precheck cover letter
        precheck_cover_letter = self.generate(prompt)
        if use_factchecker:
            # Fact-check and correct the cover letter
            fact_check_agent = FactCheckerAgent()
            cover_letter = fact_check_agent.check(profile, precheck_cover_letter) 
        else:
            cover_letter = precheck_cover_letter
        # save cover letter
        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(cover_letter, encoding="utf-8")


def strip_cover_letter(response:types.GenerateContentResponse):
    import json
    import re

    content = response.text.strip()

    # 1. Strip out markdown code blocks (```json ... ```) if Gemini includes them
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    # 2. Parse the clean JSON string into a Python dictionary
    data = json.loads(content)

    # 3. Extract just the letter text
    letter_text = data["full_letter"]
    return letter_text


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
