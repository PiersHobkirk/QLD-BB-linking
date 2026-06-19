#!/usr/bin/env python3
"""
Replace hyperlink destinations in .docx files based on a CSV mapping
and extract all hyperlinks found across documents into a text file.

Edits are surgical: only .rels files are modified.
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

ET.register_namespace("", PKG_NS)


# ── Helpers ───────────────────────────────────────────────────────────────────

def rels_path_for(content_path: str) -> str:
    parent, name = content_path.rsplit("/", 1) if "/" in content_path else ("", content_path)
    return f"{parent}/_rels/{name}.rels" if parent else f"_rels/{name}.rels"


def parse_rels(data: bytes) -> dict[str, str]:
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
                                ):
    counts = defaultdict(int)
    matched_rids = set()
    found_urls = set()

    root = ET.fromstring(content_data)

    for hl in root.iter(W_HYPERLINK):
        rid = hl.get(R_ID_ATTR)
        if not rid:
            continue

        target = rid_to_target.get(rid)

        if target:
            found_urls.add(target)

        if target and target in url_mapping:
            counts[target] += 1
            matched_rids.add(rid)

    return dict(counts), matched_rids, found_urls


# ── CSV mapping ───────────────────────────────────────────────────────────────

def load_mapping(csv_path: str):
    rows = []
    url_mapping = {}
    seen = set()

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            old = (row.get("og_url") or "").strip()
            new = (row.get("remapped_url") or "").strip()
            if not old or not new:
                continue
            if old in seen:
                continue
            seen.add(old)
            url_mapping[old] = new

    return url_mapping, rows


# ── DOCX processing ───────────────────────────────────────────────────────────

def process_docx(doc_path: Path, url_mapping: dict[str, str]):
    names = []
    with zipfile.ZipFile(doc_path, "r") as zin:
        names = zin.namelist()

    content_parts = [
        n for n in names
        if n.startswith("word/")
        and n.endswith(".xml")
        and "/_rels/" not in n
    ]

    doc_counts = defaultdict(int)
    rels_changes = {}
    all_found_urls = set()

    with zipfile.ZipFile(doc_path, "r") as zin:
        for cpart in content_parts:
            rpath = rels_path_for(cpart)
            if rpath not in names:
                continue

            rid_to_target = parse_rels(zin.read(rpath))
            if not rid_to_target:
                continue

            counts, matched, found_urls = count_hyperlink_occurrences(
                zin.read(cpart), rid_to_target, url_mapping
            )

            all_found_urls.update(found_urls)

            for dest, n in counts.items():
                doc_counts[dest] += n

            if matched:
                rels_changes.setdefault(rpath, set()).update(matched)

    if rels_changes:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".docx", dir=doc_path.parent)
        os.close(tmp_fd)

        try:
            with zipfile.ZipFile(doc_path, "r") as zin, \
                 zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:

                for info in zin.infolist():
                    data = zin.read(info.filename)

                    if info.filename in rels_changes:
                        data = rewrite_rels(
                            data,
                            rels_changes[info.filename],
                            url_mapping
                        )

                    zout.writestr(info, data)

            os.replace(tmp_path, doc_path)

        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    return dict(doc_counts), all_found_urls


# ── Main ──────────────────────────────────────────────────────────────────────

def main(raws_dir: str, mapping_csv: str, results_csv: str):

    raws = Path(raws_dir)
    if not raws.is_dir():
        sys.exit("raws dir missing")

    url_mapping, csv_rows = load_mapping(mapping_csv)

    docx_files = sorted(raws.glob("*.docx"))

    global_counts = defaultdict(int)
    all_found_urls = set()

    for doc_path in docx_files:
        print("Processing:", doc_path.name)

        doc_counts, found_urls = process_docx(doc_path, url_mapping)

        all_found_urls.update(found_urls)

        for k, v in doc_counts.items():
            global_counts[k] += v

    # ── write results CSV ────────────────────────────────────────────────
    fieldnames = list(csv_rows[0].keys()) if csv_rows else []
    if "times_replaced" not in fieldnames:
        fieldnames.append("times_replaced")

    with open(results_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in csv_rows:
            dest = (row.get("og_url") or "").strip()
            row["times_replaced"] = global_counts.get(dest, 0)
            writer.writerow(row)

    # ── write all found URLs ─────────────────────────────────────────────
    with open("all_found_links.txt", "w", encoding="utf-8") as f:
        for url in sorted(all_found_urls):
            f.write(url + "\n")

    print("\nDone.")
    print(f"Found {len(all_found_urls)} unique links.")
    print(f"Results CSV: {results_csv}")
    print("all_found_links.txt written")


if __name__ == "__main__":
    raws_dir = sys.argv[1] if len(sys.argv) > 1 else "./raws"
    mapping_csv = sys.argv[2] if len(sys.argv) > 2 else "final_map/proposed_remapped_links_v3.csv"
    results_csv = sys.argv[3] if len(sys.argv) > 3 else "jade_mnc_replacement_results.csv"
    main(raws_dir, mapping_csv, results_csv)