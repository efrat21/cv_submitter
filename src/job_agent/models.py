"""Data models (plain dataclasses, same style as Job)."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ------------------------------------------------------------------ Job
@dataclass
class Job:
    url: str
    title: str
    company: str
    description: str
    location: str = ""
    employment_type: str = ""
    work_model: str = ""
    requirements: List[str] = field(default_factory=list)
    benefits: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    date_text: str = ""
    date_published: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert Job instance to dictionary representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Instantiate a Job from a dictionary."""
        return cls(
            url=data.get("url", ""),
            title=data.get("title", ""),
            company=data.get("company", ""),
            description=data.get("description", ""),
            location=data.get("location", ""),
            employment_type=data.get("employment_type", ""),
            work_model=data.get("work_model", ""),
            requirements=data.get("requirements") or [],
            benefits=data.get("benefits") or [],
            tags=data.get("tags") or [],
            date_text=data.get("date_text", ""),
            date_published=data.get("date_published", ""),
        )


# ------------------------------------------------------------ candidate
@dataclass
class CandidateProfile:
    """Facts about the candidate (parsed once from the CV)."""

    name: str
    location: str = ""
    summary: str = ""
    years_experience: float = 0.0
    seniority: str = ""  # junior / mid / senior / lead
    skills: List[str] = field(default_factory=list)
    experience: List[str] = field(default_factory=list)  # short bullets
    education: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateProfile":
        skills_data = data.get("skills") or []
        if isinstance(skills_data, dict):
            # If skills is evidence dict from cv_parser: {"Python": [{"text": ...}], ...}
            skills = list(skills_data.keys())
        else:
            skills = list(skills_data)

        experience = data.get("experience") or []
        if not experience and data.get("professional_experience"):
            experience = [
                f"{exp.get('role', '')} at {exp.get('company', '')} ({exp.get('period', '')})".strip()
                for exp in data.get("professional_experience", [])
            ]

        years = data.get("years_experience")
        if years is None and data.get("professional_experience"):
            # Tensor Technologies (approx 2y) + Rafael (15y)
            years = 17.0

        return cls(
            name=data.get("name", ""),
            location=data.get("location", ""),
            summary=data.get("summary", ""),
            years_experience=float(years or 0),
            seniority=data.get("seniority", "mid"),
            skills=skills,
            experience=experience,
            education=data.get("education") or [],
            languages=data.get("languages") or [],
        )


@dataclass
class CandidatePreferences:
    """What the candidate WANTS (never inferred from the CV)."""

    target_roles: List[str] = field(default_factory=list)
    avoid_roles: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    work_models: List[str] = field(default_factory=list)  # remote / hybrid / onsite
    max_required_years: Optional[float] = None
    deal_breakers: List[str] = field(default_factory=list)
    strong_skills: List[str] = field(default_factory=list)
    learning_skills: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidatePreferences":
        raw = data.get("candidate") if isinstance(data.get("candidate"), dict) else data
        max_years = raw.get("max_required_years")

        work_models = list(raw.get("work_models") or [])
        if not work_models and isinstance(raw.get("preferences"), dict):
            for model_name, enabled in raw["preferences"].items():
                if enabled and model_name not in work_models:
                    work_models.append(model_name)

        avoid_roles = list(raw.get("avoid_roles") or raw.get("avoid") or [])

        strong_skills = list(raw.get("strong_skills") or [])
        learning_skills = list(raw.get("learning_skills") or [])
        if isinstance(raw.get("skills"), dict):
            if not strong_skills:
                strong_skills = list(raw["skills"].get("strong") or [])
            if not learning_skills:
                learning_skills = list(raw["skills"].get("learning") or [])

        return cls(
            target_roles=list(raw.get("target_roles") or []),
            avoid_roles=avoid_roles,
            locations=list(raw.get("locations") or []),
            work_models=work_models,
            max_required_years=float(max_years) if max_years is not None else None,
            deal_breakers=list(raw.get("deal_breakers") or []),
            strong_skills=strong_skills,
            learning_skills=learning_skills,
            notes=raw.get("notes", ""),
        )


