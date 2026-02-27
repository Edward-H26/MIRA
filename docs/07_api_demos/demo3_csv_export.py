"""
Demo 3: CSV Export for Excel / Google Sheets

Fetches daily active user data from the MEMORIA public API
and exports it to a CSV file that can be opened in Excel
or imported into Google Sheets.

Usage:
    python demo3_csv_export.py
    python demo3_csv_export.py --url http://localhost:8899/chat/api/active-users/

Output:
    Creates active_users_export.csv in the current directory.

To import into Google Sheets:
    1. Open Google Sheets (sheets.google.com)
    2. File > Import > Upload > select active_users_export.csv
    3. Choose "Replace spreadsheet" or "Insert new sheet"
    4. Click "Import data"

To open in Excel:
    1. Double-click active_users_export.csv
    2. Or: File > Open > select active_users_export.csv
"""

import csv
import sys
import requests

API_URL = "https://miramemoria.com/chat/api/active-users/"
OUTPUT_FILE = "active_users_export.csv"


def main():
    url = API_URL
    for arg in sys.argv[1:]:
        if arg.startswith("--url="):
            url = arg.split("=", 1)[1]

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    data = response.json()
    results = data["results"]

    with open(OUTPUT_FILE, "w", newline="") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=["date", "active_users", "message_count"],
        )
        writer.writeheader()
        writer.writerows(results)

    print("=" * 60)
    print("MEMORIA Public API: CSV Export")
    print("=" * 60)
    print(f"API Endpoint:   {url}")
    print(f"Records:        {data['count']}")
    print(f"Output File:    {OUTPUT_FILE}")
    print("-" * 60)
    print(f"CSV created successfully with {data['count']} rows.")
    print()
    print("Preview (first 5 rows):")
    print(f"{'date':<14} {'active_users':>14} {'message_count':>14}")
    print("-" * 44)
    for r in results[:5]:
        print(f"{r['date']:<14} {r['active_users']:>14} {r['message_count']:>14}")
    print()
    print("Import instructions:")
    print("  Excel:         Double-click the CSV file to open")
    print("  Google Sheets: File > Import > Upload > select CSV")
    print("=" * 60)


if __name__ == "__main__":
    main()
