import datetime
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

try:
    from job_agent.models import Job
except ImportError:
    from src.job_agent.models import Job

logger = logging.getLogger(__name__)


class DevBgScraper:
    """
    Playwright-based scraper for DEV.BG job listings and detailed job postings.
    """

    def __init__(
        self,
        headless: bool = False,
        delay: float = 1.5,
        max_jobs: int = 10,
        max_pages: int = 2,
    ):
        self.headless = headless
        self.delay = delay
        self.max_jobs = max_jobs
        self.max_pages = max_pages

    def discover_job_urls(self, page: Page, start_url: str) -> List[str]:
        """
        Discover job listing URLs from search/listing pages.
        """
        discovered: List[str] = []
        seen = set()

        for page_number in range(1, self.max_pages + 1):
            if page_number == 1:
                url = start_url
            else:
                separator = "&" if "?" in start_url else "?"
                url = f"{start_url}{separator}_paged={page_number}"

            print(f"\n[LISTING PAGE {page_number}]")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1000)
            except Exception as e:
                logger.warning("Failed to navigate to listing page %s: %s", url, e)
                break

            links: List[str] = page.eval_on_selector_all(
                "a[href*='/company/jobads/']",
                "elements => elements.map(el => el.href)",
            )

            print(f"Found {len(links)} candidate job links\n")

            if not links:
                break

            new_links_found = 0
            for href in links:
                if not href:
                    continue

                parsed = urlparse(href)

                if parsed.netloc.replace("www.", "") != "dev.bg":
                    continue

                if "/company/jobads/" not in parsed.path:
                    continue

                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                if clean_url in seen:
                    continue

                seen.add(clean_url)
                discovered.append(clean_url)
                new_links_found += 1

                print(f"  {len(discovered):02d}. {clean_url}")

                if self.max_jobs and len(discovered) >= self.max_jobs:
                    return discovered

            if new_links_found == 0:
                break

            time.sleep(self.delay)

        return discovered

    def scrape_job(self, page: Page, url: str) -> Job:
        """
        Scrape detailed information from a single job posting URL.
        """
        print(f"\n[JOB] {url}")

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1000)

        title = self.get_title(page)
        company = self.get_company(page)

        body = page.locator("body").inner_text()

        # Scoped metadata text around the header / apply button
        header_meta = self.extract_header_meta(body)

        location = self.get_location(header_meta, fallback_body=header_meta)
        work_model = self.get_work_model(header_meta, description=body)
        date_text = self.get_date(body)
        date_published = self.get_date_published(body, page=page)
        tags = self.get_tags(page, body=body)
        requirements, benefits = self.get_requirements_and_benefits(page, body)

        return Job(
            url=url,
            title=title,
            company=company,
            description=body,
            location=location,
            work_model=work_model,
            employment_type="Full-time",
            requirements=requirements,
            benefits=benefits,
            tags=tags,
            date_text=date_text,
            date_published=date_published,
        )

    @staticmethod
    def get_title(page: Page) -> str:
        """Extract job title from h1."""
        locator = page.locator("h1").first
        if locator.count() > 0:
            text = locator.inner_text(timeout=3000).strip()
            if text:
                return text
        return ""

    @staticmethod
    def get_company(page: Page) -> str:
        """
        Extract company name using header selectors and link heuristics in a single JS eval.
        """
        company_name = page.evaluate(
            """
            () => {
                const headerCompany = document.querySelector(
                    '.job-header a[href*="/company/"], .company-name, a.company-title, .job-meta a[href*="/company/"]'
                );
                if (headerCompany && headerCompany.textContent.trim()) {
                    return headerCompany.textContent.trim();
                }

                const links = Array.from(document.querySelectorAll('a[href*="/company/"]'));
                for (const link of links) {
                    const href = link.getAttribute('href') || '';
                    const text = (link.textContent || '').trim();
                    if (!text || text.length > 80) continue;
                    if (href.includes('/jobads/') || href.includes('/jobs/')) continue;
                    if (href.endsWith('/company/') || href.endsWith('/companies/')) continue;
                    return text;
                }
                return '';
            }
            """
        )
        return (company_name or "").strip()

    @staticmethod
    def extract_header_meta(body: str) -> str:
        """
        Extract the metadata block directly following Apply / Кандидатствай.
        This snippet contains the location (e.g. София) and work model (e.g. Hybrid).
        """
        pattern = (
            r"(?:ApplyКандидатствай|Кандидатствай|Apply)\s*\n+"
            r"(.*?)"
            r"(?=\n+\s*(?:ОБЯВАТА Е ПУБЛИКУВАНА|Обявата е публикувана|TECH STACK|ТЕХНОЛОГИИ|Публикувана|$))"
        )
        match = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
        if match and match.group(1).strip():
            return match.group(1).strip()

        lines = [line.strip() for line in body.splitlines() if line.strip()]
        for idx, line in enumerate(lines):
            if any(k in line for k in ["Кандидатствай", "Apply"]):
                return "\n".join(lines[idx + 1 : idx + 6])

        return ""

    @staticmethod
    def get_location(meta_text: str, fallback_body: str = "") -> str:
        """
        Extract location from header metadata (with fallback only if meta_text is empty).
        """
        locations = [
            "София",
            "Sofia",
            "Варна",
            "Varna",
            "Пловдив",
            "Plovdiv",
            "Бургас",
            "Burgas",
            "Русе",
            "Ruse",
            "Велико Търново",
            "Veliko Tarnovo",
            "Fully Remote",
        ]

        target = meta_text if meta_text.strip() else fallback_body
        found = []

        for location in locations:
            if location in target:
                found.append(location)

        return ", ".join(found)

    @staticmethod
    def get_work_model(meta_text: str, description: str = "") -> str:
        """
        Extract work model (Hybrid, Fully Remote, On-site).
        1. Checks normal place (header metadata block).
        2. If not found in the normal place, searches for 'hybrid' or 'remote' in the description.
        """
        # 1. Normal place: header metadata block
        if meta_text:
            if "Hybrid" in meta_text or "Хибрид" in meta_text or "Комбиниран модел" in meta_text:
                return "Hybrid"

            if "Fully Remote" in meta_text or "Изцяло дистанционно" in meta_text:
                return "Fully Remote"

            if "On-site" in meta_text or "В офис" in meta_text:
                return "On-site"

        # 2. Fallback: Search in job description
        if description:
            # Strip site headers, navigation, and footers so nav links like
            # "Fully Remote IT обяви" are not falsely matched
            content = description
            if "TECH STACK / ИЗИСКВАНИЯ" in content:
                content = content.split("TECH STACK / ИЗИСКВАНИЯ", 1)[1]
            elif "ОБЯВАТА Е ПУБЛИКУВАНА" in content:
                content = content.split("ОБЯВАТА Е ПУБЛИКУВАНА", 1)[1]
            elif "Кандидатствай" in content:
                content = content.split("Кандидатствай", 1)[1]

            for footer_marker in [
                "DEV.BG Logo",
                "Job board за IT обяви",
                "Споразумение за обработване",
            ]:
                if footer_marker in content:
                    content = content.split(footer_marker, 1)[0]

            content_lower = content.lower()

            has_hybrid = bool(
                re.search(
                    r"\b(?:hybrid|хибрид|хибриден|хибридна|хибридно|комбиниран модел)\b",
                    content_lower,
                )
            )
            has_remote = bool(
                re.search(
                    r"\b(?:remote|дистанционн[оае]|fully remote|work from home|home office)\b",
                    content_lower,
                )
            )

            if has_hybrid:
                return "Hybrid"
            elif has_remote:
                return "Fully Remote"
            else:
                return "On-site"

        return ""

    @staticmethod
    def get_date(body: str) -> str:
        """
        Extract raw post date string supporting both calendar dates and relative Bulgarian date strings.
        """
        pattern = (
            r"(?:Публикувана\s+)?(?:преди\s+\d+\s+(?:час[а]?|дни|ден|седмиц[аи]|месец[а]?)|"
            r"\b\d{1,2}\s+(?:ян\.|фев\.|мар\.|апр\.|май|юни|юли|авг\.|сеп\.|окт\.|ное\.|дек\.))"
        )

        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(0).strip()

        return ""

    @classmethod
    def get_date_published(
        cls, body: str, page: Optional[Page] = None
    ) -> str:
        """
        Fill the 'date published' field by extracting and standardizing
        the publication date (e.g. 'YYYY-MM-DD').
        Checks DOM meta/time tags first, then parses relative or calendar dates.
        """
        # 1. Try DOM elements with explicit datetime
        if page is not None:
            try:
                dom_date = page.evaluate(
                    """
                    () => {
                        const timeEl = document.querySelector('time[datetime], [itemprop="datePublished"]');
                        if (timeEl) {
                            return timeEl.getAttribute('datetime') || timeEl.getAttribute('content') || timeEl.innerText;
                        }
                        const metaEl = document.querySelector('meta[property="article:published_time"]');
                        if (metaEl) {
                            return metaEl.getAttribute('content');
                        }
                        return '';
                    }
                    """
                )
                if dom_date:
                    # Clean up to YYYY-MM-DD if ISO format
                    match_iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", dom_date)
                    if match_iso:
                        return match_iso.group(0)
            except Exception as e:
                logger.debug("Failed to read DOM datetime: %s", e)

        # 2. Extract date text from body
        raw_date = cls.get_date(body)
        if not raw_date:
            return ""

        today = datetime.date.today()
        lower = raw_date.lower()

        # Hours or minutes ago -> today
        if "час" in lower or "минут" in lower:
            return today.isoformat()

        # Days ago: преди X дни / преди 1 ден
        match_days = re.search(r"преди\s+(\d+)\s+д", lower)
        if match_days:
            days = int(match_days.group(1))
            return (today - datetime.timedelta(days=days)).isoformat()

        if "вчера" in lower:
            return (today - datetime.timedelta(days=1)).isoformat()

        # Weeks ago: преди X седмици / седмица
        match_weeks = re.search(r"преди\s+(\d+)\s+седмиц", lower)
        if match_weeks:
            weeks = int(match_weeks.group(1))
            return (today - datetime.timedelta(weeks=weeks)).isoformat()

        if "преди седмица" in lower:
            return (today - datetime.timedelta(weeks=1)).isoformat()

        # Months ago: преди X месеца / месец
        match_months = re.search(r"преди\s+(\d+)\s+месец", lower)
        if match_months:
            months = int(match_months.group(1))
            return (today - datetime.timedelta(days=30 * months)).isoformat()

        if "преди месец" in lower:
            return (today - datetime.timedelta(days=30)).isoformat()

        # Calendar date: e.g. "15 сеп." or "28 фев."
        months_map = {
            "ян": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "юни": 6,
            "юли": 7, "авг": 8, "сеп": 9, "окт": 10, "ное": 11, "дек": 12,
        }
        match_cal = re.search(r"(\d{1,2})\s+([а-я]+)", lower)
        if match_cal:
            day = int(match_cal.group(1))
            month_str = match_cal.group(2)[:3]
            if month_str in months_map:
                month = months_map[month_str]
                year = today.year
                if month > today.month:
                    year -= 1
                try:
                    return datetime.date(year, month, day).isoformat()
                except ValueError:
                    pass

        return raw_date

    @staticmethod
    def get_tags(page: Optional[Page] = None, body: str = "") -> List[str]:
        """
        Extract tech stack tags and categories, filtering out UI/social/system icon alts.
        """
        results = []

        if page is not None:
            raw_tags = page.evaluate(
                """
                () => {
                    const list = [];
                    const selectors = [
                        '.tech-stack a', '.tech-stack span',
                        '.jobad-tech-stack a', '.jobad-tech-stack span',
                        '.job-badges span', '.job-tags a', '.job-tags span',
                        'a[href*="/company/jobs/"]', 'a[href*="/tag/"]'
                    ];
                    for (const sel of selectors) {
                        for (const el of document.querySelectorAll(sel)) {
                            const text = (el.textContent || '').trim();
                            if (text && text.length >= 2 && text.length <= 50) {
                                list.push(text);
                            }
                        }
                    }
                    return list;
                }
                """
            )
            results.extend(raw_tags)

        cat_match = re.search(
            r"(?:ОБЯВАТА Е ПУБЛИКУВАНА В СЛЕДНИТЕ КАТЕГОРИИ|Обявата е публикувана в следните категории)\s*\n+([^\n]+)",
            body,
            re.IGNORECASE,
        )
        if cat_match:
            cat_line = cat_match.group(1).strip()
            cleaned_cats = re.split(r"\d+", cat_line)
            for c in cleaned_cats:
                c = c.strip()
                if len(c) >= 2:
                    results.append(c)

        ignored_keywords = [
            "icon", "arrow", "separator", "toggle", "apply", "реклама", "ad",
            "logo", "banner", "button", "house", "building", "office",
            "additional info", "кандидатствай", "social", "facebook", "linkedin",
            "youtube", "tiktok", "instagram", "dev.bg", "виж обявата", "на картата",
            "запази", "съобщи проблем", "преди"
        ]

        cleaned_tags = []
        seen = set()

        for tag in results:
            tag_clean = tag.strip()
            lower = tag_clean.lower()

            if any(bad in lower for bad in ignored_keywords):
                continue

            if 2 <= len(tag_clean) <= 60 and lower not in seen:
                seen.add(lower)
                cleaned_tags.append(tag_clean)

        return cleaned_tags[:30]

    @staticmethod
    def get_requirements_and_benefits(
        page: Optional[Page], body: str
    ) -> Tuple[List[str], List[str]]:
        """
        Parse requirement and benefit bullet points from job content.
        """
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        requirements: List[str] = []
        benefits: List[str] = []
        current_section = None

        req_headers = [
            "requirements",
            "изисквания",
            "required skills",
            "qualifications",
            "what you need",
            "your profile",
            "good to have",
            "желани умения",
            "nice to have",
            "must have",
            "skills & experience",
        ]

        ben_headers = [
            "what we offer",
            "why work with us",
            "какво предлагаме",
            "benefits",
            "придобивки",
            "what you get",
            "perks",
            "our offer",
            "защо да изберете нас",
        ]

        stop_headers = [
            "about the role",
            "responsibilities",
            "отговорности",
            "what you'll do",
            "how to apply",
            "как да кандидатствате",
            "за компанията",
            "about us",
            "about the company",
            "if you are interested",
            "confidentiality of all applications",
            "by submitting your application",
            "кандидатствай",
            "scaling innovation",
        ]

        for line in lines:
            lower = line.lower().strip(":").strip()

            if "tech stack / изисквания" in lower or "tech stack" == lower:
                current_section = None
                continue

            if any(lower == h or lower.startswith(f"{h}:") or lower.startswith(f"{h} ") or h in lower for h in req_headers):
                current_section = "req"
                continue
            elif any(lower == h or lower.startswith(f"{h}:") or lower.startswith(f"{h} ") or h in lower for h in ben_headers):
                current_section = "ben"
                continue
            elif any(lower == h or lower.startswith(f"{h}:") or lower.startswith(f"{h} ") or h in lower for h in stop_headers):
                current_section = None
                continue

            if current_section == "req" and line:
                if len(line) > 5 and not line.endswith(":"):
                    requirements.append(line)
            elif current_section == "ben" and line:
                if len(line) > 5 and not line.endswith(":"):
                    benefits.append(line)

        return requirements[:30], benefits[:30]

    def run(self, start_url: str, database: Any = None) -> List[Job]:
        """
        Execute the scraper. If database is supplied, saves jobs to the database.
        Returns the list of successfully scraped Job objects.
        """
        with sync_playwright() as p:
            print("\nStarting Chromium...")
            browser = p.chromium.launch(headless=self.headless)

            try:
                context = browser.new_context(
                    locale="bg-BG",
                    viewport={"width": 1440, "height": 1000},
                )
                page = context.new_page()

                job_urls = self.discover_job_urls(page, start_url)
                print(f"\nDiscovered {len(job_urls)} jobs.")

                scraped_jobs: List[Job] = []

                for number, url in enumerate(job_urls, start=1):
                    try:
                        job = self.scrape_job(page, url)
                        scraped_jobs.append(job)

                        if database is not None and hasattr(database, "save_job"):
                            try:
                                database.save_job(job)
                            except TypeError:
                                database.save_job(job.to_dict())

                        print(
                            f"[SAVED {number}/{len(job_urls)}] {job.title}"
                        )
                    except Exception as error:
                        logger.error("[ERROR] Failed to scrape %s: %s", url, error)

                    time.sleep(self.delay)

                return scraped_jobs
            finally:
                browser.close()


