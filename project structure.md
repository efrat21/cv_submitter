cv_submitter/
│
├── pyproject.toml                  # Dependencies, CLI entrypoints, MCP server registration
├── uv.lock                         # Locked dependency set
├── README.md                       # Quickstart and overview
├── ONBOARDING.md                   # Architecture, setup, and engineering manual
├── project structure.md            # File organization
├── .env                            # Local secrets (GEMINI_API_KEY)
│
├── data/
│   ├── jobs.db                    # SQLite database (legacy job store + migration tables)
│   ├── cv.txt / cv.pdf             # Candidate CV sources
│   ├── candidate_profile.json      # Parsed candidate profile
│   ├── candidate_preferences.json  # Candidate preferences
│   ├── match_results.json          # Stage 1 evaluation results
│   ├── decisions.json / .csv      # Stage 2 decision exports
│   ├── cover_letters/             # Generated cover letters
│   └── logs/                      # Runtime and debugging logs
│
├── src/
│   └── job_agent/
│       ├── __init__.py
│       ├── main.py                # Unified batch orchestrator (legacy CLI flow)
│       ├── models.py              # Dataclasses and data schemas
│       ├── config.py              # Settings and paths
│       ├── database.py            # SQLite connection, legacy migration, advanced schema
│       ├── mcp_server.py          # Initial MCP jobs-db server (read-only foundation)
│       ├── dashboard.py           # Analytics dashboard
│       ├── debug_decision.py      # Single-job trace and debugger
│       ├── cv_parser.py           # Evidence-based CV extractor
│       ├── adapters/
│       │   ├── base.py         # Shared BoardAdapter protocol
│       │   ├── devbg_adapter.py # Compatibility adapter over DevBgScraper
│       │   ├── jobsbg_adapter.py # Jobs.bg listing and job-page adapter
│       │   └── registry.py     # Board-name and domain lookup
│       ├── devbg/
│       │   ├── scraper.py      # Playwright DEV.BG scraper
│       │   └── application.py     # Playwright browser form-filler
│       ├── llm/
│       │   ├── evaluator.py       # Stage 1 rule-based matcher
│       │   ├── prompts.py         # Prompt templates and formatters
│       │   ├── decision_agent.py  # Stage 2 Ollama runner and guardrails
│       │   ├── cover_letter.py    # Gemini cover-letter writer
│       │   └── run_decisions.py   # Batch decision runner
│       │
│       └── future_mcp_servers/    # Planned MCP server split
│           ├── __init__.py
│           ├── jobs_db_server.py       # Jobs DB tools (this project: data + decisions)
│           ├── board_adapters_server.py # Listing discovery + scrape adapters
│           ├── evaluator_server.py     # Rule-eval + LLM decision tools
│           ├── cover_letters_server.py # Cover-letter generation tools
│           ├── application_review_server.py # Review and approval workflow
│           ├── email_tracker_server.py # Gmail read-only email matching + classification
│           ├── calendar_server.py      # Proposal / confirmation / event creation
│           └── host.py                 # Thin orchestrator connecting servers and tool approvals
│
├── tests/
│   ├── test_playwright.py         # Browser automation smoke tests
│   ├── test_scraper.py           # Scraper validation and fixtures
│   ├── test_migration.py         # Database migration + audit table validation
│   ├── test_adapter_parity.py    # Offline DEV.BG golden/parity tests
│   ├── test_jobsbg_adapter.py    # Offline Jobs.bg extraction tests
│   └── fixtures/
│       └── devbg/                # Saved DEV.BG listing and job pages
│       └── jobsbg/               # Saved Jobs.bg listing and job pages
│
├── screenshots/                  # Browser/session screenshots and review artifacts
│
└── docs/                         # Future docs for MCP contracts, security gates, and board adapters
    ├── mcp_tool_contracts.md
    ├── security_model.md
    └── board_adapter_registry.md