import argparse
import json
import re
from pathlib import Path


SKILL_ALIASES = {
    "Python": ["python"],
    "FastAPI": ["fastapi"],
    "Machine Learning": [
        "machine learning", "ml pipeline", "ml models",
    ],
    "Deep Learning": [
        "deep learning", "cnn", "lstm", "gru", "autoencoder",
    ],
    "PyTorch": ["pytorch"],
    "TensorFlow": ["tensorflow"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Data Analysis": [
        "data analysis", "data analytics",
        "data cleaning", "feature engineering",
    ],
    "Statistics": ["statistics", "statistical modeling"],
    "Signal Processing": ["signal processing"],
    "RAG": ["retrieval-augmented generation", "rag-based"],
    "LLMs": ["large language model", "llm", "chatgpt", "gemini"],
    "AI Agents": ["ai agents", "agentic ai", "autonomous agents"],
    "MCP": ["model context protocol", "mcp"],
    "GitHub Copilot": ["github copilot"],
    "Azure": ["azure", "document intelligence"],
    "Docker": ["docker"],
    "Redis": ["redis"],
    "MongoDB": ["mongodb"],
    "SQL": ["sql", "relational data infrastructure"],
    "REST APIs": ["rest api", "backend services", "fastapi"],
    "Project Management": [
        "project management", "project controls", "roadmap planning",
    ],
    "Technical Leadership": [
        "technical project management", "multidisciplinary",
        "team productivity", "mentored a team",
    ],
    "Research and Development": [
        "r&d", "research", "feasibility analysis", "algorithm development",
    ],
    "Jira": ["jira"],
    "Power BI": ["power bi"],
    "CI/CD": ["ci/cd"],
    "Kubernetes": ["kubernetes"],
    "LangGraph": ["langgraph"],
    "CrewAI": ["crewai"],
    "PydanticAI": ["pydanticai"],
    "Vector Databases": ["vector database", "vector databases"],
}


def detect_section(line):
    text = line.strip().lower()

    # Employer headings start a professional-experience section.
    if "tensor technologies" in text:
        return "professional"

    if "rafael advanced defense systems" in text:
        return "professional"

    if text == "selected projects:":
        return "professional_project"

    if text.rstrip(":") in {
        "technical project management",
        "cross-functional & stakeholder leadership",
        "technical credibility",
    }:
        return "professional"

    if text.startswith("independent learning"):
        return "learning"

    if text == "education":
        return "education"

    if (
        "technion - israel institute of technology" in text
        or "imperial college london" in text
        or "she codes" in text
    ):
        return "education"

    return None


def find_skill_evidence(lines):
    skills = {}
    current_section = "other"

    for line in lines:
        section = detect_section(line)

        if section:
            current_section = section

        lower_line = line.lower()

        for skill, aliases in SKILL_ALIASES.items():
            found = any(
                re.search(
                    r"(?<!\w)"
                    + re.escape(alias.lower())
                    + r"(?!\w)",
                    lower_line,
                )
                for alias in aliases
            )

            if found:
                evidence = {
                    "text": line[:500],
                    "context": current_section,
                }

                skills.setdefault(skill, []).append(evidence)

    # Remove duplicate evidence entries for the same skill.
    for skill, items in skills.items():
        unique = []
        seen = set()

        for item in items:
            key = (item["text"], item["context"])

            if key not in seen:
                seen.add(key)
                unique.append(item)

        skills[skill] = unique

    return skills


def parse_cv(cv_path):
    path = Path(cv_path)

    if not path.exists():
        raise FileNotFoundError(f"CV file not found: {path}")

    text = path.read_text(encoding="utf-8-sig")

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    return {
        "source_file": str(path),
        "skills": find_skill_evidence(lines),
        "professional_experience": [
            {
                "company": "Tensor Technologies",
                "role": "AI Developer",
                "period": "Jul 2023 - Present",
            },
            {
                "company": "Rafael Advanced Defense Systems",
                "role": "Physicist",
                "period": "Aug 2008 - Jul 2023",
            },
        ],
        "education": [
            "Technion - Israel Institute of Technology",
            "Imperial College London",
            "She Codes",
        ],
        "limitations": [
            "Skill presence does not automatically establish proficiency.",
            "Professional experience, projects, and learning are distinct.",
            "Years of experience must be verified against actual requirements.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Parse CV into a structured candidate profile."
    )
    parser.add_argument("--cv", default="data/cv.txt")
    parser.add_argument(
        "--output",
        default="data/candidate_profile.json",
    )
    args = parser.parse_args()

    profile = parse_cv(args.cv)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Profile saved to: {output_path}")
    print(f"Skills detected: {len(profile['skills'])}")

    for skill, evidence in profile["skills"].items():
        contexts = sorted({item["context"] for item in evidence})
        print(f"- {skill}: {', '.join(contexts)}")


if __name__ == "__main__":
    main()