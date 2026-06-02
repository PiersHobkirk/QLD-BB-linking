"""
Fast PDF hyperlink extractor for large PDFs.

Outputs:
    1) main CSV:
        link_id,
        page_no,
        link_text,
        surrounding_text,
        link_destination,
        link_domain

    2) domains.csv:
        domain, link_count (sorted desc)

Approach:
    - Iterate through every page in the PDF.
    - Find every hyperlink annotation on the page.
    - Determine which words visually overlap each hyperlink.
    - Treat those overlapping words as the visible link text.
    - Capture 10 words before and 10 words after.
    - Stream results directly to CSV.
    - Keep a running count of domains.

Requirements:
    pip install pymupdf

Usage:
    python extract_pdf_links.py draft-204.pdf 204-links.csv
"""

import csv
import sys
from urllib.parse import urlparse
from collections import Counter

import fitz  # PyMuPDF


# Number of words before and after the link to capture.
SURROUNDING_WORD_COUNT = 10


def rects_overlap(a, b):
    """
    Return True if two rectangles overlap.

    Rectangles are:
        (x0, y0, x1, y1)
    """
    return not (
        a[2] < b[0] or
        a[0] > b[2] or
        a[3] < b[1] or
        a[1] > b[3]
    )


def extract_domain(uri: str) -> str:
    """
    Convert a URL into a simplified domain label.
    """
    try:
        netloc = urlparse(uri).netloc.lower()

        netloc = netloc.split(":")[0]

        if netloc.startswith("www."):
            netloc = netloc[4:]

        parts = netloc.split(".")

        tlds = {
            "com", "org", "net", "gov", "edu",
            "io", "au", "uk", "nz", "us", "co"
        }

        filtered = [p for p in parts if p not in tlds]

        if not filtered:
            return ""

        return filtered[-1]

    except Exception:
        return ""


def extract_links(pdf_path, output_csv):
    """
    Extract hyperlinks and surrounding context.
    """
    doc = fitz.open(pdf_path)

    total_links = 0
    domain_counts = Counter()
    link_id = 1

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow([
            "link_id",
            "page_no",
            "link_text",
            "surrounding_text",
            "link_destination",
            "link_domain",
        ])

        for page_number, page in enumerate(doc, start=1):

            links = page.get_links()

            if not links:
                continue

            # Extract all words once.
            words = page.get_text("words")

            for link in links:

                uri = link.get("uri")

                if not uri:
                    continue

                link_rect = tuple(link["from"])

                matched_words = []

                for word in words:
                    if rects_overlap(link_rect, word[:4]):
                        matched_words.append(word)

                if matched_words:
                    matched_words.sort(
                        key=lambda w: (w[1], w[0])
                    )

                    link_text = " ".join(
                        w[4] for w in matched_words
                    ).strip()

                    try:
                        first_index = words.index(
                            matched_words[0]
                        )
                    except ValueError:
                        first_index = 0

                    last_index = first_index + len(matched_words) - 1

                    context_start = max(
                        0,
                        first_index - SURROUNDING_WORD_COUNT
                    )

                    context_end = min(
                        len(words),
                        last_index + SURROUNDING_WORD_COUNT + 1
                    )

                    surrounding_text = " ".join(
                        w[4]
                        for w in words[context_start:context_end]
                    ).strip()

                else:
                    link_text = ""
                    surrounding_text = ""

                link_domain = extract_domain(uri)

                writer.writerow([
                    link_id,
                    page_number,
                    link_text,
                    surrounding_text,
                    uri,
                    link_domain,
                ])

                domain_counts[link_domain] += 1
                total_links += 1
                link_id += 1

            if page_number % 50 == 0:
                print(
                    f"Processed {page_number}/{len(doc)} pages..."
                )

    doc.close()

    with open(
        "domains.csv",
        "w",
        newline="",
        encoding="utf-8"
    ) as df:

        domain_writer = csv.writer(df)

        domain_writer.writerow([
            "domain",
            "link_count"
        ])

        for domain, count in domain_counts.most_common():
            domain_writer.writerow([
                domain,
                count
            ])

    print("\nDone.")
    print(f"Extracted {total_links} links.")
    print(f"Saved to: {output_csv}")
    print("Saved to: domains.csv")


def main():
    """
    Usage:
        python extract_pdf_links.py input.pdf output.csv
    """
    if len(sys.argv) != 3:
        print(
            "Usage: python extract_pdf_links.py "
            "input.pdf output.csv"
        )
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_csv = sys.argv[2]

    extract_links(pdf_path, output_csv)


if __name__ == "__main__":
    main()