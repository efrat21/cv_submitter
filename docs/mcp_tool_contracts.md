# MCP Tool Contracts

## Evaluation and review server

Run `uv run job-agent-workflow-mcp` to start the stdio MCP server. The server
uses the local job database and candidate files. The database path can be
overridden with `JOB_AGENT_DB_PATH`; profile and preference paths can be
overridden with `JOB_AGENT_PROFILE_PATH` and `JOB_AGENT_PREFERENCES_PATH`.

| Tool | Input | Behavior |
| --- | --- | --- |
| `evaluate_job_fit` | `job_url` | Runs deterministic matching and guarded local Ollama evaluation. Persists an agent recommendation and audit event, but does not set a human action. |
| `generate_cover_letter` | `job_url`, optional `candidate_name`, optional `use_factchecker` | Generates a draft only for a job with an `APPLY` recommendation, saves it, and records its path. Candidate profile and job details are sent to the configured Gemini provider. |
| `get_application_review` | `job_url` | Returns the stored job, recommendation, and any cover-letter path for human review. |
| `review_application` | `job_url` | Presents the review context and elicits an explicit human `APPLIED` or `SKIPPED` decision and confirmation. Cancellation or declined confirmation leaves the job action unchanged. `APPLIED` means the person submitted manually outside this tool. |
| `get_decision_feedback` | optional `limit` (1–500) | Returns human `APPLIED`/`SKIPPED` history used as preference context for later evaluations. Agent recommendations are not fed back as human decisions. |

This server never opens or submits an application. Evaluation and generated
letters are recommendations/drafts and require human review. Configure
`GEMINI_API_KEY` for letter generation and run a local Ollama service for
evaluation; `OLLAMA_MODEL` selects the local model.

## Jobs database server

The separate `job-agent-mcp` server exposes read-only database tools, including
`db_stats`, `list_jobs`, `get_job`, `get_feedback_history`, and
`get_recent_audit`.
