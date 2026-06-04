import csv
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import re
from playwright.sync_api import Page

CSV_FILE = Path("legislation_links_v2.csv")

STORAGE_STATE_FILE = Path("jade_storage_state.json")
COOKIE_FILE = Path("jade_cookies.json")

ADVANCED_SEARCH_URL = "https://jade.io/t/browse/byCustom"

SELECTORS = {
    "text_field": 'input.gwt-TextBox.textSearch',
    "list_box": 'input.gwt-TextBox.textSearch ~ select.gwt-ListBox',
    "search_button": 'input.button-submit.custom-search-button',
    "result_links": 'a.gwt-Hyperlink.alcina-NoHistory',
}

SEARCH_CACHE = {}


def load_cookies_into_context(context):
    if COOKIE_FILE.exists():
        with open(COOKIE_FILE, "r") as f:
            context.add_cookies(json.load(f))


def create_authenticated_context(playwright):
    browser = playwright.chromium.launch(headless=True)

    if STORAGE_STATE_FILE.exists():
        context = browser.new_context(
            storage_state=str(STORAGE_STATE_FILE)
        )
    else:
        context = browser.new_context()
        load_cookies_into_context(context)

    return browser, context



def clean_title(title: str, jurisdiction: str = ""):
    """
    Minimal version of clean_title logic from your reference.
    Keeps dash-normalisation behaviour.
    """
    base = title.strip()

    with_dashes = base
    without_dashes = re.sub(r"[-–—]", " ", base)

    return with_dashes, without_dashes

def search_jade(page: Page, search_query: str, expected_match: str, jurisdiction: str = "") -> str | None:
    # ---- in-run cache check ----
    cache_key = search_query.strip().lower()

    if cache_key in SEARCH_CACHE:
        return SEARCH_CACHE[cache_key]

    expected_match_no_dashes = expected_match.replace("-", " ")

    page.goto(ADVANCED_SEARCH_URL)
    page.wait_for_load_state("networkidle")

    page.wait_for_selector(SELECTORS["text_field"], timeout=15000)

    text_field = page.locator(SELECTORS["text_field"])
    text_field.fill(f'"{search_query}"')

    list_box = page.locator(SELECTORS["list_box"])
    list_box.select_option(label="Document Title")

    page.locator(SELECTORS["search_button"]).click()

    page.wait_for_timeout(5000)
    page.wait_for_selector(SELECTORS["result_links"], timeout=15000)

    results = page.query_selector_all(SELECTORS["result_links"])

    found_url = None

    for result in results:
        result_text = (result.inner_text() or "").strip()
        if not result_text:
            continue

        result_with_dashes, result_without_dashes = clean_title(result_text, jurisdiction)

        if (
            result_with_dashes.lower() == expected_match.lower()
            or result_without_dashes.lower() == expected_match_no_dashes.lower()
            or result_with_dashes.lower().startswith(expected_match.lower())
            or result_without_dashes.lower().startswith(expected_match_no_dashes.lower())
        ):
            href = result.get_attribute("href")
            if not href or href == "#":
                continue

            found_url = f"https://jade.io{href}".split("?")[0]
            break

    # ---- store in-run cache (even if None) ----
    SEARCH_CACHE[cache_key] = found_url

    return found_url

def main():
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    with sync_playwright() as p:
        browser, context = create_authenticated_context(p)
        page = context.new_page()

        for row in rows:
            title = row.get("instrument_title", "").strip()

            if not title:
                continue

            print(f"Searching: {title}")

            try:
                url = search_jade(page, title, title, "")
            except Exception as e:
                print(f"ERROR: {title}: {e}")
                url = None

            row["legislation_top_link"] = url or ""

            print(f" -> {url}")

        browser.close()

    fieldnames = list(rows[0].keys())

    if "legislation_top_link" not in fieldnames:
        fieldnames.append("legislation_top_link")

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()