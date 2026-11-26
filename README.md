# DEV.BG Job Agent (`cv_submitter`)

An autonomous, AI-assisted job discovery, fit evaluation, and application screening pipeline designed to match tech jobs on [DEV.BG](https://dev.bg) with a candidate's profile, draft tailored cover letters, and prepare job applications in a supervised browser session.

---

## Key Features

- **Automated Web Scraping:** Playwright-based crawler that extracts Bulgarian and English job listings, cleans site boilerplate, normalizes tech tags, and skips already-processed jobs.
- **Two-Stage Fit Evaluation:**
  - **Stage 1 (Deterministic Rules):** Fast keyword and section-weighted heuristic scoring (`evaluator.py`).
  - **Stage 2 (Local LLM Reasoning via Ollama):** Constrained JSON-schema evaluation with a concise rationale (`decision_agent.py`).
- **Python Safety Guardrails:** Hard programmatic rules (seniority limits, avoided roles, work models, duplicate detection) that enforce conservative `SKIP` outcomes.
- **Continuous Feedback History Loop:** Human skip reasons are stored in SQLite and automatically injected into subsequent evaluation prompts as few-shot guidance.
- **Personalized Cover Letters:** High-impact, evidence-grounded cover letters generated via Google Gemini (`gemini-3.8-flash`) and saved to Markdown.
- **Email and Interview Tracking:** Read-only Gmail sync classifies application updates, matches messages conservatively to applied jobs, and prepares editable interview proposals.
- **Human-Gated Calendar Events:** Interview events are written to Google Calendar only after explicit MCP elicitation; events have no attendees and do not send invitations.
- **Local Daily Digest:** A local CLI/MCP digest summarizes new email, proposals needing review, and upcoming confirmed interviews. It is never emailed.
- **Natural-Language MCP Host:** `job-agent chat` connects the jobs, workflow, and tracking MCP servers. Tool access is allowlisted; application and calendar changes remain behind human confirmations.
- **Scheduled Daily Preparation:** `job-agent daily` prepares jobs without opening the review UI, syncs Gmail, and prints the digest locally. The Windows scheduled task uses this non-interactive path.
- **Decision Regression Harness:** `job-agent evaluate-regressions` compares fresh model decisions with stored human decisions and separately reports consistency with legacy agent rejections. It does not update the database.
- **Human-in-the-Loop Browser Automation:** Playwright launches a visible browser, accepts cookies, dismisses popups, opens application forms, prefills details, and uploads the CV—leaving final submission safely to human review.
- **Real-Time Analytics Dashboard:** ASCII terminal dashboard displaying conversion rates, application statuses, and top target companies.

---

## Quick Links

- **[ONBOARDING.md](file:///d:/cv_submitter/ONBOARDING.md)** — Comprehensive architecture guide, database schema, multi-model AI setup, and bug fix history.
- **[Project Structure](file:///d:/cv_submitter/project%20structure.md)** — Directory layout and component map.
- **[Chat Model Benchmark](docs/chat_model_benchmark.md)** — Local Ollama and Colibri chat-agent trial results.

---

## Quickstart

### 1. Prerequisites
- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** package manager
- **[Ollama](https://ollama.com/)** with `qwen2.5:7b` (or chosen model):
  ```bash
  ollama pull qwen2.5:7b
  ```
- **Google Gemini API Key** in `.env`:
  ```env
  GEMINI_API_KEY="your-gemini-api-key"
  ```

### 2. Install Environment & Playwright
```bash
# Sync virtual environment & locked dependencies
uv sync

# Install Chromium browser binaries
uv run playwright install chromium
```

### 3. Run the Unified Batch Orchestrator
Launch the end-to-end interactive agent pipeline (Discovery -> Fit Assessment -> Cover Letters -> Browser Review -> Dashboard):

```bash
uv run python src/job_agent/main.py \
    --batch-size 5 \
    --cv "data/cv.pdf" \
    --name "Your Full Name" \
    --email "your.email@example.com" \
    --url "https://dev.bg/company/jobs/ml-ai-data/" \
    --model qwen2.5:7b
```

### 4. MCP Jobs DB Server (read-only foundation)
The deterministic job store is now exposed as an MCP server for orchestration clients while keeping the legacy CLI flow intact.

```bash
uv run job-agent-mcp
```

The server exposes read-only tools such as `db_stats`, `list_jobs`, `get_job`, `get_feedback_history`, and `get_recent_audit` over stdio transport.

This is an MCP backend, not an interactive command: when run by itself, it
waits quietly for an MCP client on stdin/stdout. To use the assistant, run
`uv run job-agent chat`; it starts the jobs, workflow, and tracking servers
automatically. Use `job-agent-mcp` directly only when configuring another MCP
client to launch it.

### 5. MCP Evaluation and Review Server
The workflow server provides evaluation, cover-letter drafts, review packets, and human-confirmed feedback. It is separate from the read-only jobs database server:

```bash
uv run job-agent-workflow-mcp
```

It exposes `evaluate_job_fit`, `generate_cover_letter`, `get_application_review`, `review_application`, and `get_decision_feedback` over stdio. It uses the existing `data/jobs.db`; `JOB_AGENT_DB_PATH` can point both workflow and tracking servers at the same existing database. Evaluation saves an agent recommendation without changing the human `APPLIED`/`SKIPPED` action and skips jobs already evaluated or applied to. `review_application` asks for explicit human confirmation; this server never submits applications. Cover-letter generation sends the candidate profile and job details to the configured Gemini provider.

The workflow expects `data/candidate_profile.json`, `data/candidate_preferences.json`, a local Ollama service, and `GEMINI_API_KEY` for cover letters. Set `JOB_AGENT_DB_PATH`, `JOB_AGENT_PROFILE_PATH`, `JOB_AGENT_PREFERENCES_PATH`, or `OLLAMA_MODEL` to override the corresponding defaults.

### 6. Email and Calendar Tracking
Create a Google Cloud OAuth desktop client, enable the Gmail API and Google Calendar API, and save its client JSON as `data/google_oauth_client.json` (or set `JOB_AGENT_GOOGLE_OAUTH_CLIENT`). The first Gmail sync and Calendar access each open Google's consent flow and save separate local tokens under `data/`; grant only the requested scopes.

Start the tracking MCP server:

```bash
uv run job-agent-tracking-mcp
```

Its tools sync/read Gmail, list tracked email and pending interview proposals, request explicit confirmation before creating calendar events, and return a local-only daily digest. Gmail sync does not mark messages read or change labels. Interview events are private, contain no attendees, and send no invitations. Correct extracted date/time/timezone details during confirmation; missing details must be supplied before an event can be created.

Print the daily digest locally:

```bash
uv run job-agent-daily-digest
```

Set `JOB_AGENT_GMAIL_TOKEN_PATH` and `JOB_AGENT_CALENDAR_TOKEN_PATH` to change the separate OAuth token locations.

### 7. Agent Host and Scheduling

Start interactive natural-language control (local Ollama by default):

```bash
uv run job-agent chat
```

The host starts only the configured local MCP servers and exposes an allowlist
of their tools. Job postings and email text returned by those tools are treated
as untrusted data. Review and calendar tools retain their in-band confirmation
prompts; cover-letter generation asks before sending candidate/job data to
Gemini.
Boolean consent prompts can be answered `y`; multi-field review forms accept a
JSON object matching the fields shown in the terminal.

Run the unattended daily preparation and local digest:

```bash
uv run job-agent daily --name "Your Name" --email "you@example.com"
```

This runs the existing routine with `--no-review`, then syncs Gmail and prints
the digest. Remote cover-letter generation is off by default; enabling
`--allow-remote-letters` sends candidate profile and job details to Gemini.
It does not submit applications, approve calendar events, or email the digest.
For a digest without job preparation or Gmail access, use
`--skip-job-prep --skip-email-sync`.

For interactive job review, use the **Run Job Agent Daily** desktop shortcut.
It runs `run_daily_review.bat` directly and waits for your decision on each
recommended job; the scheduled task remains non-interactive.

Configure the chat model with `JOB_AGENT_AGENT_PROVIDER=ollama` (default),
`JOB_AGENT_AGENT_MODEL`, and `OLLAMA_HOST`. An OpenAI-compatible provider can
be selected with `JOB_AGENT_AGENT_PROVIDER=openai-compatible`, with
`JOB_AGENT_AGENT_BASE_URL` and `JOB_AGENT_AGENT_MODEL`. Remote endpoints are
blocked unless `JOB_AGENT_ALLOW_REMOTE_AGENT_DATA=true` is set; enabling this
allows chat content and MCP results, potentially including candidate and email
data, to leave the machine. Keep `OPENAI_API_KEY` in the environment, not in
the repository. The daily task does not use this chat provider.

Evaluate stored decisions without changing them:

```bash
uv run job-agent evaluate-regressions
```

The harness uses `APPLIED`/`SKIPPED` as human reference labels, excludes each
case from its own history examples, and reports `NOT_RECOMMENDED` cases
separately as legacy-agent consistency checks.

Register or update the Windows daily task (it runs preparation only; review
remains interactive and remote cover letters are off by default):

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_daily_task.ps1 -Name "Your Name" -Email "you@example.com"
```

Use `-AllowRemoteLetters` only if you explicitly want the scheduled run to
send candidate profile and job details to Gemini when drafting letters.

---

## Workflow & Step Skipping

The orchestrator operates in cyclical batches of 3 steps:
1. **Step 1:** Scrape new jobs from DEV.BG into `data/jobs.db`.
2. **Step 2:** Evaluate job fit with Ollama and generate cover letters with Gemini.
3. **Step 3:** Open visible browser review and prefill application forms.

You can selectively bypass steps using `--skip_step`:
```bash
# Skip scraping and evaluate existing database jobs directly:
uv run python src/job_agent/main.py --skip_step 1 --batch-size 5

# Skip scraping & LLM evaluation (open browser review for pre-evaluated jobs):
uv run python src/job_agent/main.py --skip_step 1 2
```

---

## Standalone Commands

| Task | Command | Description |
| :--- | :--- | :--- |
| **Parse CV** | `uv run python -m job_agent.cv_parser --cv data/cv.txt` | Extracts skills, sections, and evidence into `data/candidate_profile.json` |
| **Stage 1 Matcher** | `uv run python -m job_agent.llm.evaluator` | Heuristic rule-based matching against `jobs.db` |
| **Stage 2 Decisions** | `uv run python -m job_agent.llm.run_decisions --model qwen2.5:7b` | Batch Ollama inference writing `decisions.json` and `decisions.csv` |
| **Cover Letters** | `uv run python -m job_agent.llm.cover_letter --candidate-name "Name"` | Generates Markdown cover letters for all `APPLY` jobs |
| **Debug Single Job** | `uv run python -m job_agent.debug_decision <url> --show-prompt` | Inspects scraping, pre-match, history, raw LLM prompt, and guardrails for 1 URL |
| **Analytics Dashboard**| `uv run python -m job_agent.dashboard --recent 10` | Displays application statistics and status breakdown |

---

## Safety & Ethics Principles

- **No Blind Applications:** The system never submits application forms automatically. A human always reviews the filled fields and clicks Submit.
- **No CAPTCHA Bypass:** The agent does not bypass anti-bot, CAPTCHA, or Cloudflare challenges.
- **Evidence-Only Experience:** Cover letters and evaluation rationales are strictly grounded in candidate facts from `candidate_profile.json`.

For in-depth architectural details, refer to **[ONBOARDING.md](file:///d:/cv_submitter/ONBOARDING.md)**.

## Board Adapter Layer

The adapter contract and registry are in `src/job_agent/adapters/`.
`DevBgAdapter` delegates to the existing scraper to preserve its behavior;
`JobsBgAdapter` handles Jobs.bg pages; and the generic JSON-LD-first adapter
supports selector recipes, including public LinkedIn job pages. Offline
coverage uses saved HTML fixtures:

```bash
uv run pytest tests/test_adapter_parity.py tests/test_jobsbg_adapter.py tests/test_generic_adapters.py -q
```
