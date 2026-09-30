from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


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
