"""
jade_auth.py - Export and manage Jade.io session cookies for authenticated access.

Usage:
    python jade_auth.py

Opens a browser window for manual JADE login, then saves cookies/storage state
for use by the matcher.
"""

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

COOKIE_FILE = Path("jade_cookies.json")
STORAGE_STATE_FILE = Path("jade_storage_state.json")
JADE_URL = "https://jade.io/search/collection.journalGroupName=Legislation:corpus.country=au"


def export_cookies():
    """Interactive cookie export - opens headed browser for manual login."""
    print("=" * 60)
    print("JADE.IO COOKIE EXPORT")
    print("=" * 60)
    print()
    print("A browser window will open. Please:")
    print("1. Enter your email address")
    print("2. Click 'Continue'")
    print("3. Check your email for the login link")
    print("4. Click the link to complete login")
    print("5. Once you see the search page, come back here")
    print("6. Press ENTER in this terminal to save cookies")
    print()
    print("Opening browser...")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto(JADE_URL)

        input("\n>>> Press ENTER after you have logged in successfully... ")

        current_url = page.url
        print(f"\nCurrent URL: {current_url}")

        # Verify login
        search_input = page.query_selector('input.alcina-Filter.keywords')
        if search_input and search_input.is_visible():
            print("Login verified - search input is visible!")
        else:
            print("Warning: Search input not visible. Login may not have completed.")
            proceed = input("Save cookies anyway? (y/n): ").strip().lower()
            if proceed != 'y':
                print("Aborted.")
                browser.close()
                return False

        # Get jade.io cookies
        cookies = context.cookies()
        jade_cookies = [c for c in cookies if 'jade.io' in c.get('domain', '')]

        print(f"\nFound {len(jade_cookies)} Jade.io cookies")

        with open(COOKIE_FILE, 'w') as f:
            json.dump(jade_cookies, f, indent=2)
        print(f"Cookies saved to: {COOKIE_FILE}")

        # Save full storage state
        context.storage_state(path=str(STORAGE_STATE_FILE))
        print(f"Full storage state saved to: {STORAGE_STATE_FILE}")

        browser.close()

        print("\n" + "=" * 60)
        print("SUCCESS!")
        print("=" * 60)
        print(f"\nYou can now run the checker. Auth files:")
        print(f"  - {COOKIE_FILE}")
        print(f"  - {STORAGE_STATE_FILE} (recommended)")
        print()

        return True


if __name__ == "__main__":
    export_cookies()
