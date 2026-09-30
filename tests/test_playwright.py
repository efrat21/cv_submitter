
from playwright.sync_api import sync_playwright


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    page = browser.new_page()

    page.goto("https://dev.bg/", wait_until="domcontentloaded")

    print("Page title:", page.title())
    print("Current URL:", page.url)

    browser.close()
