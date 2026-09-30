import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    url TEXT NOT NULL UNIQUE,

    title TEXT NOT NULL,
    company TEXT,

    location TEXT,
    work_model TEXT,
    date_text TEXT,

    tags_json TEXT,
    description TEXT,

    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_title
ON jobs(title);

CREATE INDEX IF NOT EXISTS idx_jobs_company
ON jobs(company);
"""


class JobDatabase:

    def __init__(self, path="data/jobs.db"):

        self.path = Path(path)

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.connection = sqlite3.connect(
            self.path
        )

        self.connection.executescript(
            SCHEMA
        )

        self.connection.commit()

    def save_job(self, job):

        now = datetime.now(
            timezone.utc
        ).isoformat()

        self.connection.execute(
            """
            INSERT INTO jobs (
                url,
                title,
                company,
                location,
                work_model,
                date_text,
                tags_json,
                description,
                first_seen,
                last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(url) DO UPDATE SET

                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                work_model = excluded.work_model,
                date_text = excluded.date_text,
                tags_json = excluded.tags_json,
                description = excluded.description,
                last_seen = excluded.last_seen
            """,
            (
                job["url"],
                job["title"],
                job["company"],
                job["location"],
                job["work_model"],
                job["date_text"],
                json.dumps(
                    job["tags"],
                    ensure_ascii=False
                ),
                job["description"],
                now,
                now,
            ),
        )

        self.connection.commit()

    def count_jobs(self):

        result = self.connection.execute(
            "SELECT COUNT(*) FROM jobs"
        ).fetchone()

        return result[0]

    def close(self):

        self.connection.close()