import csv
import json
import re
from pathlib import Path

from rapidfuzz import fuzz
from playwright.sync_api import sync_playwright

CSV_FILE = Path("legislation_links.csv")

STORAGE_STATE_FILE = Path("jade_storage_state.json")
COOKIE_FILE = Path("jade_cookies.json")


def load_cookies_into_context(context):
    if COOKIE_FILE.exists():
        with open(COOKIE_FILE, "r") as f:
            context.add_cookies(json.load(f))


def create_authenticated_context(playwright):
    browser = playwright.chromium.launch(headless=True)

    if STORAGE_STATE_FILE.exists():
        context = browser.new_context(storage_state=str(STORAGE_STATE_FILE))
    else:
        context = browser.new_context()
        load_cookies_into_context(context)

    return browser, context


def _tokenise(s: str):
    return re.findall(r"\d+|[a-zA-Z]+", (s or "").lower())

def _word_count(s: str) -> int:
    return len(re.findall(r"\S+", s or ""))

def best_match(section_name, candidates, max_words=50):
    section_norm = (section_name or "").strip().lower()
    if not section_norm:
        return None, 0.0

    section_tokens = _tokenise(section_norm)

    best_score = 0.0
    best_text = None

    for text in candidates:
        if not text:
            continue

        t_norm = text.strip().lower()
        word_count = _word_count(t_norm)

        # HARD length penalty: long strings are harder to win
        # After 50 words, progressively down-weight score
        if word_count > max_words:
            length_penalty = max(0.5, max_words / word_count)
        else:
            length_penalty = 1.0

        if t_norm == section_norm:
            return text, 1.0

        t_tokens = _tokenise(t_norm)

        def is_token_subsequence(a, b):
            if not a:
                return False
            for i in range(len(b) - len(a) + 1):
                if b[i:i + len(a)] == a:
                    return True
            return False

        # strict containment (safe numeric + word boundary aware)
        if is_token_subsequence(section_tokens, t_tokens):
            coverage = len(section_tokens) / max(len(t_tokens), 1)
            start_bonus = 1.0 if t_tokens[:len(section_tokens)] == section_tokens else 0.95

            score = (0.88 + 0.10 * coverage + 0.02 * start_bonus) * length_penalty
            score = min(score, 0.99)

        elif is_token_subsequence(t_tokens, section_tokens):
            coverage = len(t_tokens) / max(len(section_tokens), 1)
            score = (0.75 + 0.10 * coverage) * length_penalty
            score = min(score, 0.90)

        else:
            score = fuzz.token_set_ratio(section_norm, t_norm) / 100.0
            score *= length_penalty

        if score > best_score:
            best_score = score
            best_text = text

    return best_text, best_score




def process_row(page, row):
    url = row["legislation_top_link"]
    section_name = row.get("section_name", "")

    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)

    elements = page.query_selector_all("div[class^='GPEXH4Q']")

    candidates = []
    element_map = {}

    for el in elements:
        txt = (el.inner_text() or "").strip()
        if txt:
            candidates.append(txt)
            element_map[txt] = el

    print("FOUND CANDIDATES:", len(candidates))
    # print(candidates[:10])

    if not candidates:
        return None, 0.0, ""

    best_text, confidence = best_match(section_name, candidates)

    if not best_text:
        return None, 0.0, ""

    best_el = element_map.get(best_text)
    if not best_el:
        return None, confidence, best_text

    # click and capture navigation
    with page.expect_navigation(wait_until="domcontentloaded"):
        best_el.click()

    return page.url, confidence, best_text


def main():
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    # ensure output columns exist
    for col in ["jade_pinpoint_link", "match_confidence", "best_jade_section"]:
        if col not in fieldnames:
            fieldnames.append(col)

    with sync_playwright() as p:
        browser, context = create_authenticated_context(p)
        page = context.new_page()

        for i, row in enumerate(rows):
            try:
                link, conf, best_text = process_row(page, row)

                row["jade_pinpoint_link"] = link or ""
                row["match_confidence"] = conf
                row["best_jade_section"] = best_text or ""

                print(
                    f'[{i}] confidence={conf:.3f} url={link}\n'
                    f'Searched vs Found: "{row.get("section_name","")}" vs "{best_text}"'
                )

            except Exception as e:
                row["jade_pinpoint_link"] = ""
                row["match_confidence"] = 0.0
                row["best_jade_section"] = ""

                print(f"[{i}] ERROR: {e}")

        browser.close()

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()