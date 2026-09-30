cv_submitter/
│
├── pyproject.toml
├── README.md
├── .env
│
├── data/
│   ├── jobs.db
│   └── cv/
│       └── cv.txt
│
├── src/
│   └── job_agent/
│       │
│       ├── main.py
│       │
│       ├── models.py
│       │
│       ├── config.py
│       │
│       ├── cv_parser.py
│       │
│       ├── llm/
│       │   ├── evaluator.py
│       │   └── cover_letter.py
│       │
│       ├── devbg/
│       │   ├── scraper.py
│       │   └── application.py
│       │
│       ├── database.py
│       ├── filters.py
│       └── logging_config.py
|       |
│       └── dashboards/
│             |
│             └── dashboard.py
│
├── tests/
│
└── screenshots/