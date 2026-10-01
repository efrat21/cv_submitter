import argparse
import json
import re
from pathlib import Path


SKILL_ALIASES = {
    "Python": ["python"],
    "FastAPI": ["fastapi"],
    "Machine Learning": [
        "machine learning",
        "machine-learning",
        "ml models",
        "ml pipeline",
    ],
    "Deep Learning": [
        "deep learning",
        "cnn",
        "lstm",
        "gru",
        "autoencoder",
    ],
    "PyTorch": ["pytorch"],
    "TensorFlow": ["tensorflow"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Data Analysis": [
        "data analysis",
        "data analytics",
        "data cleaning",
        "feature engineering",
    ],
    "Statistics": ["statistics", "statistical modeling"],
    "Signal Processing": ["signal processing"],
    "RAG": [
        "retrieval-augmented generation",
        "rag-based",
    ],
    "LLMs": [
        "large language model",
        "llm",
        "chatgpt",
        "gemini",
    ],
    "AI Agents": [
        "ai agents",
        "agentic ai",
        "autonomous agents",
    ],
    "MCP": [
        "model context protocol",
        "mcp",
    ],
    "GitHub Copilot": ["github copilot"],
    "Azure": [
        "azure",
        "document intelligence",
    ],
    "Docker": ["docker"],
    "Redis": ["redis"],
    "MongoDB": ["mongodb"],
    "SQL": [
        "sql",
        "relational data infrastructure",
    ],
    "REST APIs": [
        "rest api",
        "backend services",
        "fastapi",
    ],
    "Project Management": [
        "project management",
        "project controls",
        "roadmap planning",
    ],
    "Technical Leadership": [
        "technical project management",
        "multidisciplinary",
        "team productivity",
        "mentored a team",
    ],
    "Research and Development": [
        "r&d",
        "research",
        "feasibility analysis",
        "algorithm development",
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


LEARNING_MARKERS = [
    "independent learning",
    "course",
    "specialization",
    "challenge",
    "summer school",
    "learning",
]

PROJECT_MARKERS = [
    "project",
    "podcast",
    "chatbot",
    "microservice",
    "pipeline",
]


def classify_evidence(line):
    """Classify the context of a CV line, not the skill level."""

    text = line.lower()

    if any(marker in text for marker in LEARNING_MARKERS):
        return "learning_or_course"

    if any(marker in text for marker in PROJECT_MARKERS):
        return "project"

    return "professional_or_other"


def parse_cv(cv_path):
    path = Path(cv_path)

    if not path.exists():
        raise FileNotFoundError(
            f"CV file not found: {path}"
        )

    text = path.read_text(
        encoding="utf-8-sig"
    )

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    skills = {}

    for skill, aliases in SKILL_ALIASES.items():
        evidence = []

        for line in lines:
            lower_line = line.lower()

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
                evidence.append({
                    "text": line[:500],
                    "context": classify_evidence(line),
                })

        if evidence:
            skills[skill] = evidence

    profile = {
        "source_file": str(path),
        "skills": skills,
        "experience_summary": [
            "AI Developer at Tensor Technologies, "
            "July 2023 to present, according to the CV.",
            "Physicist at Rafael Advanced Defense Systems, "
            "August 2008 to July 2023, according to the CV.",
        ],
        "important_limitations": [
            "Keyword presence does not prove proficiency.",
            "Learning and course mentions are not professional "
            "work experience.",
            "Years of experience in a specific technology "
            "must be verified separately.",
        ],
    }

    return profile


def main():
    parser = argparse.ArgumentParser(
        description="Parse a CV into a structured profile."
    )

    parser.add_argument(
        "--cv",
        default="data/cv.txt",
    )

    parser.add_argument(
        "--output",
        default="data/candidate_profile.json",
    )

    args = parser.parse_args()

    profile = parse_cv(args.cv)

    output_path = Path(args.output)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            profile,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"Profile saved to: {output_path}")
    print(f"Skills detected: {len(profile['skills'])}")

    for skill, evidence in profile["skills"].items():
        contexts = sorted({
            item["context"]
            for item in evidence
        })

        print(
            f"- {skill}: "
            f"{', '.join(contexts)}"
        )


if __name__ == "__main__":
    main()