#!/usr/bin/env python3
"""
Replace hyperlink destinations in .docx files based on a CSV mapping.

For every hyperlink in the word documents whose destination matches a
``link_destination`` in the CSV, the destination is rewritten to the
corresponding ``jade_article_link``.

Edits are **surgical**: only the ``.rels`` (relationship) files inside each
``.docx`` zip are touched — document content parts (``document.xml``,
``footnotes.xml``, etc.) are left byte-for-byte unchanged.

Usage:
    python docx_link_replacer.py [RAWS_DIR] [MAPPING_CSV] [RESULTS_CSV]

Defaults:
    RAWS_DIR     = ./raws
    MAPPING_CSV  = csvs/jade_easy_mncs.csv
    RESULTS_CSV  = jade_mnc_replacement_results.csv
"""

import csv
import os
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

# ── XML namespaces ────────────────────────────────────────────────────────────
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

W_HYPERLINK = f"{{{W_NS}}}hyperlink"
R_ID_ATTR = f"{{{R_NS}}}id"
PKG_RELATIONSHIP = f"{{{PKG_NS}}}Relationship"

# Register the package-relationships namespace so ET serialises it as the
# default namespace (matching the original .rels files).
ET.register_namespace("", PKG_NS)


# ── Helpers ───────────────────────────────────────────────────────────────────

def rels_path_for(content_path: str) -> str:
    """Return the .rels path that corresponds to a content part path.

    e.g. ``word/document.xml`` → ``word/_rels/document.xml.rels``
    """
    parent, name = content_path.rsplit("/", 1) if "/" in content_path else ("", content_path)
    return f"{parent}/_rels/{name}.rels" if parent else f"_rels/{name}.rels"


def parse_rels(data: bytes) -> dict[str, str]:
    """Parse a ``.rels`` file and return ``{rId: target}`` for every
    relationship whose ``TargetMode`` is ``External``."""
    root = ET.fromstring(data)
    mapping = {}
    for rel in root.iter(PKG_RELATIONSHIP):
        if (rel.get("TargetMode") or "").lower() == "external":
            rid = rel.get("Id")
            target = rel.get("Target")
            if rid and target:
                mapping[rid] = target
    return mapping


def rewrite_rels(data: bytes, rids_to_update: set[str],
                 url_mapping: dict[str, str]) -> bytes:
    """Return modified ``.rels`` bytes with updated ``Target`` values for the
    given *rids_to_update*."""
    root = ET.fromstring(data)
    for rel in root.iter(PKG_RELATIONSHIP):
        rid = rel.get("Id")
        if rid in rids_to_update:
            old_target = rel.get("Target")
            new_target = url_mapping.get(old_target)
            if new_target:
                rel.set("Target", new_target)
                rel.set("TargetMode", "External")
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def count_hyperlink_occurrences(content_data: bytes,
                                rid_to_target: dict[str, str],
                                url_mapping: dict[str, str]
                                ) -> tuple[dict[str, int], set[str]]:
    """Scan a content XML part for ``<w:hyperlink>`` elements whose resolved
    target is in *url_mapping*.

    Returns ``(counts, matched_rids)`` where *counts* maps
    ``old_destination → occurrence_count`` and *matched_rids* is the set of
    relationship IDs that need updating.
    """
    counts: dict[str, int] = defaultdict(int)
    matched_rids: set[str] = set()
    root = ET.fromstring(content_data)
    for hl in root.iter(W_HYPERLINK):
        rid = hl.get(R_ID_ATTR)
        if not rid:
            continue
        target = rid_to_target.get(rid)
        if target and target in url_mapping:
            counts[target] += 1
            matched_rids.add(rid)
    return dict(counts), matched_rids


# ── Main logic ────────────────────────────────────────────────────────────────

def load_mapping(csv_path: str) -> tuple[dict[str, str], list[dict]]:
    """Read the mapping CSV and return ``(url_mapping, rows)``.

    ``url_mapping`` is ``{link_destination: jade_article_link}``.
    ``rows`` is the list of original CSV rows (as dicts).
    """
    rows: list[dict] = []
    url_mapping: dict[str, str] = {}
    seen: set[str] = set()

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            old = (row.get("link_destination") or "").strip()
            new = (row.get("jade_article_link") or "").strip()
            if not old or not new:
                continue
            if old in seen:
                prev = url_mapping.get(old)
                if prev and prev != new:
                    print(f"  WARNING: duplicate link_destination with "
                          f"conflicting jade_article_link — keeping first.\n"
                          f"    destination: {old}\n"
                          f"    first:       {prev}\n"
                          f"    duplicate:   {new}")
                continue
            seen.add(old)
            url_mapping[old] = new

    return url_mapping, rows


