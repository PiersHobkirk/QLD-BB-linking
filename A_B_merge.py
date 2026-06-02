#!/usr/bin/env python3

"""
Update QLDBB_link_map.csv by filling jade_link from jade_easy_mncs.csv.

Rules:
- Match rows on identical link_destination.
- For each unique link_destination in CSV B, all jade_article_link values
  must be identical. If not, report a conflict and continue.
- Update matching rows in CSV A:
    jade_link = jade_article_link
- Report:
    * conflicting jade_article_link values in CSV B
    * link_destinations from CSV B not found in CSV A
    * rows in CSV A where jade_link already had content
- Save CSV A in place.
"""

from collections import defaultdict
import csv
from pathlib import Path

CSV_A = Path("link_mapping/QLDBB_link_map.csv")
CSV_B = Path("csvs/jade_easy_mncs.csv")


def normalise(value):
    return (value or "").strip()


# ---------------------------------------------------------------------------
# Load CSV B and check for conflicting jade_article_links
# ---------------------------------------------------------------------------

b_destinations = defaultdict(set)

with CSV_B.open("r", newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)

    for row in reader:
        link_destination = normalise(row.get("link_destination"))
        jade_article_link = normalise(row.get("jade_article_link"))

        if link_destination:
            b_destinations[link_destination].add(jade_article_link)

conflicting_b_links = []

# Final mapping: link_destination -> jade_article_link
destination_to_jade = {}

for link_destination, jade_links in b_destinations.items():
    non_empty = {x for x in jade_links if x}

    if len(non_empty) > 1:
        conflicting_b_links.append(
            {
                "link_destination": link_destination,
                "jade_article_links": sorted(non_empty),
            }
        )
        # Continue anyway; arbitrarily choose first sorted value
        destination_to_jade[link_destination] = sorted(non_empty)[0]
    elif len(non_empty) == 1:
        destination_to_jade[link_destination] = next(iter(non_empty))
    else:
        destination_to_jade[link_destination] = ""


# ---------------------------------------------------------------------------
# Load CSV A
# ---------------------------------------------------------------------------

with CSV_A.open("r", newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    rows_a = list(reader)

if not fieldnames:
    raise RuntimeError("CSV A has no header row")

# Build lookup by link_destination
rows_by_destination = defaultdict(list)

for row in rows_a:
    link_destination = normalise(row.get("link_destination"))
    rows_by_destination[link_destination].append(row)

# ---------------------------------------------------------------------------
# Apply updates
# ---------------------------------------------------------------------------

not_found = []
existing_jade_conflicts = []

for link_destination, jade_article_link in destination_to_jade.items():
    matching_rows = rows_by_destination.get(link_destination, [])

    if not matching_rows:
        not_found.append(link_destination)
        continue

    for row in matching_rows:
        existing_jade = normalise(row.get("jade_link"))

        if existing_jade:
            existing_jade_conflicts.append(
                {
                    "link_id": row.get("link_id", ""),
                    "link_destination": link_destination,
                    "existing_jade_link": existing_jade,
                    "new_jade_link": jade_article_link,
                }
            )

        if not existing_jade:
            row["jade_link"] = jade_article_link

# ---------------------------------------------------------------------------
# Save CSV A in place
# ---------------------------------------------------------------------------

with CSV_A.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows_a)

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

print()
print("=== SUMMARY ===")
print(f"Unique link_destinations in CSV B: {len(destination_to_jade)}")
print(f"Rows in CSV A: {len(rows_a)}")
print()

if conflicting_b_links:
    print("=== CONFLICT: DIFFERENT jade_article_link VALUES IN CSV B ===")
    for conflict in conflicting_b_links:
        print(f"link_destination: {conflict['link_destination']}")
        for value in conflict["jade_article_links"]:
            print(f"  {value}")
        print()
else:
    print("No conflicting jade_article_link values in CSV B.")
    print()

if existing_jade_conflicts:
    print("=== CONFLICT: jade_link ALREADY POPULATED IN CSV A ===")
    for conflict in existing_jade_conflicts:
        print(
            f"link_id={conflict['link_id']} "
            f"destination={conflict['link_destination']}"
        )
        print(f"  existing: {conflict['existing_jade_link']}")
        print(f"  new:      {conflict['new_jade_link']}")
        print()
else:
    print("No existing jade_link values overwritten in CSV A.")
    print()

if not_found:
    print("=== NOT FOUND IN CSV A ===")
    for destination in not_found:
        print(destination)
    print()
else:
    print("All CSV B link_destinations were found in CSV A.")
    print()

print("CSV A updated successfully.")