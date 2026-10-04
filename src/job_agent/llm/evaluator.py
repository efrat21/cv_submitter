import argparse
import json
import re
import sqlite3
from pathlib import Path


# These are preliminary rules, not extracted job requirements.
ROLE_RULES = {
    "AI-native Software Engineer": {
        "core": [
            "Python", "LLMs", "AI Agents",
            "REST APIs", "GitHub Copilot",
        ],
        "related": [
            "RAG", "MCP", "Docker", "Project Management",
        ],
    },
    "AI-native Engineering Manager": {
        "core": [
            "AI Agents", "Project Management", "Technical Leadership",
        ],
        "related": [
            "Python", "LLMs", "GitHub Copilot",
            "Research and Development",
        ],
    },
    "Senior Operations Research Engineer": {
        "core": ["Python", "Statistics", "Data Analysis"],
        "related": [
            "Machine Learning", "NumPy", "Research and Development",
        ],
    },
    "Senior AI Engineer (Agentic AI & ML)": {
        "core": [
            "Python", "Machine Learning", "Deep Learning", "AI Agents",
        ],
        "related": ["PyTorch", "TensorFlow", "LLMs", "RAG", "MCP"],
    },
    "AI Evaluation Engineer": {
        "core": ["Python", "Machine Learning", "Data Analysis"],
        "related": ["Statistics", "LLMs", "Research and Development"],
    },
    "Senior Data Scientist": {
        "core": [
            "Python", "Machine Learning", "Statistics", "Data Analysis",
        ],
        "related": [
            "PyTorch", "TensorFlow", "scikit-learn", "Pandas", "SQL",
        ],
    },
    "AI Automation Engineer": {
        "core": ["Python", "AI Agents", "REST APIs"],
        "related": ["LLMs", "RAG", "GitHub Copilot", "Project Management"],
    },
    "MLOPS ENGINEER (m/f/d)": {
        "core": ["Python", "Machine Learning"],
        "related": ["Docker", "Azure", "CI/CD", "Kubernetes"],
    },
    "Senior AI Engieer – Voice & Agentic Systems": {
        "core": ["Python", "AI Agents", "LLMs"],
        "related": ["REST APIs", "RAG", "MCP"],
    },
    "AI PLATFORM AUTOMATION ENGINEER (m/f/d)": {
        "core": ["Python", "REST APIs", "AI Agents"],
        "related": ["Docker", "Azure", "CI/CD", "GitHub Copilot", "LLMs"],
    },
}


# Evidence weights: presence is not the same as proficiency.
CONTEXT_WEIGHTS = {
    "professional": 1.00,
    "professional_project": 0.75,
    "learning": 0.35,
    "education": 0.30,
    "other": 0.10,
}

# Some technologies deserve explicit verification when mentioned
# in a job description but not supported by the CV.
CHECK_SKILLS = [
    "Kubernetes",
    "Docker",
    "MCP",
    "CI/CD",
    "LangGraph",
    "CrewAI",
    "PydanticAI",
    "Vector Databases",
    "GitHub Copilot",
]


def load_profile(path):
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def get_evidence(profile, skill):
    """Support the current structured evidence and older profile formats."""
    items = profile.get("skills", {}).get(skill, [])

    if not isinstance(items, list):
        return []

    normalized = []

    for item in items:
        if isinstance(item, dict):
            context = item.get("context", "other")
            normalized.append({
                "context": context,
                "text": item.get("text", ""),
                "weight": CONTEXT_WEIGHTS.get(context, 0.10),
            })
        else:
            # Older profiles may store context names as strings.
            context = str(item)
            normalized.append({
                "context": context,
                "text": "",
                "weight": CONTEXT_WEIGHTS.get(context, 0.10),
            })

    return normalized


def best_evidence(profile, skill):
    items = get_evidence(profile, skill)

    if not items:
        return None

    return max(items, key=lambda item: item["weight"])


def get_role_rules(title):
    """Exact title match first; then try a conservative substring match."""
    if title in ROLE_RULES:
        return ROLE_RULES[title]

    for known_title, rules in ROLE_RULES.items():
        if known_title.lower() in title.lower():
            return rules

    return {
        "core": ["Python", "Machine Learning"],
        "related": ["Data Analysis", "LLMs", "AI Agents"],
    }


def extract_year_requirements(description):
    """Find explicit year requirements; this is a heuristic, not NLP."""
    patterns = [
        r"(\d+)\s*\+\s*years?",
        r"at least\s+(\d+)\s+years?",
        r"minimum of\s+(\d+)\s+years?",
        r"(\d+)\s+years? of experience",
    ]

    values = []

    for pattern in patterns:
        for match in re.finditer(pattern, description, re.IGNORECASE):
            values.append(int(match.group(1)))

    return sorted(set(values))


