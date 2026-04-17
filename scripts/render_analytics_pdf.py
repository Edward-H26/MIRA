"""Render the INFO490 Analytics Dashboard submission PDF (~1.5 pages)."""

import argparse
import os
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCREENSHOT_DIR = os.path.join(REPO_ROOT, "docs", "screenshots", "analytics")
DEFAULT_OUT = os.path.join(
    REPO_ROOT, "docs", "08_ai_architecture", "A10_ANALYTICS_DASHBOARD.pdf"
)


PAGE_W_IN = 8.5
PAGE_H_IN = 11.0
PAGE2_H_IN = 5.6


QUESTIONS = {
    "System Performance": [
        "A1. How does end-to-end latency vary across requests over a 30-day window?",
        "A2. Which model contributes most to overall response time?",
        "A3. What fraction of requests fail or fall back, and how does that pattern correlate with traffic spikes?",
    ],
    "User Behavior": [
        "B1. How is the user's memory store distributed across semantic, episodic, and procedural types?",
        "B2. How active is each user across days, weeks, and months?",
        "B3. What is the strength distribution of stored memories, and what fraction is below 50?",
    ],
    "Cost": [
        "C1. What is the average cost per request, and how does it move day over day?",
        "C2. Which model accounts for the largest share of spend, and is that proportional to value?",
        "C3. What is the prompt-vs-completion token split, and how does that ratio behave over time?",
        "C4. What is the projected monthly burn at the current trajectory?",
    ],
}


WIDGET_ROWS = [
    ("A1", "Latency Over Time + Avg/P95/Total/Error KPI cards", "Line chart + 4 KPI cards"),
    ("A2", "Latency by Model", "Bar chart"),
    ("A3", "Request Status Distribution + Breakdown table", "Pie chart + table"),
    ("B1", "Memory Type Distribution + Semantic/Episodic/Procedural KPIs", "Pie chart + 3 KPI cards"),
    ("B2", "Conversation Activity + Sessions/Messages KPIs + grouped table", "Line chart + KPIs + table"),
    ("B3", "Memory Strength Distribution + Avg Strength KPI", "Bar chart + KPI card"),
    ("C1", "Daily Cost Trend + Avg Cost/Request KPI", "Area chart + KPI card"),
    ("C2", "Cost by Model + breakdown table", "Bar chart + table"),
    ("C3", "Token Usage Breakdown + Prompt/Completion KPI", "Stacked bar + KPI"),
    ("C4", "Total Cost + Total Tokens KPIs + 30-day trend", "KPI cards + line"),
]


STAT_TEXT = (
    "Central tendency and dispersion. Latency cards report mean and p95 together because "
    "mean alone hides the long tail; both are computed inside _get_performance_metrics by "
    "sorting the latency series and indexing the 50th and 95th percentile elements.\n\n"
    "Distributions over categorical and numeric axes. Memory Type and Request Status pies "
    "are categorical histograms; the Memory Strength bar bins a numeric variable into 25-point "
    "ranges. Together they make imbalance visible at a glance.\n\n"
    "Trends over time and group comparisons. Latency Over Time, Conversation Activity, and "
    "Daily Cost Trend bucket events by day across a 30-day window. Group comparisons in "
    "Latency-by-Model, Cost-by-Model, and Token Usage Breakdown answer 'which group is the "
    "outlier' without forcing a tab switch."
)


SUBMISSION_META = [
    ("Live URL", "https://mira-ydqq.onrender.com/chat/analytics/"),
    ("Local URL", "http://127.0.0.1:8000/chat/analytics/"),
    ("Test login", "username: mohitg2  |  password: uiuc12345"),
    ("Re-seed (local)", "python manage.py seed_analytics --user mohitg2 --days 90"),
    ("Sample JSON", "docs/07_api_demos/analytics_api_sample.json"),
    ("Screenshots", "docs/screenshots/analytics/{01,02,03}_*.png"),
    ("Source design doc", "docs/08_ai_architecture/A10_ANALYTICS_DASHBOARD.md"),
]


