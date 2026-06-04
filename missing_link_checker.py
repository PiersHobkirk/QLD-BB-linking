import csv
import os

A_PATH = "./link_mapping/QLDBB_link_map_deduplicated.csv"
B_PATH = "./philip_links/qld_bb_prod_hrefs.csv"
C_PATH = "./philip_links/qld_bb_prod_overlays.csv"

OUT_NOT_IN_PROD = "./working_out_csvs/not_in_prod.csv"
OUT_NOT_IN_PDF = "./working_out_csvs/not_in_pdf.csv"


def read_column_as_set(path, column_name):
    values = set()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            val = row.get(column_name)
            if val:
                values.add(val.strip())
    return values


# --- Load A ---
a_rows = []
a_destinations = set()

with open(A_PATH, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    a_fieldnames = reader.fieldnames

    for row in reader:
        a_rows.append(row)
        dest = row.get("link_destination")
        if dest:
            a_destinations.add(dest.strip())


# --- Load B and C URLs ---
b_urls = read_column_as_set(B_PATH, "url")
c_urls = read_column_as_set(C_PATH, "url")

prod_urls = b_urls | c_urls


# --- Output 1: rows in A not present in B/C ---
os.makedirs("./working_out_csvs", exist_ok=True)

with open(OUT_NOT_IN_PROD, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=a_fieldnames)
    writer.writeheader()

    for row in a_rows:
        dest = (row.get("link_destination") or "").strip()
        if dest not in prod_urls:
            writer.writerow(row)


# --- Output 2: URLs in B/C not present in A ---
missing_in_pdf = prod_urls - a_destinations

with open(OUT_NOT_IN_PDF, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["url"]
    )
    writer.writeheader()

    for url in sorted(missing_in_pdf):
        writer.writerow({"url": url})