def assess_job(job, profile):
    title = job["title"]
    description = job.get("description") or ""
    description_lower = description.lower()
    rules = get_role_rules(title)

    core_results = []
    related_results = []
    missing_core = []
    missing_related = []
    evidence_summary = {}

    # Core skills are worth 2 points; related skills are worth 1.
    # Evidence strength scales the points actually earned.
    possible_points = (
        2 * len(rules["core"]) + len(rules["related"])
    )
    earned_points = 0.0

    for skill in rules["core"]:
        item = best_evidence(profile, skill)

        if item is None:
            missing_core.append(skill)
            core_results.append({
                "skill": skill,
                "status": "not_established",
                "evidence_context": [],
            })
            continue

        earned_points += 2 * item["weight"]
        evidence = get_evidence(profile, skill)
        contexts = sorted({entry["context"] for entry in evidence})

        core_results.append({
            "skill": skill,
            "status": "evidence_found",
            "evidence_context": contexts,
            "strength": item["weight"],
        })

        evidence_summary[skill] = evidence

    for skill in rules["related"]:
        item = best_evidence(profile, skill)

        if item is None:
            missing_related.append(skill)
            related_results.append({
                "skill": skill,
                "status": "not_established",
                "evidence_context": [],
            })
            continue

        earned_points += item["weight"]
        evidence = get_evidence(profile, skill)
        contexts = sorted({entry["context"] for entry in evidence})

        related_results.append({
            "skill": skill,
            "status": "evidence_found",
            "evidence_context": contexts,
            "strength": item["weight"],
        })

        evidence_summary[skill] = evidence

    score = round(
        100 * earned_points / possible_points
    ) if possible_points else 0

    # Recommendations are triage priorities, never automatic applications.
    if score >= 65:
        recommendation = "HIGH_PRIORITY_REVIEW"
    elif score >= 40:
        recommendation = "REVIEW"
    else:
        recommendation = "LOW_PRIORITY_REVIEW"

    verification_flags = []

    years = extract_year_requirements(description)

    if years:
        verification_flags.append(
            "Job description mentions a year-of-experience "
            f"requirement: {', '.join(map(str, years))} year(s). "
            "Verify the type of experience required."
        )

    if "senior" in title.lower() or "manager" in title.lower():
        verification_flags.append(
            "Check seniority, scope, and role-specific responsibilities."
        )

    for skill in CHECK_SKILLS:
        if (
            skill.lower() in description_lower
            and not get_evidence(profile, skill)
        ):
            verification_flags.append(
                f"{skill} is mentioned in the job description, "
                "but evidence was not found in the CV."
            )

    # These are only keyword signals, not a reliable list of mandatory
    # requirements. The actual job description still needs review.
    requirement_signals = []

    for phrase in [
        "required", "must have", "requirements",
        "what you bring", "experience with",
    ]:
        if phrase in description_lower:
            requirement_signals.append(phrase)

    return {
        "id": job["id"],
        "title": title,
        "company": job["company"],
        "url": job["url"],
        "location": job["location"],
        "work_model": job["work_model"],
        "match_score": score,
        "recommendation": recommendation,
        "core_assessment": core_results,
        "related_assessment": related_results,
        "core_missing": missing_core,
        "related_missing": missing_related,
        "evidence": evidence_summary,
        "verification_flags": verification_flags,
        "description_signals": requirement_signals,
        "scoring_method": {
            "core_skill_weight": 2,
            "related_skill_weight": 1,
            "evidence_weights": CONTEXT_WEIGHTS,
            "warning": (
                "Preliminary rule-based score. It is not a probability "
                "of getting an interview and does not replace review "
                "of mandatory requirements."
            ),
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Rank saved jobs against a structured CV profile."
    )
    parser.add_argument(
        "--profile",
        default="data/candidate_profile.json",
    )
    parser.add_argument(
        "--db",
        default="data/jobs.db",
    )
    parser.add_argument(
        "--output",
        default="data/match_results.json",
    )
    args = parser.parse_args()

    profile = load_profile(args.profile)

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT
                id, title, company, url,
                location, work_model, description
            FROM jobs
            """
        ).fetchall()
    finally:
        connection.close()

    results = [
        assess_job(dict(row), profile)
        for row in rows
    ]

    # Highest-priority jobs appear first.
    results.sort(
        key=lambda result: (
            result["match_score"],
            result["title"].lower(),
        ),
        reverse=True,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Jobs evaluated: {len(results)}")
    print(f"Results saved to: {output_path}")
    print("\nRanked jobs:\n")

    for rank, result in enumerate(results, start=1):
        print(
            f"{rank}. [{result['match_score']}/100] "
            f"{result['recommendation']}"
        )
        print(
            f"   {result['title']} — {result['company']}"
        )
        print(
            "   Core evidence: "
            + (
                ", ".join(
                    item["skill"]
                    for item in result["core_assessment"]
                    if item["status"] == "evidence_found"
                )
                or "None"
            )
        )
        print(
            "   Core not established: "
            + (", ".join(result["core_missing"]) or "None")
        )

        for flag in result["verification_flags"]:
            print(f"   Check: {flag}")

        print(f"   {result['url']}\n")


if __name__ == "__main__":
    main()