def _draw_page1(pdf):
    fig = plt.figure(figsize=(PAGE_W_IN, PAGE_H_IN))
    fig.subplots_adjust(left=0.05, right=0.95, top=0.96, bottom=0.04)
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    y = 0.97
    ax.text(0.05, y, "INFO490 Analytics Dashboard", fontsize=18, fontweight="bold",
            ha="left", va="top")
    y -= 0.03
    ax.text(0.05, y, "Memoria  |  https://mira-ydqq.onrender.com/chat/analytics/  |  test login: mohitg2 / uiuc12345",
            fontsize=8.5, color="#444", ha="left", va="top")
    y -= 0.025
    ax.text(0.05, y, "Snapshot 2026-04-17. 1,641 requests, 70 memory bullets, $0.5967 spend across 90 days.",
            fontsize=8, color="#666", style="italic", ha="left", va="top")
    y -= 0.03

    ax.text(0.05, y, "Part 1.1 — Analytics questions (10 across 3 categories)",
            fontsize=11, fontweight="bold", ha="left", va="top")
    y -= 0.020
    col_x = [0.05, 0.36, 0.67]
    col_top = y
    line_height = 0.013
    block_gap = 0.010
    wrap_width = 42
    cy_after = col_top
    for i, (cat, qs) in enumerate(QUESTIONS.items()):
        x = col_x[i]
        ax.text(x, col_top, cat, fontsize=9.5, fontweight="bold",
                color="#1f4e79", ha="left", va="top")
        cy = col_top - 0.020
        for q in qs:
            for line in textwrap.wrap(q, width=wrap_width):
                ax.text(x, cy, line, fontsize=7.3, ha="left", va="top")
                cy -= line_height
            cy -= block_gap
        cy_after = min(cy_after, cy)
    y = cy_after - 0.005

    ax.text(0.05, y, "Part 1.2 — Widget design plan (question to widget)",
            fontsize=11, fontweight="bold", ha="left", va="top")
    y -= 0.02
    header = ["Q", "Widget", "Type"]
    col_left = [0.05, 0.10, 0.65]
    ax.text(col_left[0], y, header[0], fontsize=8.5, fontweight="bold", va="top")
    ax.text(col_left[1], y, header[1], fontsize=8.5, fontweight="bold", va="top")
    ax.text(col_left[2], y, header[2], fontsize=8.5, fontweight="bold", va="top")
    y -= 0.014
    ax.plot([0.05, 0.95], [y, y], color="#bbb", lw=0.5)
    y -= 0.012
    for q, widget, wtype in WIDGET_ROWS:
        ax.text(col_left[0], y, q, fontsize=7.5, va="top", color="#1f4e79", fontweight="bold")
        ax.text(col_left[1], y, widget, fontsize=7.5, va="top")
        ax.text(col_left[2], y, wtype, fontsize=7.5, va="top", color="#444")
        y -= 0.022

    y -= 0.012
    ax.text(0.05, y, "Part 1.3 — Statistical thinking",
            fontsize=11, fontweight="bold", ha="left", va="top")
    y -= 0.022
    stat_paras = STAT_TEXT.split("\n\n")
    for para in stat_paras:
        for line in textwrap.wrap(para, width=120):
            ax.text(0.05, y, line, fontsize=7.6, ha="left", va="top")
            y -= 0.013
        y -= 0.006

    footer = (
        "Part 2 coverage: 26 widgets across 3 categories (8 Performance, 10 User Behavior, 8 Cost). "
        "7 chart types: KPI, line, bar, stacked bar, area, pie, table. Source: "
        "app/chat/analytics_service.py + app/chat/chart_service.py."
    )
    fy = 0.030
    for line in textwrap.wrap(footer, width=130):
        ax.text(0.05, fy, line, fontsize=7.0, ha="left", va="bottom", color="#444")
        fy -= 0.012

    pdf.savefig(fig)
    plt.close(fig)


def _draw_page2(pdf):
    fig = plt.figure(figsize=(PAGE_W_IN, PAGE2_H_IN))

    header_ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    header_ax.set_xlim(0, 1)
    header_ax.set_ylim(0, 1)
    header_ax.axis("off")

    header_ax.text(0.05, 0.95, "Part 2.4 — Dashboard screenshots (mohitg2, 2026-04-17)",
                   fontsize=11, fontweight="bold", ha="left", va="top")
    header_ax.text(0.05, 0.91,
                   "Three tabs of the live dashboard at /chat/analytics/, captured at 1440x900 via Playwright.",
                   fontsize=8, color="#555", ha="left", va="top", style="italic")

    shots = [
        ("01_performance_tab.png", "System Performance"),
        ("02_behavior_tab.png", "User Behavior"),
        ("03_cost_tab.png", "Cost"),
    ]
    img_axes_left = [0.05, 0.37, 0.69]
    img_w = 0.28
    for left, (fname, label) in zip(img_axes_left, shots):
        path = os.path.join(SCREENSHOT_DIR, fname)
        if not os.path.exists(path):
            continue
        sub = fig.add_axes((left, 0.50, img_w, 0.36))
        sub.imshow(mpimg.imread(path))
        sub.set_xticks([])
        sub.set_yticks([])
        for spine in sub.spines.values():
            spine.set_color("#bbb")
            spine.set_linewidth(0.5)
        fig.text(left + img_w / 2, 0.475, label, fontsize=8.5,
                 ha="center", va="top", fontweight="bold")
        fig.text(left + img_w / 2, 0.452, f"docs/screenshots/analytics/{fname}",
                 fontsize=6.5, ha="center", va="top", color="#666")

    header_ax.text(0.05, 0.40, "Submission metadata", fontsize=11, fontweight="bold",
                   ha="left", va="top")
    my = 0.355
    for label, value in SUBMISSION_META:
        header_ax.text(0.05, my, label, fontsize=8, fontweight="bold", ha="left", va="top")
        header_ax.text(0.22, my, value, fontsize=8, ha="left", va="top",
                       family="monospace", color="#1f4e79")
        my -= 0.044

    pdf.savefig(fig)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output PDF path")
    args = parser.parse_args()

    out_dir = os.path.dirname(args.out)
    os.makedirs(out_dir, exist_ok=True)

    with PdfPages(args.out) as pdf:
        _draw_page1(pdf)
        _draw_page2(pdf)

    size_kb = os.path.getsize(args.out) / 1024
    print(f"Wrote {args.out} ({size_kb:.1f} KB, 2 pages, page 2 half-utilized)")


if __name__ == "__main__":
    main()
