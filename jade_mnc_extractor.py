import csv
import re
import requests

INPUT_CSV = "csvs/easy_mncs.csv"
OUTPUT_CSV = "jade_easy_mncs.csv"

# Matches [2002]HCA12
PATTERN = re.compile(r"\[(\d{4})\]([A-Za-z]+)(\d+)")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

def parse_link_text(text):
    match = PATTERN.search(text)
    if not match:
        return None, None, None
    year, court, number = match.groups()
    return year, court, number

def resolve_jade_url(year, court, number):
    # Assumption: jade uses lowercase court codes in URL
    url = f"https://jade.io/mnc/{year}/{court.lower()}/{number}"
    
    try:
        resp = session.get(url, allow_redirects=True, timeout=15)
        final_url = resp.url

        if "/article/" in final_url:
            return url, final_url
        else:
            return url, "ARTICLE_NOT_FOUND"

    except requests.RequestException:
        return url, "ARTICLE_NOT_FOUND"


def main():
    rows_out = []

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            page_no = row["page_no"]
            link_text = row["link_text"]
            link_destination = row["link_destination"]

            year, court, number = parse_link_text(link_text)

            if not year:
                continue

            jade_mnc_link, jade_article_link = resolve_jade_url(year, court, number)

            print("Processed:", link_text, "→", jade_mnc_link, "→", jade_article_link)

            rows_out.append({
                "page_no": page_no,
                "link_text": link_text,
                "link_destination": link_destination,
                "jade_mnc_link": jade_mnc_link,
                "jade_article_link": jade_article_link
            })

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["page_no", "link_text", "link_destination", "jade_mnc_link", "jade_article_link"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)


if __name__ == "__main__":
    main()