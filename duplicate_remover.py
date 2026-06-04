import csv

input_file = "./To Be Sent Out/non_legislation_links.csv"
output_file = "./To Be Sent Out/non_legislation_links_deduplicated.csv"

seen = set()

with open(input_file, newline='', encoding="utf-8") as infile, \
     open(output_file, "w", newline='', encoding="utf-8") as outfile:

    reader = csv.DictReader(infile)
    writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)

    writer.writeheader()

    for row in reader:
        dest = row.get("link_destination")
        jadeLink = row.get("jade_link")
        domain = row.get("link_domain")
        link_id = row.get("link_id")

        if dest in seen:
            print(link_id + ": " +domain)
            continue

        seen.add(dest)
        seen.add(jadeLink)
        writer.writerow(row)