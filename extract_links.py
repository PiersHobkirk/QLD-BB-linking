"""
Fast PDF hyperlink extractor for large PDFs.

Outputs:
    1) main CSV:
        page_no, link_text, link_destination, link_domain

    2) domains.csv:
        domain, link_count (sorted desc)

Approach:
    - Iterate through every page in the PDF.
    - Find every hyperlink annotation on the page.
    - Determine which words visually overlap each hyperlink.
    - Treat those overlapping words as the visible link text.
    - Write results directly to CSV as they are found.
    - Keep a running count of domains for a summary report.

Optimisations:
    - Streams directly to CSV (does not keep all results in memory)
    - Only extracts words once per page
    - Uses cheap rectangle overlap checks
    - Avoids pandas overhead entirely
    - Skips pages with no links immediately

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


def rects_overlap(a, b):
    """
    Return True if two rectangles overlap.

    PyMuPDF represents both hyperlinks and words as rectangles:
        (x0, y0, x1, y1)

    If a word rectangle overlaps a hyperlink rectangle,
    we assume that word is part of the visible hyperlink text.
    """
    return not (
        a[2] < b[0] or
        a[0] > b[2] or
        a[3] < b[1] or
        a[1] > b[3]
    )


from urllib.parse import urlparse

def extract_domain(uri: str) -> str:
    """
    Extract the network location (domain) from a URL.

    Examples:
        https://www.austlii.edu.au/... -> www.austlii.edu.au
        https://austlii.edu.au/...     -> austlii.edu.au
        https://www.google.com/...     -> www.google.com

    This keeps the full host for grouping/counting without collapsing
    subdomains or attempting semantic reduction.
    """
    try:
        netloc = urlparse(uri).netloc.lower()

        # Remove port if present (e.g. example.com:8080)
        netloc = netloc.split(":")[0]

        return netloc

    except Exception:
        return ""

# OG extract_domain
# def extract_domain(uri: str) -> str:
#     """
#     Convert a URL into a simplified domain label.

#     Examples:
#         https://www.austlii.edu.au/... -> austlii
#         https://www.google.com/...     -> google

#     This is used purely for grouping/counting links by source.
#     """
#     try:
#         netloc = urlparse(uri).netloc.lower()

#         # Remove port numbers if present.
#         netloc = netloc.split(":")[0]

#         # Remove common www prefix.
#         if netloc.startswith("www."):
#             netloc = netloc[4:]

#         parts = netloc.split(".")

#         # Common TLDs to ignore.
#         tlds = {
#             "com", "org", "net", "gov", "edu",
#             "io", "au", "uk", "nz", "us", "co"
#         }

#         filtered = [p for p in parts if p not in tlds]

#         if not filtered:
#             return ""

#         # Use the final remaining component.
#         return filtered[-1]

#     except Exception:
#         return ""


def extract_links(pdf_path, output_csv):
    """
    Extract all hyperlinks from a PDF.

    For each hyperlink:
        - determine its destination URL
        - identify overlapping words on the page
        - reconstruct visible link text
        - write one CSV row

    Also builds a summary count of domains encountered.
    """
    doc = fitz.open(pdf_path)

    total_links = 0
    domain_counts = Counter()

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow([
            "page_no",
            "link_text",
            "link_destination",
            "link_domain",
        ])

        # Process pages one at a time to keep memory usage low.
        for page_number, page in enumerate(doc, start=1):

            # Retrieve all hyperlink annotations on the page.
            links = page.get_links()

            # Most pages usually contain no links.
            # Skip them immediately.
            if not links:
                continue

            # Extract all page words once.
            #
            # Each word record contains:
            #   x0, y0, x1, y1, text, ...
            #
            # Reusing this list is much cheaper than repeatedly
            # querying page text for every link.
            words = page.get_text("words")

            for link in links:

                # Ignore non-URI links such as internal page jumps.
                uri = link.get("uri")
                if not uri:
                    continue

                # Rectangle occupied by the hyperlink.
                link_rect = tuple(link["from"])

                matched_words = []

                # Find all words whose bounding boxes overlap
                # the hyperlink rectangle.
                for word in words:
                    if rects_overlap(link_rect, word[:4]):
                        matched_words.append(word)

                # Reconstruct visible hyperlink text from matched words.
                if matched_words:

                    # Sort into reading order:
                    #   top-to-bottom, then left-to-right.
                    matched_words.sort(
                        key=lambda w: (w[1], w[0])
                    )

                    link_text = " ".join(
                        w[4] for w in matched_words
                    )
                else:
                    link_text = ""

                link_domain = extract_domain(uri)

                # Stream result directly to disk.
                writer.writerow([
                    page_number,
                    link_text,
                    uri,
                    link_domain,
                ])

                # Update summary statistics.
                domain_counts[link_domain] += 1
                total_links += 1

            # Simple progress indicator for large PDFs.
            if page_number % 50 == 0:
                print(
                    f"Processed {page_number}/{len(doc)} pages..."
                )

    doc.close()

    # Write domain frequency summary.
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

        # Most frequent domains first.
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
    Command-line entry point.

    Expected usage:
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