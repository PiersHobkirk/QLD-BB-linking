from pathlib import Path
import csv

CSV_A = Path("link_mapping/QLDBB_link_map.csv")
CSV_B = Path("link_mapping/legislation_potential_jade_links.csv")

OUT = Path("link_mapping/QLDBB_link_map_UPDATED.csv")


def norm(v):
    return (v or "").strip()


# Load CSV A
with CSV_A.open(newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows_a = list(reader)
    fieldnames = reader.fieldnames

index_a = {norm(r["link_id"]): i for i, r in enumerate(rows_a)}

# Read CSV B updates
updates = []
with CSV_B.open(newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        link_id = norm(row.get("link_id"))
        jade_link = norm(row.get("jade_link"))

        if not link_id:
            continue

        updates.append((link_id, jade_link))


# Tracking
applied = 0
skipped_existing = []
missing_in_a = []
empty_in_b = []
updated = []


for link_id, new_jade in updates:
    if not new_jade:
        empty_in_b.append(link_id)
        continue

    if link_id not in index_a:
        missing_in_a.append(link_id)
        continue

    row = rows_a[index_a[link_id]]
    existing = norm(row.get("jade_link"))

    if existing:
        skipped_existing.append((link_id, existing))
        continue

    row["jade_link"] = new_jade
    applied += 1
    updated.append((link_id, new_jade))


# Write output
with OUT.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows_a)


# Reporting
print("\n=== UPDATED ===")
for link_id, jade in updated:
    print(f"[UPDATED] {link_id} → {jade}")

print("\n=== SKIPPED (already had value in CSV A) ===")
for link_id, existing in skipped_existing:
    print(f"[SKIP-EXISTS] {link_id} (existing='{existing}')")

print("\n=== MISSING IN CSV A ===")
for link_id in missing_in_a:
    print(f"[MISSING-A] {link_id}")

print("\n=== SUMMARY ===")
print(f"Applied updates: {applied}")
print(f"Skipped (existing values): {len(skipped_existing)}")
print(f"Missing in A: {len(missing_in_a)}")
print(f"Empty in B: {len(empty_in_b)}")

print(f"\nWrote: {OUT}")