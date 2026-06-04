import csv
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CSV_PATH = Path("legislation_links_v2.csv")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

# Hyphen-like characters to split on
HYPHEN_RE = re.compile(r"\s*[-–—]\s*")


def get_instrument_title(url: str) -> str:
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"ERROR fetching {url}: {e}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    # Case 1: Queensland legislation
    h1 = soup.find("h1", class_="title")
    if h1:
        title = h1.get_text(" ", strip=True)
        return f"{title} (QLD)"

    # Case 2: Commonwealth legislation
    span = soup.find("span", class_="version-name")
    if span:
        title = span.get_text(" ", strip=True)
        return f"{title} (Cth)"

    print(f"ERROR: Could not find instrument title for {url}")
    return ""


def get_section_name(link_text: str) -> str:
    if not link_text:
        return ""

    # Remove everything from the first hyphen/dash onwards
    section = HYPHEN_RE.split(link_text, maxsplit=1)[0]

    # Normalise whitespace
    section = re.sub(r"\s+", " ", section).strip()

    return section


with CSV_PATH.open(newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)

    fieldnames = list(reader.fieldnames or [])

    if "instrument_title" not in fieldnames:
        fieldnames.append("instrument_title")

    if "section_name" not in fieldnames:
        fieldnames.append("section_name")

    rows = []

    for i, row in enumerate(reader, start=1):
        # Always regenerate section_name
        row["section_name"] = get_section_name(row.get("link_text", ""))

        # Only fetch instrument_title if blank
        existing_title = row.get("instrument_title", "").strip()

        if existing_title:
            print(f"[{i}] Skipping title lookup (already populated)")
        else:
            url = row.get("link_destination", "").strip()

            if not url:
                print(f"[{i}] ERROR: No link_destination")
            else:
                print(f"[{i}] Looking up title: {url}")
                row["instrument_title"] = get_instrument_title(url)

                # Be polite to the server only when making requests
                time.sleep(0.2)

        rows.append(row)

with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"\nSaved {len(rows)} rows to {CSV_PATH}")