"""
Milestone 4: browser-assisted job application form filler.

Safety design:
- Opens a visible browser.
- Does not click Submit/Send/Apply after filling.
- Does not solve or bypass CAPTCHA, MFA, or anti-bot checks.
- Prints which fields were filled and leaves the page open for human review.

Run from the project root:
    uv run python scripts/browser_apply.py --url "https://example.com/job" \
        --name "Your Name" --email "you@example.com" --cv "data/cv.pdf"

Optional:
    --cover-letter-file data/cover_letter.txt
    --headed  (headed mode is already the default; retained for clarity)
"""

from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path
from typing import Iterable

from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


# Only fill fields whose accessible name/placeholder clearly suggests the value.
FIELD_PATTERNS = {
    "name": re.compile(r"\b(full\s*name|your\s*name|name|име|пълно име)\b", re.I),
    "email": re.compile(r"\b(e-?mail|email address|електронна поща)\b", re.I),
    "phone": re.compile(r"\b(phone|mobile|telephone|телефон)\b", re.I),
    "cover_letter": re.compile(
        r"\b(cover letter|message|why.*(you|role)| мотивационно писмо|съобщение)\b",
        re.I,
    ),
}

APPLY_BUTTON_NAMES = re.compile(
    r"^(apply|apply now|apply for this job|candidate|кандидатствай|кандидатстване)$",
    re.I,
)

SUBMIT_BUTTON_NAMES = re.compile(
    r"(submit|send application|submit application|send|изпрати кандидатура|кандидатствай)$",
    re.I,
)


def normalize(value: str) -> str:
    return " ".join(value.lower().split())


async def first_visible(locator: Locator) -> Locator | None:
    """Return the first visible match, if any."""
    try:
        count = await locator.count()
        for i in range(min(count, 20)):
            candidate = locator.nth(i)
            if await candidate.is_visible():
                return candidate
    except Exception:
        return None
    return None


