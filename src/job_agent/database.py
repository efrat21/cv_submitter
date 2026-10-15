import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union


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

    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,

    action TEXT,
    action_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_title
ON jobs(title);

CREATE INDEX IF NOT EXISTS idx_jobs_company
ON jobs(company);

CREATE INDEX IF NOT EXISTS idx_jobs_action
ON jobs(action);
"""


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
        if "action" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN action TEXT")
        if "action_at" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN action_at TEXT")
        self.connection.commit()

    def save_job(self, job: Any) -> None:
        if hasattr(job, "to_dict"):
            job = job.to_dict()

        now = datetime.now(timezone.utc).isoformat()

        tags = job.get("tags") or []
        tags_json = json.dumps(tags, ensure_ascii=False) if isinstance(tags, list) else str(tags)

        self.connection.execute(
            """
            INSERT INTO jobs (
                url,
                title,
                company,
                location,
                work_model,
                date_text,
                date_published,
                tags_json,
                description,
                first_seen,
                last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                work_model = excluded.work_model,
                date_text = excluded.date_text,
                date_published = excluded.date_published,
                tags_json = excluded.tags_json,
                description = excluded.description,
                last_seen = excluded.last_seen
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
                now,
                now,
            ),
        )

        self.connection.commit()

    def already_processed(self, url: str) -> bool:
        cursor = self.connection.execute(
            "SELECT 1 FROM jobs WHERE url = ?", (url,)
        )
        return cursor.fetchone() is not None

    def count_jobs(self) -> int:
        result = self.connection.execute(
            "SELECT COUNT(*) FROM jobs"
        ).fetchone()
        return result[0] if result else 0

    def close(self) -> None:
        self.connection.close()

    def record_action(self, url: str, action: str) -> bool:
        """Set the latest action for a job (e.g. "NOT_RECOMMENDED").

        Returns False if the job URL is not in the database.
        """
        cursor = self.connection.execute(
            "UPDATE jobs SET action = ?, action_at = ? WHERE url = ?",
            (action, datetime.now(timezone.utc).isoformat(), url),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def get_action(self, url: str) -> Optional[str]:
        row = self.connection.execute(
            "SELECT action FROM jobs WHERE url = ?", (url,)
        ).fetchone()
        return row[0] if row else None