def process_docx(doc_path: Path, url_mapping: dict[str, str]) -> dict[str, int]:
    """Process a single ``.docx``, rewriting matching hyperlink destinations.

    Returns ``{old_destination: occurrence_count}`` for links replaced in this
    document.
    """
    names: list[str]
    with zipfile.ZipFile(doc_path, "r") as zin:
        names = zin.namelist()

    # Identify content parts that might contain hyperlinks.
    content_parts = [
        n for n in names
        if n.startswith("word/")
        and n.endswith(".xml")
        and "/_rels/" not in n
    ]

    # Phase 1 — scan: count occurrences and collect rIds to change per rels file.
    doc_counts: dict[str, int] = defaultdict(int)
    rels_changes: dict[str, set[str]] = {}  # rels_path → rIds

    with zipfile.ZipFile(doc_path, "r") as zin:
        for cpart in content_parts:
            rpath = rels_path_for(cpart)
            if rpath not in names:
                continue
            rid_to_target = parse_rels(zin.read(rpath))
            if not rid_to_target:
                continue
            counts, matched = count_hyperlink_occurrences(
                zin.read(cpart), rid_to_target, url_mapping
            )
            for dest, n in counts.items():
                doc_counts[dest] += n
            if matched:
                rels_changes.setdefault(rpath, set()).update(matched)

    if not rels_changes:
        return dict(doc_counts)

    # Phase 2 — rewrite: create a new zip with updated .rels files.
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".docx", dir=doc_path.parent
    )
    os.close(tmp_fd)

    try:
        with zipfile.ZipFile(doc_path, "r") as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename in rels_changes:
                    data = rewrite_rels(
                        data, rels_changes[info.filename], url_mapping
                    )
                zout.writestr(info, data)
        # Atomic replace (same filesystem — dir matches).
        os.replace(tmp_path, doc_path)
    except Exception:
        # Clean up temp file on failure.
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return dict(doc_counts)


def main(raws_dir: str, mapping_csv: str, results_csv: str) -> None:
    raws = Path(raws_dir)
    if not raws.is_dir():
        sys.exit(f"Error: directory '{raws_dir}' does not exist.")

    print(f"Loading mapping from {mapping_csv} ...")
    url_mapping, csv_rows = load_mapping(mapping_csv)
    print(f"  {len(url_mapping)} unique link_destination → jade_article_link entries loaded.\n")

    docx_files = sorted(raws.glob("*.docx"))
    if not docx_files:
        sys.exit(f"No .docx files found in {raws}")

    global_counts: dict[str, int] = defaultdict(int)
    total_replaced = 0

    for doc_path in docx_files:
        print(f"Processing: {doc_path.name}")
        doc_counts = process_docx(doc_path, url_mapping)
        doc_total = sum(doc_counts.values())
        if doc_total:
            print(f"  → {doc_total} link(s) replaced")
        for dest, n in doc_counts.items():
            global_counts[dest] += n
        total_replaced += doc_total

    # ── Write results CSV ─────────────────────────────────────────────────
    fieldnames = list(csv_rows[0].keys()) if csv_rows else []
    if "times_replaced" not in fieldnames:
        fieldnames.append("times_replaced")

    with open(results_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in csv_rows:
            dest = (row.get("link_destination") or "").strip()
            row_out = dict(row)
            row_out["times_replaced"] = global_counts.get(dest, 0)
            writer.writerow(row_out)

    print(f"\nDone — {total_replaced} total replacement(s) across "
          f"{len(docx_files)} document(s).")
    print(f"Results written to {results_csv}")


if __name__ == "__main__":
    raws_dir = sys.argv[1] if len(sys.argv) > 1 else "./raws"
    mapping_csv = sys.argv[2] if len(sys.argv) > 2 else "csvs/jade_easy_mncs.csv"
    results_csv = sys.argv[3] if len(sys.argv) > 3 else "jade_mnc_replacement_results.csv"
    main(raws_dir, mapping_csv, results_csv)