async def find_field(page: Page, pattern: re.Pattern[str]) -> Locator | None:
    """Find a visible text input/textarea by label, placeholder, or name."""
    # Prefer Playwright's accessible-label lookup.
    for role in ("textbox",):
        try:
            locator = page.get_by_role(role, name=pattern)
            found = await first_visible(locator)
            if found is not None:
                return found
        except Exception:
            pass

    # Labels are often more reliable than placeholder text.
    try:
        locator = page.get_by_label(pattern)
        found = await first_visible(locator)
        if found is not None:
            return found
    except Exception:
        pass

    # Fall back to common input attributes; never target hidden controls.
    selectors = [
        "input:not([type='hidden']):not([type='file'])",
        "textarea",
        "[contenteditable='true']",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = await locator.count()
            for i in range(min(count, 100)):
                field = locator.nth(i)
                if not await field.is_visible() or not await field.is_enabled():
                    continue
                attrs = []
                for attr in ("aria-label", "placeholder", "name", "id", "autocomplete"):
                    try:
                        attrs.append(await field.get_attribute(attr) or "")
                    except Exception:
                        pass
                descriptor = " ".join(attrs)
                if pattern.search(descriptor):
                    return field
                # For id/name, also inspect a matching associated label.
                field_id = await field.get_attribute("id")
                if field_id:
                    try:
                        label_text = await page.locator(f"label[for='{field_id}']").inner_text()
                        if pattern.search(label_text):
                            return field
                    except Exception:
                        pass
        except Exception:
            continue
    return None


async def safe_fill(page: Page, label: str, pattern: re.Pattern[str], value: str | None,
                    filled: list[str]) -> None:
    if not value:
        return
    field = await find_field(page, pattern)
    if field is None:
        print(f"[NOT FOUND] {label} field")
        return
    try:
        await field.fill(value)
        print(f"[FILLED] {label}")
        filled.append(label)
    except Exception as exc:
        print(f"[SKIPPED] {label}: {type(exc).__name__}: {exc}")

async def upload_cv(page: Page, cv_path: Path | None) -> bool:
    if cv_path is None:
        return False
    if not cv_path.exists() or not cv_path.is_file():
        print(f"[ERROR] CV file does not exist: {cv_path}")
        return False

    try:
        file_inputs = page.locator("input[type='file']")
        count = await file_inputs.count()
        for i in range(count):
            control = file_inputs.nth(i)
            # File inputs can be hidden but still usable by set_input_files.
            accept = (await control.get_attribute("accept") or "").lower()
            name = (await control.get_attribute("name") or "").lower()
            description = f"{accept} {name}"
            if any(term in description for term in ("cv", "resume", "pdf", "doc")) or count == 1:
                await control.set_input_files(str(cv_path.resolve()))
                print(f"[FILLED] CV upload ({cv_path.name})")
                return True
        print("[NOT FOUND] A clearly identifiable CV upload field")
    except Exception as exc:
        print(f"[SKIPPED] CV upload: {type(exc).__name__}: {exc}")
    return False

POPUP_CLOSE_SELECTORS = [
    '[aria-label="Close" i]',
    '[aria-label="Затвори" i]',
    "button.close",
    ".modal .close",
    '[class*="popup"] [class*="close"]',
    '[class*="modal"] [class*="close"]',
    "button:has-text('×')",
    "button:has-text('Close')",
    "button:has-text('Затвори')",
]

COOKIE_ACCEPT_SELECTORS = [
    '[data-cky-tag="accept-button"]',   # CookieYes (dev.bg)
    "button.cky-btn-accept",
]


async def accept_cookies(page: Page) -> bool:
    for selector in COOKIE_ACCEPT_SELECTORS:
        btn = page.locator(selector).first
        try:
            if await btn.is_visible():
                await btn.click(timeout=2000)
                await page.locator(".cky-consent-container").wait_for(
                    state="hidden", timeout=3000
                )
                print("[INFO] Cookie banner accepted.")
                return True
        except Exception:
            pass
    return False

# Something that only exists in the REAL application form (CV upload is a good marker).
# Adjust after inspecting the dev.bg form.
FORM_MARKER = "input[type=file], form textarea"


async def dismiss_popups(page: Page) -> int:
    closed = 1 if await accept_cookies(page) else 0
    for selector in POPUP_CLOSE_SELECTORS:
        loc = page.locator(selector)
        for i in range(await loc.count()):
            el = loc.nth(i)
            try:
                if await el.is_visible():
                    await el.click(timeout=1000)
                    closed += 1
                    await page.wait_for_timeout(300)
            except Exception:
                pass
    await page.keyboard.press("Escape")
    return closed


async def application_form_visible(page: Page, timeout: int = 4000) -> bool:
    try:
        await page.locator(FORM_MARKER).first.wait_for(state="visible", timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        return False
        


async def maybe_open_application_form(page: Page) -> Optional[Page]:
    """Returns the page containing a visible application form, or None if it couldn't be opened."""
    for attempt in range(1, 4):
        n = await dismiss_popups(page)
        if n:
            print(f"[INFO] Closed {n} popup(s) before clicking.")

        target = None
        for role in ("link", "button"):
            target = await first_visible(page.get_by_role(role, name=APPLY_BUTTON_NAMES))
            if target is not None:
                break
        if target is None:
            print("[INFO] No clearly labelled Apply control found.")
            return None

        pages_before = set(page.context.pages)
        url_before = page.url
        print(f"[INFO] Opening the application form (attempt {attempt})...")

        try:
            await target.scroll_into_view_if_needed()
            await target.click(timeout=3000)
        except PlaywrightTimeoutError:
            print("[WARN] Click blocked, closing popups and retrying...")
            await dismiss_popups(page)
            try:
                # Last resort: dispatch the click in JS, bypassing the overlay
                await target.evaluate("e => e.click()")
            except Exception as exc:
                print(f"[WARN] JS click failed: {type(exc).__name__}: {exc}")
                continue
        except Exception as exc:
            print(f"[WARN] Click failed: {type(exc).__name__}: {exc}")
            continue

        await page.wait_for_timeout(1000)

        # New tab?
        new_pages = [p for p in page.context.pages if p not in pages_before]
        if new_pages:
            page = new_pages[-1]
            await page.wait_for_load_state("domcontentloaded")

        # Verify, don't assume
        if await application_form_visible(page):
            print(f"[INFO] Application form is open: {page.url}")
            return page

        # A popup may have appeared AFTER the click and swallowed it
        print("[WARN] Form not visible after click.")

    print("[ERROR] Could not open the application form.")
    return None

async def describe_form(page: Page) -> None:
    """Print a small inventory of visible form controls for debugging."""
    print("\n--- Visible form controls (for manual inspection) ---")
    try:
        fields = page.locator("input:not([type='hidden']), textarea, select, [contenteditable='true']")
        count = await fields.count()
        shown = 0
        for i in range(min(count, 100)):
            field = fields.nth(i)
            try:
                if not await field.is_visible():
                    continue
                kind = await field.get_attribute("type") or await field.evaluate("(e) => e.tagName.toLowerCase()")
                attrs = []
                for attr in ("aria-label", "placeholder", "name", "id", "autocomplete", "accept"):
                    val = await field.get_attribute(attr)
                    if val:
                        attrs.append(f"{attr}={val!r}")
                print(f"- {kind}: " + (", ".join(attrs) if attrs else "(no descriptive attributes)"))
                shown += 1
                if shown >= 40:
                    break
            except Exception:
                continue
        if shown == 0:
            print("(No visible form controls detected on this page.)")
    except Exception as exc:
        print(f"(Could not inspect controls: {type(exc).__name__}: {exc})")
    print("----------------------------------------------------\n")


async def run(args: argparse.Namespace) -> None:
    print(("starting job appication"))
    url = args.url.strip()
    if not re.match(r"^https?://", url, re.I):
        raise SystemExit("--url must start with http:// or https://")

    cv_path = Path(args.cv).expanduser() if args.cv else None
    letter = None
    if args.cover_letter_file:
        letter_path = Path(args.cover_letter_file).expanduser()
        if not letter_path.exists():
            raise SystemExit(f"Cover-letter file not found: {letter_path}")
        letter = letter_path.read_text(encoding="utf-8-sig").strip()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context: BrowserContext = await browser.new_context(accept_downloads=False)
        page = await context.new_page()
        page.set_default_timeout(2500)

        print(f"[OPEN] {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass

        print(f"[PAGE] {await page.title()}")
        print(f"[URL]  {page.url}")

        # The user-selected job page may have an Apply button that opens the form.
        if args.open_apply:
            await maybe_open_application_form(page)

        # If a new tab was opened, this script does not guess which tab to use.
        filled: list[str] = []
        await safe_fill(page, "name", FIELD_PATTERNS["name"], args.name, filled)
        await safe_fill(page, "email", FIELD_PATTERNS["email"], args.email, filled)
        await safe_fill(page, "cover letter", FIELD_PATTERNS["cover_letter"], letter, filled)
        await upload_cv(page, cv_path)
        await describe_form(page)

        print("REVIEW REQUIRED")
        print(f"Fields filled: {', '.join(filled) if filled else '(none)'}")
        print("Check every field and the attached CV in the browser.")
        print("This script will NOT submit the application.")
        print("Close the browser window when you are finished reviewing.")

        # Keep browser open until the user closes it.
        try:
            while not page.is_closed():
                await page.wait_for_timeout(1000)
        except (KeyboardInterrupt, Exception):
            pass
        finally:
            await context.close()
            await browser.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open and prefill a job application for human review.")
    parser.add_argument("--url", required=True, help="Job page or direct application-form URL")
    parser.add_argument("--name", required=True, help="Your full name")
    parser.add_argument("--email", required=True, help="Your email address")
    parser.add_argument("--phone", default=None, help="Phone number (optional)")
    parser.add_argument("--cv", default=None, help="Path to CV PDF/DOCX (optional)")
    parser.add_argument("--cover-letter-file", default=None, help="Path to a plain-text cover letter")
    parser.add_argument("--open-apply", action="store_true",
                        help="Click a clearly labelled Apply link/button if found")
    parser.add_argument("--headed", action="store_true", default=True,
                        help="Open a visible browser (default)")
    return parser


if __name__ == "__main__":
    asyncio.run(run(build_parser().parse_args()))
