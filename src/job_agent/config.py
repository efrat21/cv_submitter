"""
Configuration settings for DEV.BG Job Agent.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Database configuration
DEFAULT_DB_PATH = BASE_DIR / "data" / "jobs.db"

# Scraper configuration
DEFAULT_JOBS_URL = "https://dev.bg/company/jobs/ml-ai-data/"
DEFAULT_MAX_JOBS = 10
DEFAULT_MAX_PAGES = 1
