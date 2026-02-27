"""
Demo 2: Data Analysis with pandas

Fetches daily active user data from the MEMORIA public API,
loads it into a pandas DataFrame, and computes descriptive
statistics including mean, median, standard deviation,
and correlation between active users and message count.

Usage:
    pip install pandas requests
    python demo2_pandas_analysis.py
    python demo2_pandas_analysis.py --url http://localhost:8899/chat/api/active-users/
"""

import sys
import requests
import pandas as pd

API_URL = "https://miramemoria.com/chat/api/active-users/"


def main():
    url = API_URL
    for arg in sys.argv[1:]:
        if arg.startswith("--url="):
            url = arg.split("=", 1)[1]

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    data = response.json()
    df = pd.DataFrame(data["results"])
    df["date"] = pd.to_datetime(df["date"])

    print("=" * 60)
    print("MEMORIA Public API: pandas Statistical Analysis")
    print("=" * 60)
    print(f"API Endpoint: {url}")
    print(f"Records:      {len(df)}")
    print(f"Date Range:   {df['date'].min().date()} to {df['date'].max().date()}")
    print()

    print("Descriptive Statistics:")
    print("-" * 60)
    stats = df[["active_users", "message_count"]].describe()
    print(stats.to_string())
    print()

    correlation = df["active_users"].corr(df["message_count"])
    print(f"Correlation (active_users vs message_count): {correlation:.4f}")
    print()

    print("Top 5 Days by Active Users:")
    print("-" * 60)
    top_users = df.nlargest(5, "active_users")[["date", "active_users", "message_count"]]
    top_users["date"] = top_users["date"].dt.strftime("%Y-%m-%d")
    print(top_users.to_string(index=False))
    print()

    print("Weekly Summary:")
    print("-" * 60)
    df["week"] = df["date"].dt.isocalendar().week
    weekly = df.groupby("week").agg(
        total_users=("active_users", "sum"),
        total_messages=("message_count", "sum"),
        avg_users=("active_users", "mean"),
    ).round(2)
    print(weekly.to_string())
    print("=" * 60)


if __name__ == "__main__":
    main()
