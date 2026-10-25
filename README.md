# DEV.BG Job Agent (`cv_submitter`)

An autonomous, AI-assisted job discovery, fit evaluation, and application screening pipeline designed to match tech jobs on [DEV.BG](https://dev.bg) with a candidate's profile, draft tailored cover letters, and prepare job applications in a supervised browser session.

---

## Key Features

- **Automated Web Scraping:** Playwright-based crawler that extracts Bulgarian and English job listings, cleans site boilerplate, normalizes tech tags, and skips already-processed jobs.
- **Two-Stage Fit Evaluation:**
  - **Stage 1 (Deterministic Rules):** Fast keyword and section-weighted heuristic scoring (`evaluator.py`).
  - **Stage 2 (Local LLM Reasoning via Ollama):** Constrained JSON schema inference with Chain-of-Thought reasoning (`decision_agent.py`).
- **Python Safety Guardrails:** Hard programmatic rules (seniority limits, avoided roles, work models, duplicate detection) that enforce conservative `SKIP` outcomes.
- **Continuous Feedback History Loop:** Human skip reasons are stored in SQLite and automatically injected into subsequent evaluation prompts as few-shot guidance.
- **Personalized Cover Letters:** High-impact, evidence-grounded cover letters generated via Google Gemini (`gemini-3.8-flash`) and saved to Markdown.
- **Human-in-the-Loop Browser Automation:** Playwright launches a visible browser, accepts cookies, dismisses popups, opens application forms, prefills details, and uploads the CV—leaving final submission safely to human review.
- **Real-Time Analytics Dashboard:** ASCII terminal dashboard displaying conversion rates, application statuses, and top target companies.

---

## Quick Links

- **[ONBOARDING.md](file:///d:/cv_submitter/ONBOARDING.md)** — Comprehensive architecture guide, database schema, multi-model AI setup, and bug fix history.
- **[Project Structure](file:///d:/cv_submitter/project%20structure.md)** — Directory layout and component map.

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
