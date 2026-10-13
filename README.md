# DEV.BG Job Agent (`cv_submitter`)

An autonomous job discovery, evaluation, and application screening pipeline designed to match tech jobs on [DEV.BG](https://dev.bg) with a candidate profile using Playwright and local LLMs (via Ollama).

## Quick Links
- **[Onboarding Guide](file:///d:/cv_submitter/ONBOARDING.md)** — Comprehensive architecture overview, quickstart setup, execution commands, and current milestone notes.
- **[Project Structure](file:///d:/cv_submitter/project%20structure.md)** — File organization and directory tree.

## Quickstart

```bash
# 1. Install dependencies
uv sync

# 2. Install Playwright browser
uv run playwright install chromium

# 3. Discover & scrape jobs
uv run devbg-scrape --max-jobs 10

# 4. Parse CV
uv run python -m job_agent.cv_parser

# 5. Evaluate matches
uv run python -m job_agent.llm.evaluator

# 6. Run LLM decision agent
uv run python -m job_agent.llm.run_decisions --model qwen2.5:7b
```

For detailed pipeline explanations, data formats, and development guidelines, refer to **[ONBOARDING.md](file:///d:/cv_submitter/ONBOARDING.md)**.
