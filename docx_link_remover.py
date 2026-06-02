#!/usr/bin/env python3
"""
Remove all hyperlinks from .docx files while preserving text and formatting.

The script surgically removes <w:hyperlink> elements and promotes their
contents into the parent element.

Only XML parts that actually contain hyperlinks are modified.

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

ET.register_namespace("w", W_NS)

# CONSTANTS

W_FLDCHAR = f"{{{W_NS}}}fldChar"
W_INSTRTEXT = f"{{{W_NS}}}instrText"
FLDCHAR_TYPE = f"{{{W_NS}}}fldCharType"

# ── Helpers ───────────────────────────────────────────────────────────────────

# FIELDSPACE REMOVAL

def remove_hyperlink_fields(root):
    """
    Remove HYPERLINK field codes while preserving displayed text.

    Returns number of hyperlink fields removed.
    """
    removed = 0

    for parent in root.iter():
        children = list(parent)

        i = 0
        while i < len(children):

            child = children[i]

            if (
                child.tag == W_R
                and len(child)
                and child[0].tag == W_FLDCHAR
                and child[0].get(FLDCHAR_TYPE) == "begin"
            ):
                start = i

                # Locate matching fldChar end
                j = i + 1
                found_hyperlink = False
                end = None

                while j < len(children):

                    c = children[j]

                    if c.tag == W_R:
                        for desc in c.iter():
                            if (
                                desc.tag == W_INSTRTEXT
                                and desc.text
                                and "HYPERLINK" in desc.text.upper()
                            ):
                                found_hyperlink = True

                        for desc in c.iter():
                            if (
                                desc.tag == W_FLDCHAR
                                and desc.get(FLDCHAR_TYPE) == "end"
                            ):
                                end = j
                                break

                    if end is not None:
                        break

                    j += 1

                if found_hyperlink and end is not None:

                    # Remove everything except display runs
                    to_delete = []

                    inside_display = False

                    for k in range(start, end + 1):

                        elem = children[k]

                        keep = False

                        if elem.tag == W_R:

                            fldchars = list(elem.iter(W_FLDCHAR))

                            if fldchars:
                                fld_type = fldchars[0].get(FLDCHAR_TYPE)

                                if fld_type == "separate":
                                    inside_display = True
                                    keep = False

                                elif fld_type in ("begin", "end"):
                                    keep = False

                            elif any(
                                t.tag == W_INSTRTEXT
                                for t in elem.iter()
                            ):
                                keep = False

                            elif inside_display:
                                keep = True

                        if not keep:
                            to_delete.append(elem)

                    for elem in to_delete:
                        if elem in parent:
                            parent.remove(elem)

                    removed += 1

                    children = list(parent)
                    i = 0
                    continue

            i += 1

    return removed

def remove_hyperlinks_from_xml(xml_bytes: bytes) -> tuple[bytes, int]:
    """
    Remove all <w:hyperlink> elements from a document part.

    Returns:
        (modified_xml_bytes, hyperlink_count_removed)
    """
    root = ET.fromstring(xml_bytes)
    removed = 0

    for parent in root.iter():
        children = list(parent)

        for idx, child in enumerate(children):
            if child.tag != W_HYPERLINK:
                continue

            removed += 1

            insertion_index = idx

            # Preserve all child elements (runs, proofing marks, etc.)
            for grandchild in list(child):
                parent.insert(insertion_index, grandchild)
                insertion_index += 1

            parent.remove(child)

    if not removed:
        return xml_bytes, 0

    return (
        ET.tostring(root, encoding="UTF-8", xml_declaration=True),
        removed,
    )


def process_docx(doc_path: Path) -> int:
    """
    Remove hyperlinks from a single DOCX.

    Returns:
        Number of hyperlinks removed.
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