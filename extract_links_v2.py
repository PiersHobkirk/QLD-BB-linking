"""
Fast PDF hyperlink extractor for large PDFs.

Outputs:
    1) main CSV:
        page_no,
        link_text,
        preceding_text,
        link_destination,
        link_domain,
        is_jade_link,
        is_sublink

    2) domains.csv:
        domain, link_count (sorted desc)

Definitions:
    is_jade_link:
        True if link_destination contains "jade"

    is_sublink:
        For jade links only.

        True if the most recent NON-jade link_text
        appears within the jade link's preceding_text.

        Matching is fuzzy:
            - spaces are removed
            - comparison is case-insensitive

Approach:
    - Iterate through every page in the PDF.
    - Find every hyperlink annotation on the page.
    - Determine which words visually overlap each hyperlink.
    - Treat those overlapping words as the visible link text.
    - Capture a configurable number of preceding words.
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


# Number of preceding words to capture.
PRECEDING_WORD_COUNT = 10


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


def is_jade_link(uri: str) -> bool:
    """
    True if URL contains 'jade'.
    """
    return "jade" in (uri or "").lower()


def normalise_for_contains(text: str) -> str:
    """
    Fuzzy comparison helper.

    PDFs often contain unreliable spacing,
    so remove all whitespace and lowercase.
    """
    return "".join(text.lower().split())


def extract_links(pdf_path, output_csv):
    """
    Extract hyperlinks and surrounding context.
    """
    doc = fitz.open(pdf_path)

    total_links = 0
    domain_counts = Counter()

    # Most recent NON-jade link text.
    previous_non_jade_link_text = ""

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow([
            "page_no",
            "link_text",
            "preceding_text",
            "link_destination",
            "link_domain",
            "is_jade_link",
            "is_sublink",
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

                    # Find earliest matched word in original
                    # page word stream.
                    first_matched_word = matched_words[0]

                    try:
                        first_index = words.index(first_matched_word)
                    except ValueError:
                        first_index = 0

                    start_index = max(
                        0,
                        first_index - PRECEDING_WORD_COUNT
                    )

                    preceding_text = " ".join(
                        w[4]
                        for w in words[start_index:first_index]
                    ).strip()

                else:
                    link_text = ""
                    preceding_text = ""

                jade = is_jade_link(uri)

                if jade:
                    previous_norm = normalise_for_contains(
                        previous_non_jade_link_text
                    )

                    preceding_norm = normalise_for_contains(
                        preceding_text
                    )

                    is_sublink = (
                        bool(previous_norm)
                        and previous_norm in preceding_norm
                    )

                else:
                    is_sublink = False

                    if link_text:
                        previous_non_jade_link_text = link_text

                link_domain = extract_domain(uri)

                writer.writerow([
                    page_number,
                    link_text,
                    preceding_text,
                    uri,
                    link_domain,
                    jade,
                    is_sublink,
                ])

                domain_counts[link_domain] += 1
                total_links += 1

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