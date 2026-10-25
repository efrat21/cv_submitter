cv_submitter/
│
├── pyproject.toml              # Project dependencies and CLI entrypoints
├── uv.lock                     # Pinned dependencies
├── README.md                   # Quickstart and overview
├── ONBOARDING.md               # Architecture, setup, and engineering manual
├── project structure.md        # File organization
├── .env                        # Local secrets (GEMINI_API_KEY)
│
├── data/
│   ├── jobs.db                 # SQLite database
│   ├── cv.txt / cv.pdf         # Candidate CV sources
│   ├── candidate_profile.json  # Parsed candidate profile
│   ├── candidate_preferences.json # Candidate preferences
│   ├── match_results.json      # Stage 1 evaluation results
│   ├── decisions.json / .csv   # Stage 2 decision exports
│   └── cover_letters/          # Generated cover letters
│
├── src/
│   └── job_agent/
│       ├── __init__.py
│       ├── main.py             # Unified batch orchestrator
│       ├── models.py           # Dataclasses & schemas
│       ├── config.py           # Settings and paths
│       ├── database.py         # SQLite connection and feedback history
│       ├── dashboard.py        # Analytics conversion dashboard
│       ├── debug_decision.py   # Single-job trace and debugger
│       ├── cv_parser.py        # Evidence-based CV extractor
│       │
│       ├── devbg/
│       │   ├── scraper.py      # Playwright DEV.BG scraper
│       │   └── application.py  # Playwright browser form-filler
│       │
│       └── llm/
│           ├── evaluator.py    # Stage 1 rule-based matcher
│           ├── prompts.py      # Prompt templates & formatters
│           ├── decision_agent.py # Stage 2 Ollama runner & guardrails
│           ├── cover_letter.py # Gemini cover letter writer
│           └── run_decisions.py# Batch decision runner
│
├── tests/
│   ├── test_playwright.py
│   └── test_scraper.py
└── screenshots/