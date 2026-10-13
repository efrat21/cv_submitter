# Onboarding Guide: DEV.BG Job Agent (`cv_submitter`)

Welcome to the **DEV.BG Job Agent** (`devbg-job-agent`) project! This document serves as a comprehensive, fast-track onboarding guide covering the system architecture, setup instructions, workflows, project status, and key gotchas.

---

## 1. Project Overview & Mission

**Repository:** `cv_submitter`  
**Package:** `devbg-job-agent`  
**Objective:** An autonomous, AI-augmented job application agent that discovers tech jobs on [DEV.BG](https://dev.bg), evaluates candidate fit using deterministic rules and local/cloud LLMs (via Ollama), applies safety guardrails, and prepares job applications.

### Core Philosophy
1. **Candidate-Centric Filtering:** Evaluates jobs strictly against candidate facts (parsed from CV) and preferences (target roles, avoid-lists, work models, location).
2. **Two-Stage Decision Architecture:**
   - **Stage 1 (Deterministic/Heuristic Scoring):** Fast, cheap rule-based scoring and evidence checking without consuming LLM inference.
   - **Stage 2 (LLM Reasoning + Guardrails):** Structured JSON reasoning using an LLM, followed by hard Python guardrails that have the final say (safety-first: fail-safe to `SKIP`).
3. **No Blind Submissions:** Human-in-the-loop and strict verification flags prevent hallucinated fit.

---

## 2. Tech Stack

| Component | Technology | Description |
| :--- | :--- | :--- |
| **Runtime & Packaging** | Python >= 3.11, [uv](https://github.com/astral-sh/uv), Hatchling | Modern, ultra-fast Python environment and package management |
| **Web Scraping** | [Playwright](https://playwright.dev/python/) | Headless/headed Chromium browser automation for DEV.BG job discovery |
| **LLM Inference** | [Ollama](https://github.com/ollama/ollama-python) | Local/cloud LLM inference with constrained JSON schema output |
| **Database** | SQLite3 (`data/jobs.db`) | Local persistence for raw scraped jobs, deduplication, and timestamps |
| **Data Formats** | JSON, YAML, CSV | Configuration, structured profiles, match results, and decision exports |

---

## 3. Architecture & Data Flow Pipeline

The system operates across distinct milestones:

```mermaid
flowchart TD
    subgraph Milestone 1: Job Discovery
        A[DEV.BG Listing Page] -->|Playwright Scraper| B[DevBgScraper]
        B -->|Extract Details & Tech Stack| C[(SQLite: data/jobs.db)]
    end

    subgraph Profile & Preference Extraction
        D[data/cv.txt] -->|cv_parser.py| E[data/candidate_profile.json]
        F[data/candidate_preferences.yaml/json] --> G[CandidatePreferences]
    end

    subgraph Milestone 2: Fit Evaluation
        C -->|Raw Jobs| H[Stage 1: Evaluator\nevaluator.py]
        E -->|Evidence Profiles| H
        H -->|Ranked Match Scores| I[data/match_results.json]
        
        I --> J[Stage 2: Decision Agent\ndecision_agent.py]
        G --> J
        J -->|Ollama Structured JSON| K{LLM Decision}
        K -->|Python Hard Guardrails| L[Final Decision: APPLY / SKIP]
        L --> M[data/decisions.json & decisions.csv]
    end

    subgraph Milestone 3: Application & Delivery (Roadmap)
        M -->|Filtered APPLY Jobs| N[cover_letter.py (Stub)]
        N --> O[application.py (Stub)]
    end
```

---

## 4. Directory Structure

```
cv_submitter/
├── pyproject.toml              # Project dependencies (ollama, playwright) & CLI entrypoints
├── uv.lock                     # Locked dependency tree
├── README.md                   # Repository README
├── ONBOARDING.md               # Quickstart and onboarding manual (this file)
├── project structure.md        # Architectural notes
├── .env                        # Environment configuration (ignored)
│
├── data/                       # Local data directory (created at runtime)
│   ├── cv.txt                  # Raw text CV of the candidate
│   ├── jobs.db                 # SQLite database storing scraped job listings
│   ├── candidate_profile.json  # Parsed candidate skills with evidence weights
│   ├── candidate_preferences.yaml / .json # User target roles, avoid roles, locations
│   ├── match_results.json      # Output of Stage 1 deterministic scoring
│   ├── decisions.json          # Output of Stage 2 LLM + Guardrails decisions
│   └── decisions.csv           # Human-readable spreadsheet of decisions & rationales
│
├── src/
│   └── job_agent/
│       ├── __init__.py
│       ├── config.py           # Paths and default scraper settings
│       ├── models.py           # Core dataclasses: Job, CandidateProfile, CandidatePreferences,
│       │                       # MatchResult, LLMDecision, FinalDecision
│       ├── database.py         # SQLite connection manager and upsert logic
│       ├── cv_parser.py        # Regex & keyword evidence parser extracting profile from cv.txt
│       ├── filters.py          # (Stub) Additional filtering utilities
│       ├── logging_config.py   # (Stub) Logging setup
│       ├── main.py             # CLI entrypoint for scraping: `devbg-scrape`
│       │
│       ├── devbg/              # DEV.BG Scraping & Automation
│       │   ├── scraper.py      # Playwright crawler with content clean-up and tech extraction
│       │   └── application.py  # (Stub) Form filler / submission automation
│       │
│       ├── llm/                # Evaluation & Decision Engine
│       │   ├── evaluator.py    # Stage 1 deterministic rule-based scoring & ranking
│       │   ├── prompts.py      # System prompts & XML formatting for Ollama
│       │   ├── decision_agent.py # Stage 2 Ollama runner with constrained decoding & guardrails
│       │   ├── run_decisions.py  # Batch CLI runner across matches -> writes decisions.csv/json
│       │   └── cover_letter.py # (Stub) Tailored cover letter generator
│       │
│       └── dashboards/
│           └── dashboard.py    # (Stub) Analytics dashboard
│
├── tests/
│   ├── test_playwright.py      # Playwright environment sanity test
│   └── test_scraper.py         # Scraper HTML fixture tests
└── screenshots/                # Scraper debug screenshots
```

---

## 5. Getting Started (Fast Setup)

### 5.1 Prerequisites
1. **Python 3.11+**
2. **`uv` Package Manager** ([Installation Guide](https://docs.astral.sh/uv/getting-started/installation/))
3. **Ollama Running Locally or Remote** ([Ollama Download](https://ollama.com/))
   - Ensure the required model is pulled, e.g.:
     ```bash
     ollama pull qwen2.5:7b
     # or
     ollama pull deepseek-v3.2-exp:33b-cloud
     ```

### 5.2 Environment Installation
In the project root (`d:\cv_submitter`):

```bash
# 1. Sync dependencies and create virtual environment
uv sync

# 2. Install Playwright browser binaries
uv run playwright install chromium
```

---

## 6. Execution Guide (Step-by-Step Pipeline)

### Step 1: Scrape Jobs from DEV.BG (Milestone 1)
Discovers and scrapes job ads, cleans boilerplate, and saves them to SQLite:
```bash
# Run using the registered CLI command:
uv run devbg-scrape --max-jobs 10 --max-pages 1

# Or run via Python module:
uv run python -m job_agent.main --url "https://dev.bg/company/jobs/ml-ai-data/" --max-jobs 10
```

### Step 2: Parse Candidate CV
Extracts candidate skills mapped to sections (`professional`, `professional_project`, `learning`, `education`) with evidence weights:
```bash
uv run python -m job_agent.cv_parser --cv data/cv.txt --output data/candidate_profile.json
```

### Step 3: Run Stage 1 Deterministic Matcher
Scores scraped jobs against the candidate profile using weighted skill categories and verification checks:
```bash
uv run python -m job_agent.llm.evaluator --profile data/candidate_profile.json --db data/jobs.db --output data/match_results.json
```

### Step 4: Run Stage 2 Decision Agent (Milestone 2)
Runs Ollama inference with strict JSON schema constraints and applies Python safety guardrails:
```bash
uv run python -m job_agent.llm.run_decisions --model qwen2.5:7b --min-confidence 70
```
Outputs:
- `data/decisions.json`: Detailed reasoning, fit breakdown, overrides, confidence.
- `data/decisions.csv`: High-level spreadsheet summary (`APPLY` vs `SKIP`).

---

## 7. Current Project Status & Known Inconsistencies (Active Bug Alert)

> [!WARNING]
> **Active Milestone 2 Transition Discrepancies:**
> During the recent transition to structured dataclasses and Ollama JSON schemas, three data contract issues need alignment before `run_decisions.py` completes cleanly:
>
> 1. **`model_dump()` vs `to_dict()` (`src/job_agent/llm/prompts.py`):**
>    - `CandidateProfile`, `CandidatePreferences`, and `MatchResult` in [models.py](file:///d:/cv_submitter/src/job_agent/models.py) are plain `@dataclass` classes equipped with `.to_dict()`.
>    - [prompts.py](file:///d:/cv_submitter/src/job_agent/llm/prompts.py) lines 69, 79, and 80 call `.model_dump()` (a Pydantic v2 convention), raising:  
>      `AttributeError: 'MatchResult' object has no attribute 'model_dump'`.
>    - **Fix:** Replace `.model_dump()` with `.to_dict()` or convert models to Pydantic `BaseModel`.
>
> 2. **`match_results.json` vs `MatchResult.from_dict` (`src/job_agent/models.py`):**
>    - [evaluator.py](file:///d:/cv_submitter/src/job_agent/llm/evaluator.py) produces a flat JSON dictionary containing `title`, `company`, `url`, `match_score`, etc.
>    - `MatchResult.from_dict` expects a nested `{"job": {...}}` dictionary. When loaded into `run_decisions.py`, the nested `job` becomes blank.
>
> 3. **`candidate_preferences.json` root key:**
>    - `candidate_preferences.json` wraps fields inside a top-level `"candidate": {...}` object, while `CandidatePreferences.from_dict` expects direct attributes (`target_roles`, `avoid_roles`, etc.).

---

## 8. Summary of Components & Module Map

| File | Purpose | Status |
| :--- | :--- | :--- |
| [`src/job_agent/models.py`](file:///d:/cv_submitter/src/job_agent/models.py) | Dataclass definitions for Job, Candidate, MatchResult, LLMDecision, FinalDecision | Stable (needs alignment on `to_dict`) |
| [`src/job_agent/database.py`](file:///d:/cv_submitter/src/job_agent/database.py) | SQLite manager (`jobs` table with upsert on URL conflict) | Stable |
| [`src/job_agent/devbg/scraper.py`](file:///d:/cv_submitter/src/job_agent/devbg/scraper.py) | Playwright scraper with regex cleaning of Bulgarian headers & footers | Stable & Tested |
| [`src/job_agent/cv_parser.py`](file:///d:/cv_submitter/src/job_agent/cv_parser.py) | Evidence-based CV regex parser | Stable |
| [`src/job_agent/llm/evaluator.py`](file:///d:/cv_submitter/src/job_agent/llm/evaluator.py) | Stage 1 heuristic matcher & triage ranker | Stable |
| [`src/job_agent/llm/prompts.py`](file:///d:/cv_submitter/src/job_agent/llm/prompts.py) | System prompt with structured COT guidance & prompt builder | Needs `to_dict` fix |
| [`src/job_agent/llm/decision_agent.py`](file:///d:/cv_submitter/src/job_agent/llm/decision_agent.py) | Ollama client, schema validation, retry loop, Python guardrails | Implemented |
| [`src/job_agent/llm/run_decisions.py`](file:///d:/cv_submitter/src/job_agent/llm/run_decisions.py) | Batch runner iterating over matches and writing CSV/JSON | Implemented |
| [`src/job_agent/llm/cover_letter.py`](file:///d:/cv_submitter/src/job_agent/llm/cover_letter.py) | Cover letter generator | Stub (0 bytes) |
| [`src/job_agent/devbg/application.py`](file:///d:/cv_submitter/src/job_agent/devbg/application.py) | Automated application submission via Playwright | Stub (0 bytes) |
| [`src/job_agent/dashboards/dashboard.py`](file:///d:/cv_submitter/src/job_agent/dashboards/dashboard.py) | Analytics visualization | Stub (0 bytes) |

---

## 9. Immediate Roadmap / Recommended Next Steps

1. **Resolve Model Serializer Discrepancy:** Standardize on `.to_dict()` across `prompts.py` (or transition models to Pydantic v2 `BaseModel` for validation).
2. **Align MatchResult Schema:** Ensure `evaluator.py` and `MatchResult.from_dict` agree on whether `job` is nested or flattened.
3. **Integration Test Suite:** Add a mock LLM test in `tests/` verifying the end-to-end pipeline from `jobs.db` through `decisions.csv` without requiring live Ollama.
4. **Milestone 3 Implementation:** Build out `cover_letter.py` using candidate projects matching the job's core tech stack.