def fetch_jobs(
    start_url: str = "https://devbg.com/jobs",
    max_jobs: int = 10,
    headless: bool = True,
) -> List[Job]:
    """
    Convenience function to scrape jobs from a given DEV.BG start URL.
    """
    scraper = DevBgScraper(headless=headless, max_jobs=max_jobs)
    return scraper.run(start_url)


def parse_job(text: str, url: str = "https://devbg.com/jobs") -> Job:
    """
    Parse a raw text job listing (e.g. from DEV.BG copy or mock text) into a Job instance.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    company = ""
    title = ""
    for idx, line in enumerate(lines):
        if "Кандидатствай" in line or "Apply" in line:
            if idx >= 1:
                title = lines[idx - 1]
            if idx >= 2:
                company = lines[idx - 2]
            break

    if not title:
        title = lines[0] if lines else "Unknown Title"
    if not company:
        company = lines[1] if len(lines) > 1 else "Unknown Company"

    header_meta = DevBgScraper.extract_header_meta(text)
    location = DevBgScraper.get_location(header_meta, fallback_body=text)
    work_model = DevBgScraper.get_work_model(header_meta, description=text)
    date_text = DevBgScraper.get_date(text)
    date_published = DevBgScraper.get_date_published(text)
    tags = DevBgScraper.get_tags(None, body=text)

    reqs, bens = DevBgScraper.get_requirements_and_benefits(None, text)

    return Job(
        url=url,
        title=title,
        company=company,
        description=text.strip(),
        location=location or "София",
        work_model=work_model or "On-site",
        employment_type="Full-time",
        requirements=reqs,
        benefits=bens,
        tags=tags,
        date_text=date_text,
        date_published=date_published,
    )


__all__ = ["DevBgScraper", "Job", "fetch_jobs", "parse_job"]