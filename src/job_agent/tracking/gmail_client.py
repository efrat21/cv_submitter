"""Read-only Gmail API client. Message bodies are returned transiently only."""

from __future__ import annotations

import base64
import os
import re
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from job_agent.config import DATA_DIR

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._hidden_depth += 1
        elif tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1
        elif tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def _decode_part(part: dict[str, Any]) -> str:
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    charset = "utf-8"
    for header in part.get("headers", []):
        if header.get("name", "").casefold() == "content-type":
            match = re.search(
                r"""charset=["']?([^;"']+)""",
                str(header.get("value", "")),
                re.I,
            )
            if match:
                charset = match.group(1).strip()
            break
    try:
        return raw.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return raw.decode("latin-1", errors="replace")


def _plain_text(payload: dict[str, Any]) -> str:
    plain: list[str] = []
    html: list[str] = []

    def visit(part: dict[str, Any]) -> None:
        if part.get("filename"):
            return
        mime_type = part.get("mimeType", "").casefold()
        if mime_type == "text/plain":
            plain.append(_decode_part(part))
        elif mime_type == "text/html":
            html.append(_decode_part(part))
        for child in part.get("parts", []):
            visit(child)

    visit(payload)
    if plain:
        return "\n".join(plain)
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed("\n".join(html))
    return " ".join("".join(parser.parts).split())


def _header_value(headers: list[dict[str, str]], name: str) -> str:
    for header in headers:
        if header.get("name", "").casefold() == name.casefold():
            return str(make_header(decode_header(header.get("value", ""))))
    return ""


def _received_at(headers: list[dict[str, str]], internal_date: str | None) -> str:
    date_header = _header_value(headers, "Date")
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            pass
    if internal_date and internal_date.isdigit():
        return datetime.fromtimestamp(
            int(internal_date) / 1000, tz=timezone.utc
        ).isoformat()
    return datetime.now(timezone.utc).isoformat()


class GmailClient:
    """Fetch recent Gmail messages without modifying labels or read state."""

    def __init__(self, *, service: Any | None = None) -> None:
        self._service = service

    def _build_service(self) -> Any:
        if self._service is not None:
            return self._service
        credentials_path = Path(
            os.environ.get(
                "JOB_AGENT_GOOGLE_OAUTH_CLIENT",
                DATA_DIR / "google_oauth_client.json",
            )
        )
        token_path = Path(
            os.environ.get("JOB_AGENT_GMAIL_TOKEN_PATH", DATA_DIR / "gmail_token.json")
        )
        if not credentials_path.is_file():
            raise FileNotFoundError(
                f"Google OAuth client file not found: {credentials_path}"
            )

        credentials = None
        if token_path.is_file():
            credentials = Credentials.from_authorized_user_file(
                str(token_path), [GMAIL_READONLY_SCOPE]
            )
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), [GMAIL_READONLY_SCOPE]
                )
                credentials = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(credentials.to_json(), encoding="utf-8")

        self._service = build(
            "gmail", "v1", credentials=credentials, cache_discovery=False
        )
        return self._service

    def list_recent_messages(
        self, *, max_results: int = 100, query: str = "newer_than:30d -in:trash -in:spam"
    ) -> list[dict[str, Any]]:
        if not 1 <= max_results <= 500:
            raise ValueError("max_results must be between 1 and 500")
        service = self._build_service()
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        results: list[dict[str, Any]] = []
        for item in response.get("messages", []):
            message = (
                service.users()
                .messages()
                .get(userId="me", id=item["id"], format="full")
                .execute()
            )
            payload = message.get("payload", {})
            headers = payload.get("headers", [])
            results.append(
                {
                    "message_id": message["id"],
                    "thread_id": message.get("threadId"),
                    "sender": _header_value(headers, "From"),
                    "subject": _header_value(headers, "Subject"),
                    "received_at": _received_at(
                        headers, message.get("internalDate")
                    ),
                    "snippet": message.get("snippet", ""),
                    "text": _plain_text(payload),
                }
            )
        return results
