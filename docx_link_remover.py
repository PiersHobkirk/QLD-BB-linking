#!/usr/bin/env python3
"""
Remove all hyperlinks from .docx files while preserving text and formatting.

Removes:
1) <w:hyperlink> elements
2) Word field-based hyperlinks (HYPERLINK fields using fldChar + instrText)

Usage:
    python remove_docx_hyperlinks.py [RAWS_DIR]

Defaults:
    RAWS_DIR = ./raws
"""

import os
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


# ── XML namespaces ────────────────────────────────────────────────────────────

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

W_HYPERLINK = f"{{{W_NS}}}hyperlink"
W_R = f"{{{W_NS}}}r"
W_FLDCHAR = f"{{{W_NS}}}fldChar"
W_INSTRTEXT = f"{{{W_NS}}}instrText"
FLDCHAR_TYPE = f"{{{W_NS}}}fldCharType"

ET.register_namespace("w", W_NS)


# ── XML helpers ───────────────────────────────────────────────────────────────

def remove_hyperlink_fields(root):
    """
    Remove HYPERLINK field codes while preserving display runs.

    Handles:
    fldChar(begin) -> instrText(HYPERLINK ...) -> fldChar(separate) -> display -> fldChar(end)
    """
    removed = 0

    for parent in root.iter():
        children = list(parent)

        i = 0
        while i < len(children):

            child = children[i]

            if child.tag != W_R:
                i += 1
                continue

            fldchars = list(child.findall(W_FLDCHAR))
            if not fldchars:
                i += 1
                continue

            # must be field start
            if fldchars[0].get(FLDCHAR_TYPE) != "begin":
                i += 1
                continue

            # scan ahead to detect hyperlink field structure
            j = i + 1
            found_hyperlink = False
            end_idx = None
            separate_idx = None

            while j < len(children):
                r = children[j]

                # detect instrText
                for it in r.findall(W_INSTRTEXT):
                    if it.text and "HYPERLINK" in it.text.upper():
                        found_hyperlink = True

                # detect field boundaries
                for fc in r.findall(W_FLDCHAR):
                    ftype = fc.get(FLDCHAR_TYPE)
                    if ftype == "separate":
                        separate_idx = j
                    elif ftype == "end":
                        end_idx = j
                        break

                if end_idx is not None:
                    break

                j += 1

            if not found_hyperlink or end_idx is None:
                i += 1
                continue

            # keep only display runs between separate and end
            display_start = (separate_idx + 1) if separate_idx is not None else (i + 1)
            display_end = end_idx

            kept = set(range(display_start, display_end))

            new_children = []
            for idx, c in enumerate(children):
                if idx < i or idx > end_idx:
                    new_children.append(c)
                elif idx in kept:
                    new_children.append(c)

            # rebuild parent
            for c in children:
                if c in parent:
                    parent.remove(c)

            for c in new_children:
                parent.append(c)

            removed += 1
            children = list(parent)
            i = 0
            continue

        # end while

    return removed


def remove_hyperlinks_from_xml(xml_bytes: bytes) -> tuple[bytes, int]:
    """
    Remove:
      - <w:hyperlink>
      - field-based HYPERLINK constructs
    """
    root = ET.fromstring(xml_bytes)
    removed = 0

    # 1) Remove explicit hyperlink elements
    for parent in root.iter():
        children = list(parent)

        for idx, child in enumerate(children):
            if child.tag != W_HYPERLINK:
                continue

            removed += 1

            insertion_index = idx

            for grandchild in list(child):
                parent.insert(insertion_index, grandchild)
                insertion_index += 1

            parent.remove(child)

    # 2) Remove field-based hyperlinks
    removed += remove_hyperlink_fields(root)

    if removed == 0:
        return xml_bytes, 0

    return (
        ET.tostring(root, encoding="UTF-8", xml_declaration=True),
        removed,
    )


# ── DOCX processing ───────────────────────────────────────────────────────────

def process_docx(doc_path: Path) -> int:
    """
    Remove hyperlinks from a single DOCX file.
    """
    total_removed = 0

    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".docx",
        dir=doc_path.parent,
    )
    os.close(tmp_fd)

    try:
        with zipfile.ZipFile(doc_path, "r") as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:

            for info in zin.infolist():
                data = zin.read(info.filename)

                should_check = (
                    info.filename.startswith("word/")
                    and info.filename.endswith(".xml")
                    and "/_rels/" not in info.filename
                )

                if should_check:
                    data, removed = remove_hyperlinks_from_xml(data)
                    total_removed += removed

                zout.writestr(info, data)

        os.replace(tmp_path, doc_path)

    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return total_removed


# ── Main ──────────────────────────────────────────────────────────────────────

def main(raws_dir: str) -> None:
    raws = Path(raws_dir)

    if not raws.is_dir():
        sys.exit(f"Error: directory '{raws_dir}' does not exist.")

    docx_files = sorted(raws.glob("*.docx"))

    if not docx_files:
        sys.exit(f"No .docx files found in {raws}")

    grand_total = 0

    for doc_path in docx_files:
        print(f"Processing: {doc_path.name}")

        removed = process_docx(doc_path)

        print(f"  → {removed} hyperlink(s) removed")

        grand_total += removed

    print(
        f"\nDone — {grand_total} hyperlink(s) removed across "
        f"{len(docx_files)} document(s)."
    )


if __name__ == "__main__":
    raws_dir = sys.argv[1] if len(sys.argv) > 1 else "./raws"
    main(raws_dir)