"""Extract a cautious, editable interview-event proposal from email text."""

from __future__ import annotations

import re
from datetime import date, datetime
from email.utils import parseaddr
from typing import Any


_MONTHS = {
    name.casefold(): number
    for number, names in enumerate(
        (
            ("January", "Jan"),
            ("February", "Feb"),
            ("March", "Mar"),
            ("April", "Apr"),
            ("May",),
            ("June", "Jun"),
            ("July", "Jul"),
            ("August", "Aug"),
            ("September", "Sep", "Sept"),
            ("October", "Oct"),
            ("November", "Nov"),
            ("December", "Dec"),
        ),
        1,
    )
    for name in names
}
_TIMEZONES = {
    "UTC": "UTC",
    "GMT": "UTC",
    "ET": "America/New_York",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CT": "America/Chicago",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MT": "America/Denver",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "CET": "Europe/Paris",
    "CEST": "Europe/Paris",
    "EET": "Europe/Sofia",
    "EEST": "Europe/Sofia",
    "BST": "Europe/London",
}


def _extract_date(text: str, today: date) -> date | None:
    iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if iso:
        try:
            return date(*(int(part) for part in iso.groups()))
        except ValueError:
            return None

    month_names = "|".join(sorted(_MONTHS, key=len, reverse=True))
    month_match = re.search(
        rf"\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d{{2}}))?\b",
        text,
        re.I,
    )
    if month_match:
        month = _MONTHS[month_match.group(1).casefold()]
        day = int(month_match.group(2))
        year = int(month_match.group(3) or today.year)
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if not month_match.group(3) and candidate < today:
            candidate = candidate.replace(year=year + 1)
        return candidate

    month_first = "|".join(sorted(_MONTHS, key=len, reverse=True))
    day_first_match = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_first})\.?(?:,?\s+(20\d{{2}}))?\b",
        text,
        re.I,
    )
    if day_first_match:
        day = int(day_first_match.group(1))
        month = _MONTHS[day_first_match.group(2).casefold()]
        year = int(day_first_match.group(3) or today.year)
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if not day_first_match.group(3) and candidate < today:
            candidate = candidate.replace(year=year + 1)
        return candidate

    numeric = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", text)
    if numeric:
        first, second, year = (int(part) for part in numeric.groups())
        try:
            # Resolve unambiguous values; choose European day/month when both
            # values are valid months and leave the final check to the human.
            if first > 12:
                day, month = first, second
            elif second > 12:
                month, day = first, second
            else:
                day, month = first, second
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _extract_time(text: str) -> tuple[int, int] | None:
    match = re.search(
        r"\b(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b",
        text,
        re.I,
    )
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3).casefold().replace(".", "")
        if not 1 <= hour <= 12 or minute > 59:
            return None
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return hour, minute

    match = re.search(
        r"\b(?:at\s+|time\s*[:=]\s*)([01]?\d|2[0-3]):([0-5]\d)\b",
        text,
        re.I,
    )
    return (int(match.group(1)), int(match.group(2))) if match else None


def extract_interview_proposal(
    subject: str,
    text: str,
    *,
    sender: str = "",
    today: date | None = None,
) -> dict[str, Any]:
    """Return parsed values; incomplete or ambiguous fields remain unset."""
    now_date = today or datetime.now().date()
    content = f"{subject}\n{text}"
    date_value = _extract_date(content, now_date)
    time_value = _extract_time(content)
    scheduled_for = None
    if date_value and time_value:
        scheduled_for = datetime(
            date_value.year,
            date_value.month,
            date_value.day,
            time_value[0],
            time_value[1],
        ).isoformat(timespec="minutes")

    timezone_name = ""
    tz_match = re.search(
        r"\b(UTC|GMT|ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|"
        r"CET|CEST|EET|EEST|BST)\b",
        content,
        re.I,
    )
    if tz_match:
        timezone_name = _TIMEZONES[tz_match.group(1).upper()]
    else:
        iana_match = re.search(r"\b([A-Za-z_]+/[A-Za-z_+-]+)\b", content)
        if iana_match:
            timezone_name = iana_match.group(1)

    meeting_match = re.search(r"https?://[^\s<>\"')]+", content, re.I)
    format_match = re.search(
        r"\b(video|zoom|google meet|microsoft teams|phone|in[- ]person|onsite)\b",
        content,
        re.I,
    )
    contact, _ = parseaddr(sender)
    return {
        "scheduled_for": scheduled_for,
        "timezone": timezone_name,
        "interview_format": format_match.group(1) if format_match else "",
        "meeting_link": meeting_match.group(0).rstrip(".,;") if meeting_match else "",
        "contact_person": contact or sender,
    }
