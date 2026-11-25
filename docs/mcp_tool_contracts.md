# MCP Tool Contracts

## Evaluation and review server

Run `uv run job-agent-workflow-mcp` to start the stdio MCP server. The server
uses the local job database and candidate files. The database path can be
overridden with `JOB_AGENT_DB_PATH`; profile and preference paths can be
overridden with `JOB_AGENT_PROFILE_PATH` and `JOB_AGENT_PREFERENCES_PATH`.

| Tool | Input | Behavior |
| --- | --- | --- |
| `evaluate_job_fit` | `job_url` | Runs deterministic matching and guarded local Ollama evaluation only if the existing database has no successful evaluation or human action for the job. Returns `evaluation_skipped: true` for already-evaluated/applied jobs instead of invoking the model again. |
| `generate_cover_letter` | `job_url`, optional `candidate_name`, optional `use_factchecker` | Generates a draft only for a job with an `APPLY` recommendation, saves it, and records its path. Candidate profile and job details are sent to the configured Gemini provider. |
| `get_application_review` | `job_url` | Returns the stored job, recommendation, and any cover-letter path for human review. |
| `review_application` | `job_url` | Presents the review context and elicits an explicit human `APPLIED` or `SKIPPED` decision and confirmation. Cancellation or declined confirmation leaves the job action unchanged. `APPLIED` means the person submitted manually outside this tool. |
| `get_decision_feedback` | optional `limit` (1–500) | Returns human `APPLIED`/`SKIPPED` history used as preference context for later evaluations. Agent recommendations are not fed back as human decisions. |

This server never opens or submits an application. Evaluation and generated
letters are recommendations/drafts and require human review. Configure
`GEMINI_API_KEY` for letter generation and run a local Ollama service for
evaluation; `OLLAMA_MODEL` selects the local model.

Both workflow and tracking servers use the existing `data/jobs.db` by default;
set `JOB_AGENT_DB_PATH` to point both at another existing database. They do
not create a separate tracking database.

## Jobs database server

The separate `job-agent-mcp` server exposes read-only database tools, including
`db_stats`, `list_jobs`, `get_job`, `get_feedback_history`, and
`get_recent_audit`.

## Email and calendar tracking server

Run `uv run job-agent-tracking-mcp` to start the stdio server. Configure a
Google Cloud OAuth desktop client JSON at `data/google_oauth_client.json` or
set `JOB_AGENT_GOOGLE_OAUTH_CLIENT`. Gmail and Calendar use separate local
token files, configurable with `JOB_AGENT_GMAIL_TOKEN_PATH` and
`JOB_AGENT_CALENDAR_TOKEN_PATH`. Gmail requests only
`gmail.readonly`; Calendar requests `calendar.events`.

| Tool | Input | Behavior |
| --- | --- | --- |
| `sync_application_emails` | optional `max_results` (1–500) | Reads recent Gmail messages, classifies them locally, and creates interview proposals. It never sends, marks read, or changes labels. Full bodies are processed transiently; only provider snippets up to 500 characters are stored. |
| `get_tracked_application_emails` | optional `limit` (1–500) | Lists stored email metadata and short snippets. |
| `get_pending_interview_proposals` | optional `limit` (1–500) | Lists proposals that need date/time details or human confirmation. |
| `confirm_interview_calendar_event` | `interview_id` | Elicits confirmation, shows conflicts, and creates a private event only after approval. No attendees are added and invitations are not sent. |
| `get_daily_application_digest` | optional `upcoming_days` (1–90) | Returns a local-only summary of today's email updates, proposals needing review, and upcoming confirmed interviews. It never emails the digest. |

Interview time extraction is heuristic. The confirmation flow allows corrections
and requires a valid date/time and IANA timezone; if a corrected time reveals a
calendar conflict, a separate confirmation is required. Calendar event creation
is idempotent on retries. The same digest is available locally through
`uv run job-agent-daily-digest`.
