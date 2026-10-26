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
        self.connection.commit()

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
        """Newest stored jobs that have no action recorded yet."""
        cursor = self.connection.execute(
            """
            SELECT * FROM jobs
            WHERE action IS NULL OR action = ''
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

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
        cursor = self.connection.execute(
            "UPDATE jobs SET action = ?, action_at = ?, action_note = ? WHERE url = ?",
            (action, datetime.now(timezone.utc).isoformat(), note, url),
        )
        self.connection.commit()
        return cursor.rowcount > 0

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