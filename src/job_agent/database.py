import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Union
import re
import hashlib


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    url TEXT NOT NULL UNIQUE,

    title TEXT NOT NULL,
    company TEXT,

    location TEXT,
    work_model TEXT,
    date_text TEXT,
    date_published TEXT,

    tags_json TEXT,
    description TEXT,
    content_hash TEXT,

    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,

    action TEXT,
    action_at TEXT,
    action_note TEXT,
    cv_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_title
ON jobs(title);

CREATE INDEX IF NOT EXISTS idx_jobs_company
ON jobs(company);

CREATE INDEX IF NOT EXISTS idx_jobs_action
ON jobs(action);
"""

ADVANCED_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board TEXT NOT NULL,
    domain TEXT,
    recipe TEXT,
    recipe_status TEXT NOT NULL DEFAULT 'legacy',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(board, domain)
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    cv_mapping TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url TEXT NOT NULL,
    verdict TEXT,
    guardrail_overrides TEXT,
    rationale TEXT,
    model TEXT,
    prompt_version TEXT,
    confidence INTEGER,
    details_json TEXT,
    cover_letter_path TEXT,
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_url)
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'APPLIED',
    cv_path TEXT,
    cover_letter_path TEXT,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_url)
);

CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    thread_id TEXT,
    job_url TEXT,
    sender TEXT,
    subject TEXT,
    classification TEXT,
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_snippet TEXT
);

CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER,
    job_url TEXT,
    email_message_id TEXT,
    scheduled_for TEXT,
    timezone TEXT,
    interview_format TEXT,
    meeting_link TEXT,
    contact_person TEXT,
    event_title TEXT NOT NULL DEFAULT '',
    location TEXT,
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    calendar_event_id TEXT,
    confirmed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'needs_details',
    approval_reference TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL DEFAULT 'system',
    event_type TEXT NOT NULL,
    tool_name TEXT,
    details_json TEXT,
    approval_required INTEGER NOT NULL DEFAULT 0,
    approved INTEGER NOT NULL DEFAULT 0,
    approval_reference TEXT
);

CREATE TABLE IF NOT EXISTS job_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_url TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

def normalize_job_text(value: str) -> str:
    """Normalize text for duplicate comparison."""
    value = (value or "").lower()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def make_job_fingerprint(company: str, title: str, description: str) -> str:
    """Create a stable fingerprint for a job listing."""
    parts = [
        normalize_job_text(company),
        normalize_job_text(title),
        normalize_job_text(description),
    ]
    # Don't classify incomplete descriptions as duplicates.
    if not all(parts):
        return ""

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class JobDatabase:

    def __init__(self, path: Union[str, Path] = "data/jobs.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self._migrate()
        self.connection.executescript(SCHEMA)
        self.connection.executescript(ADVANCED_SCHEMA)
        self.connection.commit()
        self._migrate_advanced_schema()

    def _migrate(self) -> None:
        columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(jobs)")
        }
        if not columns:
            return  # fresh DB, SCHEMA will create everything
        if "action" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN action TEXT")
        if "action_at" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN action_at TEXT")
        if "action_note" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN action_note TEXT")
        if "cv_path" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN cv_path TEXT")
        if "content_hash" not in columns:
            self.connection.execute(
                "ALTER TABLE jobs ADD COLUMN content_hash TEXT"
            )
        self.connection.commit()

    def _migrate_advanced_schema(self) -> None:
        """Seed the broader job-platform schema without changing the legacy jobs table."""
        decision_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(job_decisions)")
        }
        for column, column_type in (
            ("confidence", "INTEGER"),
            ("details_json", "TEXT"),
            ("cover_letter_path", "TEXT"),
        ):
            if column not in decision_columns:
                self.connection.execute(
                    f"ALTER TABLE job_decisions ADD COLUMN {column} {column_type}"
                )

        email_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(emails)")
        }
        for column, column_type in (
            ("matched_job_url", "TEXT"),
            ("match_confidence", "INTEGER"),
        ):
            if column not in email_columns:
                self.connection.execute(
                    f"ALTER TABLE emails ADD COLUMN {column} {column_type}"
                )

        interview_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(interviews)")
        }
        for column, column_type in (
            ("email_message_id", "TEXT"),
            ("event_title", "TEXT NOT NULL DEFAULT ''"),
            ("location", "TEXT"),
            ("duration_minutes", "INTEGER NOT NULL DEFAULT 60"),
            ("status", "TEXT NOT NULL DEFAULT 'needs_details'"),
            ("approval_reference", "TEXT"),
        ):
            if column not in interview_columns:
                self.connection.execute(
                    f"ALTER TABLE interviews ADD COLUMN {column} {column_type}"
                )
        self.connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_interviews_email_message
            ON interviews(email_message_id)
            WHERE email_message_id IS NOT NULL
            """
        )

        self.connection.execute(
            """
            INSERT OR IGNORE INTO sources (board, domain, recipe, recipe_status)
            VALUES ('devbg', 'dev.bg', NULL, 'legacy')
            """
        )
        self.connection.execute(
            """
            INSERT OR IGNORE INTO listings (url, source, cv_mapping)
            SELECT j.url, 'devbg', j.cv_path
            FROM jobs j
            LEFT JOIN listings l ON l.url = j.url
            WHERE l.url IS NULL
            """
        )
        self.connection.commit()

    def record_audit_event(
        self,
        event_type: str,
        *,
        actor: str = "system",
        tool_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        approval_required: bool = False,
        approved: bool = False,
        approval_reference: Optional[str] = None,
    ) -> int:
        """Persist a structured audit record for tool calls and approvals."""
        cursor = self.connection.execute(
            """
            INSERT INTO audit_log (
                actor, event_type, tool_name, details_json,
                approval_required, approved, approval_reference
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor,
                event_type,
                tool_name,
                json.dumps(details or {}, ensure_ascii=False),
                int(bool(approval_required)),
                int(bool(approved)),
                approval_reference,
            ),
        )
        self.connection.commit()
        return cursor.lastrowid

    def list_jobs(self, limit: int = 50, action: Optional[str] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT * FROM jobs
            WHERE (? IS NULL OR action = ?)
            ORDER BY id DESC
            LIMIT ?
        """
        params: tuple[Any, ...] = (action, action, limit)
        rows = self.connection.execute(query, params).fetchall()
        columns = [c[0] for c in self.connection.execute("SELECT * FROM jobs LIMIT 0").description]
        return [dict(zip(columns, row)) for row in rows]

    def get_audit_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self.connection.execute(
            """
            SELECT timestamp, actor, event_type, tool_name, details_json,
                   approval_required, approved, approval_reference
            FROM audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    def save_job(self, job: Any) -> None:
        if hasattr(job, "to_dict"):
            job = job.to_dict()

        now = datetime.now(timezone.utc).isoformat()

        tags = job.get("tags") or []
        tags_json = json.dumps(tags, ensure_ascii=False) if isinstance(tags, list) else str(tags)
        content_hash = make_job_fingerprint(
            job.get("company", ""),
            job.get("title", ""),
            job.get("description", ""),
        )

        self.connection.execute(
            """
            INSERT INTO jobs (
                url, title, company, location, work_model, date_text,
                date_published, tags_json, description, content_hash, first_seen, last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                work_model = excluded.work_model,
                date_text = excluded.date_text,
                date_published = excluded.date_published,
                tags_json = excluded.tags_json,
                description = excluded.description,
                last_seen = excluded.last_seen,
                content_hash = excluded.content_hash
            """,
            (
                job.get("url", ""),
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("work_model", ""),
                job.get("date_text", ""),
                job.get("date_published", ""),
                tags_json,
                job.get("description", ""),
                content_hash,
                now,
                now,
            ),
        )
        self.connection.execute(
            """
            INSERT OR IGNORE INTO listings (url, source, cv_mapping)
            VALUES (?, 'devbg', ?)
            """,
            (job.get("url", ""), job.get("cv_path") or None),
        )

        self.connection.commit()

    # ------------------------------------------------------------------
    # Existing-job checks
    # ------------------------------------------------------------------

    def has_job(self, url: str) -> bool:
        """True if the job URL is already stored in the DB (scraped before)."""
        cursor = self.connection.execute("SELECT 1 FROM jobs WHERE url = ?", (url,))
        return cursor.fetchone() is not None

    def already_processed(self, url: str) -> bool:
        """Kept for backward compatibility. NOTE: this only checks that the job
        is stored, not that it was evaluated. Use has_job() / has_action()."""
        return self.has_job(url)

    def known_urls(self) -> Set[str]:
        """All job URLs already stored. Used by the scraper to skip known jobs."""
        return {row[0] for row in self.connection.execute("SELECT url FROM jobs")}

    
    def find_duplicate_url(
        self,
        company: str,
        title: str,
        description: str,
        exclude_url: Optional[str] = None,
    ) -> Optional[str]:
        """Return the URL of an existing identical job, if found."""
        fingerprint = make_job_fingerprint(company, title, description)
        if not fingerprint:
            return None

        rows = self.connection.execute(
            """
            SELECT url, company, title, description
            FROM jobs
            WHERE content_hash = ?
            """,
            (fingerprint,),
        ).fetchall()

        # Also compare older database records that don't have a hash yet.
        if not rows:
            rows = self.connection.execute(
                "SELECT url, company, title, description FROM jobs"
            ).fetchall()

        for url, db_company, db_title, db_description in rows:
            if url == exclude_url:
                continue

            existing_hash = make_job_fingerprint(
                db_company, db_title, db_description
            )
            if existing_hash and existing_hash == fingerprint:
                return url

        return None


    def has_action(self, url: str) -> bool:
        """True if the job already has a recorded action (evaluated/applied/skipped)."""
        cursor = self.connection.execute(
            "SELECT 1 FROM jobs WHERE url = ? AND action IS NOT NULL AND action != ''",
            (url,),
        )
        return cursor.fetchone() is not None

    def get_unprocessed_jobs(self, limit: int) -> List[Dict[str, Any]]:
        """Newest jobs with neither a recorded action nor an evaluation."""
        cursor = self.connection.execute(
            """
            SELECT * FROM jobs
            WHERE (action IS NULL OR action = '')
              AND NOT EXISTS (
                  SELECT 1
                  FROM job_decisions d
                  WHERE d.job_url = jobs.url
                    AND d.verdict IS NOT NULL
                    AND d.verdict != ''
                    AND d.verdict != 'EVAL_ERROR'
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM applications a
                  WHERE a.job_url = jobs.url
                    AND UPPER(a.status) = 'APPLIED'
              )
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_job_processing_state(self, url: str) -> Optional[Dict[str, Any]]:
        """Return the existing action and evaluation record for a stored job."""
        row = self.connection.execute(
            """
            SELECT j.action, d.verdict, d.details_json, d.rationale,
                   d.confidence, d.model, d.decided_at, a.status
            FROM jobs j
            LEFT JOIN job_decisions d ON d.job_url = j.url
            LEFT JOIN applications a ON a.job_url = j.url
            WHERE j.url = ?
            """,
            (url,),
        ).fetchone()
        if row is None:
            return None
        return {
            "action": row[0],
            "verdict": row[1],
            "details_json": row[2],
            "rationale": row[3],
            "confidence": row[4],
            "model": row[5],
            "decided_at": row[6],
            "application_status": row[7],
        }

    def count_jobs(self) -> int:
        result = self.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return result[0] if result else 0

    def close(self) -> None:
        self.connection.close()

    def record_action(self, url: str, action: str, note: Optional[str] = None) -> bool:
        """Set the latest action for a job (e.g. "NOT_RECOMMENDED").

        `note` is an optional free-text reason (e.g. why you skipped a job);
        it is fed back to the decision agent as preference history.
        Returns False if the job URL is not in the database.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        if not self.has_job(url):
            return False

        cursor = self.connection.execute(
            "UPDATE jobs SET action = ?, action_at = ?, action_note = ? WHERE url = ?",
            (action, timestamp, note, url),
        )
        self.connection.execute(
            """
            INSERT INTO job_status_history (job_url, status, note, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (url, action, note, timestamp),
        )
        self.connection.execute(
            """
            INSERT INTO job_decisions (job_url, verdict, rationale, model, prompt_version, decided_at)
            VALUES (?, ?, ?, 'legacy', 'legacy', ?)
            ON CONFLICT(job_url) DO UPDATE SET
                verdict = excluded.verdict,
                rationale = excluded.rationale,
                model = excluded.model,
                prompt_version = excluded.prompt_version,
                decided_at = excluded.decided_at
            """,
            (url, action, note or "legacy action", timestamp),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def record_evaluation(
        self,
        url: str,
        *,
        verdict: str,
        rationale: str,
        model: str,
        confidence: int,
        overrides: List[str],
        details: Dict[str, Any],
    ) -> None:
        """Persist an agent recommendation separately from human job actions."""
        if not self.has_job(url):
            raise ValueError(f"Cannot record evaluation for unknown job: {url}")
        if verdict not in {"APPLY", "SKIP"}:
            raise ValueError(f"Invalid evaluation verdict: {verdict}")
        if not 0 <= confidence <= 100:
            raise ValueError("Evaluation confidence must be between 0 and 100")

        self.connection.execute(
            """
            INSERT INTO job_decisions (
                job_url, verdict, guardrail_overrides, rationale, model,
                prompt_version, confidence, details_json, decided_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_url) DO UPDATE SET
                verdict = excluded.verdict,
                guardrail_overrides = excluded.guardrail_overrides,
                rationale = excluded.rationale,
                model = excluded.model,
                prompt_version = excluded.prompt_version,
                confidence = excluded.confidence,
                details_json = excluded.details_json,
                decided_at = excluded.decided_at
            """,
            (
                url,
                verdict,
                json.dumps(overrides, ensure_ascii=False),
                rationale,
                model,
                "m4-v1",
                confidence,
                json.dumps(details, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.connection.commit()

    def record_cover_letter_path(self, url: str, path: str) -> None:
        """Attach a generated review letter to the latest recommendation."""
        cursor = self.connection.execute(
            "UPDATE job_decisions SET cover_letter_path = ? WHERE job_url = ?",
            (path, url),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Cannot attach cover letter to unevaluated job: {url}")
        self.connection.commit()

    def get_feedback_history(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Your own decisions (APPLIED / SKIPPED), newest first.

        Agent verdicts (RECOMMENDED / NOT_RECOMMENDED) are deliberately excluded:
        learning from the agent's own output would be circular.
        """
        cursor = self.connection.execute(
            """
            SELECT title, company, location, work_model, tags_json,
                   action, action_note, action_at
            FROM jobs
            WHERE action IN ('APPLIED', 'SKIPPED')
            ORDER BY action_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def set_cv_path(self, urls: Iterable[str], cv_path: str) -> int:
        """Remember which CV to use for these jobs (set when they are scraped)."""
        cursor = self.connection.executemany(
            "UPDATE jobs SET cv_path = ? WHERE url = ?", [(cv_path, u) for u in urls]
        )
        self.connection.commit()
        return cursor.rowcount

    def get_cv_path(self, url: str) -> Optional[str]:
        row = self.connection.execute(
            "SELECT cv_path FROM jobs WHERE url = ?", (url,)
        ).fetchone()
        return row[0] if row and row[0] else None

    def get_action(self, url: str) -> Optional[str]:
        row = self.connection.execute(
            "SELECT action FROM jobs WHERE url = ?", (url,)
        ).fetchone()
        return row[0] if row else None

    def save_tracked_email(self, email: Dict[str, Any]) -> None:
        """Store email metadata and a short snippet, never the full message body."""
        self.connection.execute(
            """
            INSERT INTO emails (
                message_id, thread_id, job_url, sender, subject,
                classification, received_at, raw_snippet,
                matched_job_url, match_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                thread_id = excluded.thread_id,
                job_url = COALESCE(excluded.job_url, emails.job_url),
                sender = excluded.sender,
                subject = excluded.subject,
                classification = excluded.classification,
                received_at = excluded.received_at,
                raw_snippet = excluded.raw_snippet,
                matched_job_url = COALESCE(excluded.matched_job_url, emails.matched_job_url),
                match_confidence = COALESCE(excluded.match_confidence, emails.match_confidence)
            """,
            (
                email["message_id"],
                email.get("thread_id"),
                email.get("matched_job_url"),
                email.get("sender", ""),
                email.get("subject", ""),
                email.get("classification", "other"),
                email.get("received_at") or datetime.now(timezone.utc).isoformat(),
                (email.get("snippet") or "")[:500],
                email.get("matched_job_url"),
                email.get("match_confidence"),
            ),
        )
        self.connection.commit()

    def get_tracked_emails(self, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = self.connection.execute(
            """
            SELECT message_id, thread_id, job_url, sender, subject,
                   classification, received_at, raw_snippet,
                   matched_job_url, match_confidence
            FROM emails
            ORDER BY received_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def save_interview_proposal(self, proposal: Dict[str, Any]) -> int:
        """Create or refresh an unconfirmed proposal linked to its source email."""
        email_message_id = proposal.get("email_message_id")
        existing = None
        if email_message_id:
            existing = self.connection.execute(
                """
                SELECT id, status FROM interviews WHERE email_message_id = ?
                """,
                (email_message_id,),
            ).fetchone()
        if existing and existing[1] in {"scheduled", "creating"}:
            return int(existing[0])

        values = (
            proposal.get("job_url"),
            email_message_id,
            proposal.get("scheduled_for"),
            proposal.get("timezone"),
            proposal.get("interview_format"),
            proposal.get("meeting_link"),
            proposal.get("contact_person"),
            proposal.get("event_title", "Job interview"),
            proposal.get("location"),
            proposal.get("duration_minutes", 60),
            proposal.get("status", "needs_details"),
        )
        if existing:
            self.connection.execute(
                """
                UPDATE interviews SET
                    job_url = ?, scheduled_for = ?, timezone = ?,
                    interview_format = ?, meeting_link = ?, contact_person = ?,
                    event_title = ?, location = ?, duration_minutes = ?,
                    status = ?, confirmed = 0
                WHERE id = ?
                """,
                (*values[:1], *values[2:], int(existing[0])),
            )
            interview_id = int(existing[0])
        else:
            cursor = self.connection.execute(
                """
                INSERT INTO interviews (
                    job_url, email_message_id, scheduled_for, timezone,
                    interview_format, meeting_link, contact_person, event_title,
                    location, duration_minutes, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            interview_id = int(cursor.lastrowid)
        self.connection.commit()
        return interview_id

    def get_interview(self, interview_id: int) -> Optional[Dict[str, Any]]:
        cursor = self.connection.execute(
            """
            SELECT id, job_url, email_message_id, scheduled_for, timezone,
                   interview_format, meeting_link, contact_person, event_title,
                   location, duration_minutes, calendar_event_id, confirmed,
                   status, approval_reference, created_at
            FROM interviews WHERE id = ?
            """,
            (interview_id,),
        )
        row = cursor.fetchone()
        return dict(zip((column[0] for column in cursor.description), row)) if row else None

    def list_interviews(
        self, *, status: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        cursor = self.connection.execute(
            """
            SELECT id, job_url, email_message_id, scheduled_for, timezone,
                   interview_format, meeting_link, contact_person, event_title,
                   location, duration_minutes, calendar_event_id, confirmed,
                   status, approval_reference, created_at
            FROM interviews
            WHERE (? IS NULL OR status = ?)
            ORDER BY COALESCE(scheduled_for, created_at), id
            LIMIT ?
            """,
            (status, status, limit),
        )
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def record_scheduled_interview(
        self,
        interview_id: int,
        *,
        scheduled_for: str,
        timezone_name: str,
        duration_minutes: int,
        calendar_event_id: str,
        approval_reference: str,
    ) -> bool:
        cursor = self.connection.execute(
            """
            UPDATE interviews SET
                scheduled_for = ?, timezone = ?, duration_minutes = ?,
                calendar_event_id = ?, confirmed = 1, status = 'scheduled',
                approval_reference = ?
            WHERE id = ? AND status IN ('needs_details', 'pending_confirmation')
              AND confirmed = 0
            """,
            (
                scheduled_for,
                timezone_name,
                duration_minutes,
                calendar_event_id,
                approval_reference,
                interview_id,
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1