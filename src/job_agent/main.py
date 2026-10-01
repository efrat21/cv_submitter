import argparse
import sys

try:
    from job_agent.database import JobDatabase
    from job_agent.devbg.scraper import DevBgScraper
except ImportError:
    from src.job_agent.database import JobDatabase
    from src.job_agent.devbg.scraper import DevBgScraper


def main():
    parser = argparse.ArgumentParser(
        description="DEV.BG Job Discovery Agent"
    )
    parser.add_argument(
        "--url",
        default="https://dev.bg/company/jobs/ml-ai-data/",
        help="Start URL to scrape (default: https://dev.bg/company/jobs/ml-ai-data/)",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=10,
        help="Maximum jobs to scrape (default: 10)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Maximum pages to scrape (default: 1)",
    )
    parser.add_argument(
        "--db",
        "--database",
        dest="database",
        default="data/jobs.db",
        help="Path to SQLite database (default: data/jobs.db)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Run browser in headless mode",
    )

    args = parser.parse_args()

    print("================================")
    print("DEV.BG JOB AGENT")
    print("Milestone 1 - Job Discovery")
    print("================================\n")
    print(f"URL: {args.url}")
    print(f"Maximum jobs: {args.max_jobs}")
    print(f"Maximum pages: {args.max_pages}")
    print(f"Database: {args.database}")

    db = JobDatabase(path=args.database)
    scraper = DevBgScraper(
        headless=args.headless,
        max_jobs=args.max_jobs,
        max_pages=args.max_pages,
    )

    try:
        scraper.run(start_url=args.url, database=db)
    finally:
        db.close()


if __name__ == "__main__":
    main()