"""
Demo 1: Python Script with Simple Aggregations

Fetches daily active user data from the MEMORIA public API
and performs basic aggregations (totals, averages, peak day).

Usage:
    python demo1_python_aggregation.py
    python demo1_python_aggregation.py --url http://localhost:8899/chat/api/active-users/
"""

import sys
import requests

API_URL = "https://miramemoria.com/chat/api/active-users/"


def main():
    url = API_URL
    for arg in sys.argv[1:]:
        if arg.startswith("--url="):
            url = arg.split("=", 1)[1]

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    data = response.json()
    results = data["results"]
    record_count = data["count"]

    total_active_users = sum(r["active_users"] for r in results)
    total_messages = sum(r["message_count"] for r in results)
    days_with_activity = sum(1 for r in results if r["active_users"] > 0)

    avg_daily_users = total_active_users / record_count if record_count else 0
    avg_daily_messages = total_messages / record_count if record_count else 0

    peak_day = max(results, key=lambda r: r["active_users"])
    busiest_msg_day = max(results, key=lambda r: r["message_count"])

    print("=" * 60)
    print("MEMORIA Public API: Daily Active Users Aggregation")
    print("=" * 60)
    print(f"API Endpoint:         {url}")
    print(f"Total Days Covered:   {record_count}")
    print(f"Days with Activity:   {days_with_activity}")
    print("-" * 60)
    print(f"Total Active Users:   {total_active_users}")
    print(f"Total Messages:       {total_messages}")
    print(f"Avg Daily Users:      {avg_daily_users:.2f}")
    print(f"Avg Daily Messages:   {avg_daily_messages:.2f}")
    print("-" * 60)
    print(f"Peak User Day:        {peak_day['date']} ({peak_day['active_users']} users)")
    print(f"Busiest Message Day:  {busiest_msg_day['date']} ({busiest_msg_day['message_count']} messages)")
    print("=" * 60)

    print("\nFirst 5 records:")
    print(f"{'Date':<14} {'Active Users':>14} {'Messages':>10}")
    print("-" * 40)
    for r in results[:5]:
        print(f"{r['date']:<14} {r['active_users']:>14} {r['message_count']:>10}")


if __name__ == "__main__":
    main()
