#!/usr/bin/env python3

import pandas as pd
from difflib import SequenceMatcher
from pathlib import Path


CSV_A = Path("link_mapping/linkless_jade_links.csv")
CSV_B = Path("link_mapping/QLDBB_link_map.csv")
OUTPUT = Path("link_mapping/potential_jade_links.csv")


def normalize(text):
    """
    Lowercase and remove all whitespace.
    """
    if pd.isna(text):
        return ""

    return "".join(str(text).lower().split())


def similarity(a, b):
    """
    Similarity score from 0.0 to 1.0.
    """
    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def main():
    print(f"Reading {CSV_A}")
    df_a = pd.read_csv(CSV_A, dtype=str).fillna("")

    print(f"Reading {CSV_B}")
    df_b = pd.read_csv(CSV_B, dtype=str).fillna("")

    # Precompute normalized surrounding text
    df_a["_norm"] = df_a["surrounding_text"].map(normalize)
    df_b["_norm"] = df_b["surrounding_text"].map(normalize)

    # Precompute page numbers
    df_a["_page"] = df_a["page_no"].map(safe_int)
    df_b["_page"] = df_b["page_no"].map(safe_int)

    # Build page lookup for CSV A
    page_lookup = {}

    for idx, row in df_a.iterrows():
        page = row["_page"]

        if page is None:
            continue

        page_lookup.setdefault(page, []).append(idx)

    # Output columns
    df_b["match_score"] = 0.0
    df_b["potential_jade_link_text"] = "NA"
    df_b["potential_jade_link"] = "NA"

    total = len(df_b)

    for b_idx, b_row in df_b.iterrows():
        if b_idx % 1000 == 0:
            print(f"Processing {b_idx:,}/{total:,}")

        b_page = b_row["_page"]
        b_text = b_row["_norm"]

        if b_page is None or not b_text:
            continue

        candidate_indices = []

        for page in (b_page - 1, b_page, b_page + 1):
            candidate_indices.extend(page_lookup.get(page, []))

        if not candidate_indices:
            continue

        best_score = 0.0
        best_row = None

        for a_idx in candidate_indices:
            a_row = df_a.loc[a_idx]

            score = similarity(b_text, a_row["_norm"])

            if score > best_score:
                best_score = score
                best_row = a_row

        if best_row is not None:
            df_b.at[b_idx, "match_score"] = round(best_score, 6)
            df_b.at[b_idx, "potential_jade_link_text"] = best_row["link_text"]
            df_b.at[b_idx, "potential_jade_link"] = best_row["link_destination"]

    # Remove helper columns
    df_b = df_b.drop(columns=["_norm", "_page"])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df_b.to_csv(OUTPUT, index=False)

    print(f"\nDone.")
    print(f"Output written to: {OUTPUT}")


if __name__ == "__main__":
    main()