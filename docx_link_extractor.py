#!/usr/bin/env python3
"""
Extract hyperlinks from a folder of .docx files and write a CSV.

Usage:
    python extract_hyperlinks.py [INPUT_DIR] [OUTPUT_CSV]

Defaults:
    INPUT_DIR  = ./raws
    OUTPUT_CSV = hyperlinks.csv
"""

import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from docx import Document

# XML namespaces used in .docx
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

W_P = f"{{{W_NS}}}p"
W_R = f"{{{W_NS}}}r"
W_T = f"{{{W_NS}}}t"
W_TBL = f"{{{W_NS}}}tbl"
W_TR = f"{{{W_NS}}}tr"
W_TC = f"{{{W_NS}}}tc"
W_HYPERLINK = f"{{{W_NS}}}hyperlink"
W_SDT = f"{{{W_NS}}}sdt"
W_SDTCONTENT = f"{{{W_NS}}}sdtContent"
R_ID = f"{{{R_NS}}}id"


def iter_paragraphs(element):
    """Yield all <w:p> elements in document reading order, recursing into
    tables, structured-document-tags, and table cells."""
    for child in element:
        tag = child.tag
        if tag == W_P:
            yield child
        elif tag == W_TBL:
            for row in child.iterfind(W_TR):
                for cell in row.iterfind(W_TC):
                    yield from iter_paragraphs(cell)
        elif tag == W_SDT:
            sdt_content = child.find(W_SDTCONTENT)
            if sdt_content is not None:
                yield from iter_paragraphs(sdt_content)
        elif tag == W_TC:
            yield from iter_paragraphs(child)


def text_of(element):
    """Return concatenated text from all <w:t> descendants."""
    parts = []
    for t in element.iter(W_T):
        if t.text:
            parts.append(t.text)
    return "".join(parts)


def extract_hyperlinks(doc_path):
    """Return a list of hyperlink dicts from *doc_path* in reading order.

    Each dict has keys: link_text, url, preceding_text (last 20 chars of
    paragraph text before the hyperlink).
    """
    doc = Document(str(doc_path))
    rels = doc.part.rels
    body = doc.element.body

    results = []

    for para in iter_paragraphs(body):
        accumulated = ""  # plain-text accumulator for the paragraph

        for child in para:
            if child.tag == W_HYPERLINK:
                r_id = child.get(R_ID)
                link_text = text_of(child)

                if r_id and r_id in rels:
                    url = rels[r_id].target_ref
                    if url and (url.startswith("http://") or url.startswith("https://")):
                        preceding = accumulated[-20:] if len(accumulated) > 20 else accumulated
                        results.append(
                            {
                                "link_text": link_text,
                                "url": url,
                                "preceding_text": preceding,
                            }
                        )

                # Whether we kept the hyperlink or not, its text is part of the paragraph
                accumulated += link_text

            elif child.tag == W_R:
                accumulated += text_of(child)
            # Ignore bookmarkStart/End, proofErr, etc.

    return results


def extract_domain(url):
    """Return the domain (netloc) of *url*, lowercased, ``www.`` stripped."""
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def extract_ch(filename):
    """Return text between the first and second space in *filename* (stem)."""
    stem = Path(filename).stem
    parts = stem.split(" ")
    if len(parts) >= 3:
        return parts[1]
    # Fewer than two spaces — fall back to second token if available
    if len(parts) == 2:
        return parts[1]
    return stem  # single-word filename, return entire stem


def normalize(text):
    """Lowercase and collapse whitespace for substring matching."""
    return re.sub(r"\s+", " ", text).strip().lower()


def process_documents(input_dir, output_csv):
    input_path = Path(input_dir)
    if not input_path.is_dir():
        sys.exit(f"Error: directory '{input_dir}' does not exist.")

    docx_files = sorted(input_path.glob("*.docx"))
    if not docx_files:
        sys.exit(f"No .docx files found in {input_path}")

    rows = []

    for doc_path in docx_files:
        ch = extract_ch(doc_path.name)

        print("Processing " + ch)

        hyperlinks = extract_hyperlinks(doc_path)

        last_non_jade_text = None  # reset per document

        for hl in hyperlinks:
            url = hl["url"]
            domain = extract_domain(url)
            is_jade = "jade" in url.lower()

            if is_jade:
                link_text = hl["preceding_text"] + hl["link_text"]
                if last_non_jade_text:
                    is_sublink = normalize(last_non_jade_text) in normalize(link_text)
                else:
                    is_sublink = False
            else:
                link_text = hl["link_text"]
                is_sublink = False
                last_non_jade_text = hl["link_text"]

            rows.append(
                {
                    "ch": ch,
                    "link_text": link_text,
                    "link_destination": url,
                    "domain": domain,
                    "is_sublink": is_sublink,
                }
            )

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["ch", "link_text", "link_destination", "domain", "is_sublink"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done — {len(rows)} hyperlinks from {len(docx_files)} documents → {output_csv}")


if __name__ == "__main__":
    input_dir = sys.argv[1] if len(sys.argv) > 1 else "./raws"
    output_csv = sys.argv[2] if len(sys.argv) > 2 else "docx_hyperlinks.csv"
    process_documents(input_dir, output_csv)
