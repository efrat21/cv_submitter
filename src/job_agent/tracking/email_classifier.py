"""Conservative, local classification of job-application email."""

from __future__ import annotations

import re
from typing import Literal

EmailClassification = Literal[
    "interview", "offer", "rejection", "acknowledgement", "other"
]

_PATTERNS: tuple[tuple[EmailClassification, re.Pattern[str]], ...] = (
    (
        "offer",
        re.compile(r"\b(job offer|offer of employment|pleased to offer|employment offer)\b", re.I),
    ),
    (
        "interview",
        re.compile(
            r"\b(interview|schedule a call|schedule a meeting|availability for|"
            r"technical screen|screening call|meet with the team)\b",
            re.I,
        ),
    ),
    (
        "rejection",
        re.compile(
            r"\b(unfortunately|not moving forward|decided to proceed with another|"
            r"not selected|will not be progressing|regret to inform)\b",
            re.I,
        ),
    ),
    (
        "acknowledgement",
        re.compile(
            r"\b(application received|thank you for applying|application confirmation|"
            r"we have received your application|your application has been received)\b",
            re.I,
        ),
    ),
)


def classify_email(subject: str, text: str) -> EmailClassification:
    """Classify without sending email content to an external model."""
    content = f"{subject}\n{text}"
    for classification, pattern in _PATTERNS:
        if pattern.search(content):
            return classification
    return "other"
