"""Match tracked messages to stored jobs without guessing between candidates."""

from __future__ import annotations

import re

from job_agent.database import JobDatabase


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def match_email_to_job(
    sender: str,
    subject: str,
    text: str,
    db: JobDatabase,
) -> tuple[str | None, int | None]:
    """Return a job URL only for a unique, evidence-backed match."""
    content = _normalized(f"{subject} {text}")
    sender_domain = sender.rsplit("@", 1)[-1].split(">")[0].strip().casefold()
    rows = db.connection.execute(
        """
        SELECT url, title, company
        FROM jobs
        WHERE action = 'APPLIED'
           OR EXISTS (
               SELECT 1 FROM applications a
               WHERE a.job_url = jobs.url AND a.status = 'APPLIED'
           )
        """
    ).fetchall()
    scores: list[tuple[int, str]] = []
    for url, title, company in rows:
        score = 0
        normalized_company = _normalized(company or "")
        normalized_title = _normalized(title or "")
        if url and url.casefold() in f"{subject} {text}".casefold():
            score += 100
        if normalized_company and len(normalized_company) >= 3:
            if normalized_company in content:
                score += 5
            company_tokens = normalized_company.split()
            domain_tokens = _normalized(sender_domain)
            if company_tokens and company_tokens[0] in domain_tokens.split():
                score += 3
        title_tokens = [
            token for token in normalized_title.split() if len(token) >= 4
        ]
        if title_tokens and all(token in content.split() for token in title_tokens):
            score += 4
        if score:
            scores.append((score, url))

    if not scores:
        return None, None
    scores.sort(reverse=True)
    if len(scores) > 1 and scores[0][0] == scores[1][0]:
        return None, None
    if scores[0][0] < 4:
        return None, None
    return scores[0][1], min(scores[0][0] * 10, 100)
