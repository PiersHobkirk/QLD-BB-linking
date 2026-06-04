"""
jade_matcher.py - Search JADE for legislation and compare currency dates.

This module provides the JadeMatcher class which:
  1. Searches JADE's advanced search by document title
  2. Matches results against cleaned/normalised legislation titles
  3. Extracts currency dates and repealed status from JADE pages
  4. Caches results to avoid redundant searches

Authentication is handled via saved cookies/storage state from jade_auth.py.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page

from utils import parse_date

# Authentication file paths
STORAGE_STATE_FILE = Path('jade_storage_state.json')
COOKIE_FILE = Path('jade_cookies.json')

# JADE URLs and selectors
ADVANCED_SEARCH_URL = "https://jade.io/t/browse/byCustom"
SELECTORS = {
    'text_field': 'input.gwt-TextBox.textSearch',
    'list_box': 'input.gwt-TextBox.textSearch ~ select.gwt-ListBox',
    'search_button': 'input.button-submit.custom-search-button',
    'result_links': 'a.gwt-Hyperlink.alcina-NoHistory',
}

# Jurisdiction code mapping for JADE title formatting
JURISDICTION_MAP = {
    'nsw': 'NSW',
    'vic': 'Vic',
    'qld': 'Qld',
    'wa': 'WA',
    'sa': 'SA',
    'tas': 'Tas',
    'act': 'ACT',
    'nt': 'NT',
    'cth': 'Cth',
}

# Month abbreviation lookup for date parsing on JADE pages
_MONTH_ABBREV_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}

# Regex patterns for extracting dates from JADE legislation pages
_DATE_PATTERNS = [
    r'(?:Start date:|Date made:|Compilation date:|Date of assent:|Date published:)'
    r'[^<]*</td>[^<]*<td[^>]*>'
    r'(\d{1,2}/(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/\d{4})',

    r'(?:Start date:|Date made:|Compilation date:|Date of assent:|Date published:)'
    r'\s*(\d{1,2}/\d{1,2}/\d{4})',

    r'(?:Start date:|Date made:|Compilation date:|Date of assent:|Date published:)'
    r'[^>]*?(?:</b>|</strong>)?\s*'
    r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December)\s+\d{4})',

    r'(?:Start date:|Date made:|Compilation date:|Date of assent:|Date published:)'
    r'.*?(\d{1,2}(?:\s+(?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December)|/\d{1,2})/?\s*\d{4})',
]


class JadeMatcher:
    """
    Searches JADE for legislation titles and extracts currency dates.

    The cache is written fresh each run (not used to skip searches).
    It exists purely as a reference file so you can quickly inspect
    which URLs were found and which were not.
    """

    def __init__(self, jurisdiction: str | None = None):
        self.jurisdiction = jurisdiction.lower() if jurisdiction else None

        # Cache setup - single combined cache for all jurisdictions
        # Start fresh each run; cache is for reference only, not lookup
        self.cache_dir = Path('cache')
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_file = self.cache_dir / 'jade_matches_cache.json'
        self.cached_urls: dict[str, str | None] = {}
        self._save_cache()  # write empty cache to start fresh

        self.verbose = False  # Enable with --debug for detailed match logging
        self.search_count = 0
        self.max_searches_before_refresh = 10

        self._check_auth_files()

    # ── Authentication ──────────────────────────────────────────────

    def _check_auth_files(self) -> None:
        """Check which authentication method is available."""
        if STORAGE_STATE_FILE.exists():
            logging.info(f"Found storage state file: {STORAGE_STATE_FILE}")
            self.auth_method = 'storage_state'
        elif COOKIE_FILE.exists():
            logging.info(f"Found cookie file: {COOKIE_FILE}")
            self.auth_method = 'cookies'
        else:
            logging.warning(
                "No authentication files found! "
                "Run jade_auth.py first to save your login cookies."
            )
            self.auth_method = None

    @staticmethod
    def get_storage_state_path() -> str | None:
        """Return the path to storage state file if it exists."""
        if STORAGE_STATE_FILE.exists():
            return str(STORAGE_STATE_FILE)
        return None

    @staticmethod
    def load_cookies_into_context(context: BrowserContext) -> bool:
        """Load saved cookies into a browser context."""
        if COOKIE_FILE.exists():
            try:
                with open(COOKIE_FILE, 'r') as f:
                    cookies = json.load(f)
                context.add_cookies(cookies)
                logging.info(f"Loaded {len(cookies)} cookies from {COOKIE_FILE}")
                return True
            except Exception as e:
                logging.error(f"Failed to load cookies: {e}")
                return False
        logging.warning(f"Cookie file not found: {COOKIE_FILE}")
        return False

    # ── Cache ───────────────────────────────────────────────────────

    def _load_cache(self) -> None:
        """Load previously matched Jade URLs from cache."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    self.cached_urls = json.load(f)
            except json.JSONDecodeError as e:
                logging.error(f"Error loading cache file: {e}")
                self.cached_urls = {}
                backup = self.cache_file.with_suffix('.json.bak')
                self.cache_file.rename(backup)
        else:
            self.cached_urls = {}

    def _save_cache(self) -> None:
        """Persist the match cache to disk."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cached_urls, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving cache: {e}")

    def clear_cache_entry(self, title: str) -> None:
        """Remove a single entry from the cache (useful for retries)."""
        cache_key = f"{self.jurisdiction}:{title}"
        if cache_key in self.cached_urls:
            del self.cached_urls[cache_key]
            self._save_cache()
            logging.info(f"Cleared cache for: {cache_key}")

    # ── Title normalisation ─────────────────────────────────────────

    def clean_title(self, title: str, jurisdiction: str) -> tuple[str, str]:
        """
        Clean legislation title for searching and append jurisdiction.

        Returns:
            Tuple of (title_with_dashes, title_without_dashes), both with
            jurisdiction suffix appended.
        """
        # Normalise dashes
        title = title.replace('\u2014', '-').replace('\u2013', '-')
        # Mojibake fixes
        title = (title
                 .replace("\u00e2\u0080\u0099", "'")
                 .replace("\u00e2\u0080\u0098", "'")
                 .replace("\u00e2\u0080\u0094", "-")
                 .replace("\u00e2\u0080\u0093", "-"))
        # Normalise apostrophes
        title = re.sub(
            r"[\u0027\u2019\u2018\u02BC\u02BB\u0060\u00B4\u2032\u201B]",
            "'", title
        )

        # Fully spaced hyphens don't appear in JADE
        title = title.replace(' - ', ' ')

        # Two versions: with and without dashes
        title_with_dashes = title
        title_without_dashes = title.replace('-', ' ')

        # Patterns to strip from titles
        jur_pattern = rf"\s*\({re.escape(jurisdiction)}\)\s*$"
        private_act_pattern = r"\s*\(Private Act\)"
        no_number_pattern = r"\s*\bNo\s+\d+[a-e]?\b(?=\s|$)"

        suffix_patterns = [jur_pattern, private_act_pattern, no_number_pattern]

        def remove_last_occurrence(text: str, pattern: str) -> str:
            matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
            if matches:
                last = matches[-1]
                text = text[:last.start()] + text[last.end():]
            return text

        for pattern in suffix_patterns:
            title_with_dashes = remove_last_occurrence(title_with_dashes, pattern)
            title_without_dashes = remove_last_occurrence(title_without_dashes, pattern)

        # Normalise whitespace
        title_with_dashes = ' '.join(title_with_dashes.split())
        title_without_dashes = ' '.join(title_without_dashes.split())

        # Append jurisdiction suffix
        jur_suffix = f" ({JURISDICTION_MAP.get(jurisdiction.lower(), jurisdiction.upper())})"
        title_with_dashes = title_with_dashes.strip() + jur_suffix
        title_without_dashes = title_without_dashes.strip() + jur_suffix

        return title_with_dashes, title_without_dashes

    def _strip_jurisdiction(self, title: str) -> str:
        return re.sub(
            r'\s*\((?:NSW|Vic|Qld|WA|SA|Tas|ACT|NT|Cth|Cwlth)\)\s*$',
            '', title, flags=re.IGNORECASE
        )

    def _strip_apostrophes(self, title: str, greedy: bool) -> str:
        """
        Remove apostrophes from a title for JADE search queries.

        Args:
            title: Title that may contain apostrophes
            greedy: If True, remove everything up to and including the
                    word containing the apostrophe (more aggressive).
        """
        if greedy:
            title = re.sub(r"^.*['\u2018\u2019]\w*\s*", "", title, flags=re.UNICODE)
            title = re.sub(r'["\u201c\u201d]', '', title)
            return ' '.join(title.split())

        # Internal apostrophes: remove the whole word
        title = re.sub(
            r"^.*\b[^\W\d_]+['\u2018\u2019][^\W\d_]+\b\s*",
            '', title, flags=re.UNICODE
        )
        # External apostrophes: strip trailing apostrophe
        title = re.sub(
            r"(\b[^\W\d_]+)['\u2018\u2019](?=\s|$)",
            r'\1', title, flags=re.UNICODE
        )
        # Remove quotation marks
        title = re.sub(r'["\u201c\u201d]', '', title)
        return ' '.join(title.split())

    # ── Login check ─────────────────────────────────────────────────

    def _check_login_required(self, page: Page) -> bool:
        """Return True if JADE is showing the login page."""
        login_indicators = [
            "text=Sign in to JADE",
            "input[placeholder='your@email.com']",
        ]
        for indicator in login_indicators:
            if page.query_selector(indicator):
                return True
        return False

    # ── Search ──────────────────────────────────────────────────────

    def _perform_single_search(
        self,
        page: Page,
        search_query: str,
        expected_match: str,
        jurisdiction: str,
    ) -> str | None:
        """
        Perform a single advanced search on JADE and return the URL if a
        matching result is found.
        """
        expected_match_no_dashes = expected_match.replace('-', ' ')

        page.goto(ADVANCED_SEARCH_URL)
        time.sleep(3)

        if self._check_login_required(page):
            logging.error("SESSION EXPIRED: Login required. Run jade_auth.py.")
            return None

        page.wait_for_selector(SELECTORS['text_field'], timeout=15000)

        text_field = page.locator(SELECTORS['text_field'])
        text_field.fill('"' + search_query + '"')
        time.sleep(1)

        list_box = page.locator(SELECTORS['list_box'])
        list_box.select_option("Document Title")
        time.sleep(1)

        search_button = page.locator(SELECTORS['search_button'])
        search_button.click()
        time.sleep(5)

        results = page.query_selector_all(SELECTORS['result_links'])
        logging.info(f"Found {len(results)} result links")

        for result in results:
            result_text = result.inner_text()
            if not result_text.strip():
                continue

            result_with_dashes, result_without_dashes = self.clean_title(
                result_text, jurisdiction
            )

            if self.verbose:
                logging.info(f"[MATCH-DEBUG] Raw: '{result_text}'")
                logging.info(f"[MATCH-DEBUG]   Cleaned:  '{result_with_dashes}'")
                logging.info(f"[MATCH-DEBUG]   Expected: '{expected_match}'")

            # Flexible matching: exact or startswith, with or without dashes
            if (result_with_dashes.lower() == expected_match.lower()
                    or result_without_dashes.lower() == expected_match_no_dashes.lower()
                    or result_with_dashes.lower().startswith(expected_match.lower())
                    or result_without_dashes.lower().startswith(expected_match_no_dashes.lower())):

                logging.info(f"Matched: {result_text}")
                href = result.get_attribute('href')
                if not href or href == '#':
                    continue

                actual_url = f"https://jade.io{href}"
                if '?' in actual_url:
                    actual_url = actual_url.split('?')[0]

                if actual_url and actual_url != "https://jade.io#":
                    return actual_url

            elif self.verbose:
                logging.info("[MATCH-DEBUG]   => NO MATCH")

        return None

    def search_jade(self, page: Page, title: str, jurisdiction: str) -> str | None:
        """
        Search JADE for a legislation title. Uses a two-attempt strategy:
          1. Search with jurisdiction suffix, apostrophes stripped.
          2. Search without jurisdiction suffix, greedy apostrophe strip.

        Always performs a fresh search (cache is written for reference only,
        not used to skip searches).
        """
        cache_key = f"{jurisdiction.lower()}:{title}"

        logging.info(f"Searching JADE for: {title}")

        expected_match, _ = self.clean_title(title, jurisdiction)

        # Attempt 1: with jurisdiction
        search_query = self._strip_apostrophes(expected_match, greedy=False)
        logging.info(f'Attempt 1 - Search: "{search_query}"')

        try:
            result = self._perform_single_search(page, search_query, expected_match, jurisdiction)
            if result:
                self.cached_urls[cache_key] = result
                self._save_cache()
                return result
        except Exception as e:
            logging.error(f"Attempt 1 error: {e}")

        # Attempt 2: without jurisdiction, greedy apostrophe strip
        search_query = self._strip_jurisdiction(
            self._strip_apostrophes(expected_match, greedy=True)
        )
        logging.info(f'Attempt 2 - Search: "{search_query}"')

        try:
            result = self._perform_single_search(page, search_query, expected_match, jurisdiction)
            if result:
                self.cached_urls[cache_key] = result
                self._save_cache()
                return result
        except Exception as e:
            logging.error(f"Attempt 2 error: {e}")

        logging.warning(f"No match found for: {cache_key}")
        self.cached_urls[cache_key] = None
        self._save_cache()
        return None

    # ── Date extraction ─────────────────────────────────────────────

    def get_jade_status_and_date(
        self, page: Page, jade_url: str
    ) -> tuple[datetime | None, bool | None]:
        """
        Extract the currency date and repealed status from a JADE legislation page.

        Returns:
            (date, is_repealed) or (None, None) on failure.
        """
        max_retries = 3
        base_timeout = 45000

        for attempt in range(max_retries):
            try:
                backoff_time = 5 * (2 ** attempt)
                timeout = base_timeout + (attempt * 15000)

                logging.info(
                    f"Attempt {attempt + 1}/{max_retries} to get date from {jade_url} "
                    f"(timeout: {timeout}ms)"
                )

                try:
                    page.goto(jade_url, wait_until='domcontentloaded', timeout=timeout)
                except Exception as e:
                    logging.warning(f"Navigation failed on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(backoff_time)
                        continue
                    return None, None

                time.sleep(3)

                if self._check_login_required(page):
                    logging.error("SESSION EXPIRED during date retrieval")
                    return None, None

                if not page.url.startswith(jade_url):
                    logging.warning(f"Wrong page loaded: {page.url}")
                    if attempt < max_retries - 1:
                        time.sleep(backoff_time)
                        continue
                    return None, None

                is_repealed = bool(page.query_selector("text=Statute repealed"))

                try:
                    page_html = page.content()
                except Exception as e:
                    logging.warning(f"Failed to get page content: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(backoff_time)
                        continue
                    return None, None

                # Check if article doesn't exist
                if re.search(
                    r'Article does not exist.*is inaccessible.*or you have entered an incorrect URL',
                    page_html, re.IGNORECASE | re.DOTALL
                ):
                    logging.error(f"ARTICLE DOES NOT EXIST: {jade_url}")
                    return None, None

                # Try each date pattern
                date = None
                for pattern in _DATE_PATTERNS:
                    matches = re.findall(pattern, page_html, re.IGNORECASE)
                    if matches:
                        date_str = matches[0]
                        try:
                            mon_match = re.match(r'(\d{1,2})/([A-Za-z]{3})/(\d{4})', date_str)
                            if mon_match:
                                day, mon_abbrev, year = mon_match.groups()
                                month_num = _MONTH_ABBREV_MAP.get(mon_abbrev.lower())
                                if month_num:
                                    date = datetime(int(year), month_num, int(day))
                                    break
                            else:
                                date = parse_date(date_str)
                                break
                        except ValueError:
                            continue

                if date:
                    logging.info(f"Found date: {date}, repealed: {is_repealed}")
                    return date, is_repealed

                logging.warning(f"No date found on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(backoff_time)
                    try:
                        page.reload()
                    except Exception as e:
                        logging.debug("Page reload failed during backoff: %s", e)

            except Exception as e:
                logging.error(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5 * (2 ** attempt))
                else:
                    return None, None

        logging.error(f"All {max_retries} attempts failed for {jade_url}")
        return None, None


# ── Helper: create authenticated browser context ────────────────────


def create_authenticated_context(playwright: Any, headless: bool = True) -> tuple:
    """
    Create a Playwright browser + context with JADE authentication loaded.

    Args:
        playwright: Playwright instance
        headless: Whether to run headless (default True)

    Returns:
        (browser, context) tuple
    """
    browser = playwright.chromium.launch(headless=headless)

    storage_path = JadeMatcher.get_storage_state_path()
    if storage_path:
        logging.info(f"Creating context with storage state: {storage_path}")
        context = browser.new_context(storage_state=storage_path)
    else:
        logging.info("Creating context and loading cookies manually")
        context = browser.new_context()
        JadeMatcher.load_cookies_into_context(context)

    return browser, context