# ---------------------------------------------------------------- match
@dataclass
class MatchResult:
    """Output of the cheap deterministic matcher (Stage 1) for one job."""

    job: Job
    matched_skills: List[str] = field(default_factory=list)
    missing_skills: List[str] = field(default_factory=list)
    detected_seniority: str = ""
    required_years: Optional[float] = None
    prefilter_score: Optional[int] = None  # 0-100, advisory only
    verification_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)  # recurses into the nested Job

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MatchResult":
        years = data.get("required_years")
        score = data.get("prefilter_score")
        if score is None and data.get("match_score") is not None:
            score = data.get("match_score")

        job_data = data.get("job")
        if not job_data:
            # Flattened format from evaluator.py
            job_data = {
                "url": data.get("url", ""),
                "title": data.get("title", ""),
                "company": data.get("company", ""),
                "location": data.get("location", ""),
                "work_model": data.get("work_model", ""),
                "description": data.get("description", ""),
            }

        matched = list(data.get("matched_skills") or [])
        if not matched and ("core_assessment" in data or "related_assessment" in data):
            all_assessments = (data.get("core_assessment") or []) + (data.get("related_assessment") or [])
            matched = [
                item["skill"]
                for item in all_assessments
                if isinstance(item, dict) and item.get("status") == "evidence_found"
            ]

        missing = list(data.get("missing_skills") or [])
        if not missing and ("core_missing" in data or "related_missing" in data):
            missing = (data.get("core_missing") or []) + (data.get("related_missing") or [])

        return cls(
            job=Job.from_dict(job_data),
            matched_skills=matched,
            missing_skills=missing,
            title_keyword_hits=list(data.get("title_keyword_hits") or []),
            detected_seniority=data.get("detected_seniority", ""),
            required_years=float(years) if years is not None else None,
            prefilter_score=int(score) if score is not None else None,
        )


# ------------------------------------------------------------ decisions
ROLE_FIT = ("strong", "partial", "weak")
SENIORITY_FIT = ("good", "stretch", "too_senior", "too_junior")
LOCATION_FIT = ("good", "uncertain", "bad")
DECISIONS = ("APPLY", "SKIP")

# JSON schema sent to Ollama (`format=`). Property ORDER matters: with
# constrained decoding the model fills fields in order, so the analysis comes
# first and `decision` last - the model "thinks" before it commits.
_STR_LIST = {"type": "array", "items": {"type": "string"}}
LLM_DECISION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "role_fit": {"type": "string", "enum": list(ROLE_FIT)},
        "seniority_fit": {"type": "string", "enum": list(SENIORITY_FIT)},
        "location_fit": {"type": "string", "enum": list(LOCATION_FIT)},
        "hard_blockers": _STR_LIST,
        "critical_missing_skills": _STR_LIST,
        "reasons_for": _STR_LIST,
        "reasons_against": _STR_LIST,
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "rationale": {"type": "string"},
    },
    "required": [
        "role_fit", "seniority_fit", "location_fit", "hard_blockers",
        "critical_missing_skills", "reasons_for", "reasons_against",
        "confidence", "decision", "rationale",
    ],
}


def _choice(data: Dict[str, Any], key: str, allowed: tuple) -> str:
    value = data.get(key)
    if value not in allowed:
        raise ValueError(f"'{key}' must be one of {list(allowed)}, got {value!r}")
    return value


def _str_list(data: Dict[str, Any], key: str) -> List[str]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"'{key}' must be a list of strings, got {value!r}")
    return value


@dataclass
class LLMDecision:
    """What the LLM must return. `from_dict` VALIDATES and raises ValueError."""

    role_fit: str
    seniority_fit: str
    location_fit: str
    hard_blockers: List[str]
    critical_missing_skills: List[str]
    reasons_for: List[str]
    reasons_against: List[str]
    confidence: int
    decision: str
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMDecision":
        if not isinstance(data, dict):
            raise ValueError(f"expected a JSON object, got {type(data).__name__}")
        confidence = data.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 100
        ):
            raise ValueError(f"'confidence' must be a number 0-100, got {confidence!r}")
        rationale = data.get("rationale")
        if not isinstance(rationale, str):
            raise ValueError("'rationale' must be a string")
        return cls(
            role_fit=_choice(data, "role_fit", ROLE_FIT),
            seniority_fit=_choice(data, "seniority_fit", SENIORITY_FIT),
            location_fit=_choice(data, "location_fit", LOCATION_FIT),
            hard_blockers=_str_list(data, "hard_blockers"),
            critical_missing_skills=_str_list(data, "critical_missing_skills"),
            reasons_for=_str_list(data, "reasons_for"),
            reasons_against=_str_list(data, "reasons_against"),
            confidence=int(confidence),
            decision=_choice(data, "decision", DECISIONS),
            rationale=rationale,
        )


@dataclass
class FinalDecision:
    """What the agent returns after Python guardrails have been applied."""

    job_url: str
    title: str
    company: str
    decision: str  # APPLY / SKIP
    confidence: int
    rationale: str
    overrides: List[str] = field(default_factory=list)
    llm: Optional[LLMDecision] = None
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -------------------------------------------------------- cover letter
@dataclass
class CoverLetter:
    job_url: str
    title: str
    company: str
    subject_line: str
    content: str
    file_path: str = ""
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)