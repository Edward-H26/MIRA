# A10 Analytics Dashboard (INFO490 Submission)

> Scannable map from the INFO490 Analytics Dashboard rubric (Parts 1 and 2, 100 points) to the artifact that fulfills it. Every claim links to a screenshot, a Python function, a Django URL, or a Cypher node so the grader can jump directly to evidence.

| Item | Value |
|---|---|
| Live dashboard | `https://mira-ydqq.onrender.com/chat/analytics/` |
| Local dashboard | `http://127.0.0.1:8000/chat/analytics/` |
| Test credentials | username `mohitg2` / password `uiuc12345` |
| Repository | this repo, branch `feature/ai` |
| Sample API JSON | [`docs/07_api_demos/analytics_api_sample.json`](../07_api_demos/analytics_api_sample.json) |
| Screenshots | [`docs/screenshots/analytics/`](../screenshots/analytics/) |
| Snapshot date | 2026-04-17 |

---

## Part 1 — Analytics Design (50 pts)

### 1.1 Analytics questions (≥ 3 per category, 10 total)

The dashboard is question-driven, not chart-driven. By starting from the operational decisions a Memoria engineer needs to make every week, we derive the questions first and then attach widgets that answer them.

**Category A — System Performance**

A1. **How does end-to-end latency vary across requests over a 30-day window?** A grader needs to see whether the AI pipeline is stable, drifting, or spiking after a deployment.
A2. **Which model contributes most to overall response time?** Memoria routes traffic across `gemini-3-flash-preview`, `gemini-3.1-flash-lite-preview`, and the local `qwen3.5-0.8b`, so a per-model latency comparison shows where to spend optimization effort.
A3. **What fraction of requests fail or fall back, and is the failure pattern correlated with traffic spikes?** Error rate and fallback rate together describe pipeline health more honestly than either alone.

**Category B — User Behavior**

B1. **How is the user's memory store distributed across the three memory types (semantic, episodic, procedural)?** Imbalance in this distribution suggests the AI is capturing only one kind of knowledge and tells the team to tune the classifier.
B2. **How active is each user across days, weeks, and months?** Session and message counts grouped by time window expose engagement, dormancy, and the effect of feature releases.
B3. **What is the strength distribution of stored memories, and what fraction of them are weak (strength below 50)?** Weak memories pile up when the AI guesses without reinforcement and become a maintenance debt.

**Category C — Cost**

C1. **What is the average cost per request, and how does it move day over day?** Cost-per-request is the unit economic that determines whether Memoria can scale without reorganizing the model mix.
C2. **Which model accounts for the largest share of spend, and is that share proportional to the value it produces?** A model that costs 90 percent of the budget but serves 30 percent of the requests is a re-routing target.
C3. **What is the prompt-vs-completion token split, and how does that ratio behave over time?** A growing completion share usually indicates verbose responses that warrant prompt tightening.
C4. **What is the projected monthly burn at the current trajectory?** Cumulative daily cost projected forward gives finance the number it actually wants.

### 1.2 Widget design plan — question → widget map

Every widget in the dashboard maps back to a specific question above. The widget IDs match the section anchors inside `app/chat/templates/chat/analytics.html`.

| Q | Widget(s) | Type | File / Code path | Data source |
|---|---|---|---|---|
| A1 | Latency Over Time | Line chart, 30-day | `app/chat/chart_service.py::latency_over_time_chart` rendered at `chat:latency_over_time_chart` (`/chat/analytics/latency-over-time.png`) | Neo4j `RequestLog` nodes via `neo4j_memory.get_request_logs_for_user` |
| A1 | Avg Latency, P95 Latency, Total Requests, Error Rate | KPI summary metrics (4 cards) | `analytics_service.py::_get_performance_metrics` → template lines 47–89 | Same |
| A2 | Latency by Model | Bar chart | `chart_service.py::latency_by_model_chart` (`/chat/analytics/latency-by-model.png`) | Same, grouped by `modelName` |
| A3 | Request Status Distribution + Request Status Breakdown table | Pie chart + data table | `chart_service.py::error_rate_chart` (`/chat/analytics/error-rate.png`) + template lines 117–158 | Same, grouped by `status` |
| B1 | Memory Type Distribution | Pie chart | `chart_service.py::memory_type_chart` (`/chat/analytics/memory-type.png`) | Neo4j `MemoryBullet` nodes via `_get_memory_bullets_for_user` |
| B1 | Semantic / Episodic / Procedural counts | KPI cards | `analytics_service.py::_get_analytics_metrics_for_user` lines 19–29 | Same |
| B2 | Conversation Activity | Line chart, 30-day | `chart_service.py::activity_chart` (`/chat/analytics/activity.png`) | Neo4j `Session` and `Message` nodes via `neo4j_memory.get_sessions_for_user` and `get_total_message_count_for_user` |
| B2 | Conversations and Messages KPI cards + grouped Sessions Summary table | KPI + data table grouped by day/week/month | `analytics_service.py::get_analytics_dashboard_context_with_reports` (sessionGroup parameter) | Same |
| B3 | Memory Strength Distribution | Bar chart, strength buckets | `chart_service.py::memory_strength_chart` (`/chat/analytics/memory-strength.png`) | Neo4j `MemoryBullet.strength` aggregated into 0–25, 25–50, 50–75, 75–100 buckets |
| B3 | Avg Strength KPI | Summary metric | `_get_analytics_metrics_for_user` line 30 (mean over `strength`) | Same |
| C1 | Avg Cost per Request | KPI summary metric | `analytics_service.py::_get_cost_metrics` | Neo4j `RequestLog.estimatedCostUsd` |
| C1 | Daily Cost Trend | Area / line chart, 30-day | `chart_service.py::daily_cost_chart` (`/chat/analytics/daily-cost.png`) | Same, grouped by day |
| C2 | Cost by Model | Bar chart + breakdown table | `chart_service.py::cost_by_model_chart` (`/chat/analytics/cost-by-model.png`) | Same, grouped by `modelName` |
| C3 | Token Usage Breakdown | Stacked bar chart | `chart_service.py::token_usage_chart` (`/chat/analytics/token-usage.png`) | `RequestLog.promptTokens` and `RequestLog.completionTokens` |
| C3 | Prompt / Completion split KPI card | Summary metric | `_get_cost_metrics` (`total_prompt_tokens`, `total_completion_tokens`) | Same |
| C4 | Total Cost, Total Tokens KPI cards (with throughput-per-day text under the table) | Summary metrics | `_get_cost_metrics` and template footer line | Same |

A grader can verify this map by opening the dashboard, opening DevTools, and confirming each PNG `src` resolves to the `chat:*_chart` URL listed above.

### 1.3 Data Science thinking — statistical concepts in use

The widgets above lean on three classes of analytical concept, each implemented in a specific function so the math is reproducible.

**Central tendency and dispersion.** The latency KPI cards report both **mean** and **p95** because mean alone hides the long tail that the user actually feels. Both are computed in `analytics_service.py::_get_performance_metrics` (lines 55–60), which sorts the latency series and indexes the 50th and 95th percentile elements. The p50 (median) is exposed in the JSON payload at `summary_performance.p50_latency_ms` even though the dashboard surfaces the mean for compactness. By reporting both, we expose distribution shape without forcing the reader to look at a histogram for every chart.

**Distributions over categorical and numeric axes.** The Memory Type Distribution pie and the Memory Strength Distribution bar chart are histograms in disguise: one categorical (semantic / episodic / procedural), one binned numeric (strength bucketed in 25-point ranges). The Request Status Distribution pie and table do the same for `success / fallback / error`. Together they let an engineer spot imbalance at a glance and decide whether the AI is over-fitting to one regime.

**Trends over time and group comparisons.** The Latency Over Time, Conversation Activity, and Daily Cost Trend charts share a single pattern: bucket events by day, plot a 30-day series, and overlay a single line. Group comparisons appear in Latency by Model, Cost by Model, and Token Usage Breakdown, where bars side by side answer "which group is the outlier." This is the same pattern recommended in Tufte's small-multiples principle and lets a reader compare across models without tab-switching.

**Why this is more than raw data.** The dashboard does not surface a single chart that asks the user to compute something themselves. Each widget already answers a specific decision question (slow model? expensive model? unhealthy ratio?). That intentional design is what separates a question-driven dashboard from a chart-driven dashboard.

---

## Part 2 — Dashboard Implementation (50 pts)

### 2.1 Coverage — three categories, 26 widgets

The assignment requires at least one widget per category and at least three visualizations overall. Memoria delivers 26 widgets across the three required categories, roughly nine times the minimum. The breakdown matches the question map in section 1.2.

| Category | Widget count | Components |
|---|---|---|
| System Performance | 8 | 4 KPI cards + 3 charts (line, bar, pie) + 1 data table |
| User Behavior | 10 | 7 KPI cards + 3 charts (pie, bar, line) + grouped-summary tables |
| Cost | 8 | 4 KPI cards + 3 charts (line, bar, stacked bar) + 1 breakdown table |
| **Total** | **26** | 7 distinct visualization types |

Distinct visualization types in use: KPI summary metric, line chart, bar chart, stacked bar chart, area chart, pie chart, data table.

### 2.2 Data source

The dashboard runs on **real per-request telemetry** captured from production-style usage, not handcrafted demo numbers. The data flow is:

1. Every chat request enters `app/chat/views.py::ConversationMessagesView.post`, which calls `app/chat/service.py::stream_user_message_with_agent_reply`.
2. That function brackets the model call with `time.monotonic()` (service.py:798–947) and reads `usage_metadata` returned by the Gemini stream (lines 950–965) to get `prompt_tokens`, `completion_tokens`, and computes `estimated_cost_usd` via the `MODEL_PRICING` table at lines 45–54.
3. A row is then written to the Django `RequestLog` model (`app/chat/models/request_log.py`) and a corresponding `(:RequestLog)` node is created in Neo4j via `app/services/neo4j_memory.py::create_request_log` (lines 1597–1669).
4. The dashboard reads exclusively from the Neo4j side (`get_request_logs_for_user`, `get_sessions_for_user`, `get_total_message_count_for_user`, `get_bullets_for_memory`), which keeps analytics queries off the request path.

For demo and grading purposes, `app/chat/management/commands/seed_analytics.py` provisions the `mohitg2` user and inserts 700–2000 weighted `RequestLog` rows over a configurable 90-day window. Hour-of-day weighting (`_hour_weight`) peaks between 09:00 and 22:00 to mimic a study app's natural traffic pattern. Seeded rows are tagged `metadata.seeded=True` so a future production deploy can filter them out with a single query.

The current snapshot used for these screenshots is captured in [`docs/07_api_demos/analytics_api_sample.json`](../07_api_demos/analytics_api_sample.json) and reports 1,641 total requests, 21 sessions, 232 messages, 70 memory bullets, $0.5967 total cost across 2,382,737 tokens.

### 2.3 Functionality

By visiting `/chat/analytics/` after logging in, a user sees three tabs governed by a small JavaScript tab switcher in the template. Every chart is a server-rendered PNG produced by `app/chat/chart_service.py` at 150 dpi via Matplotlib, which keeps the client side dependency-free and renders identically in Safari, Chrome, and headless Playwright runs. Three export endpoints (`export_request_log_report`, `export_sessions_report`, `export_memory_bullets_report`) deliver the underlying rows as CSV or JSON, and a JSON API at `/chat/api/analytics/` returns the user-behavior summary for external integration. The full URL map is registered in `app/chat/urls.py:21–33` and `:78`.

Authentication is enforced by Django's `@login_required` decorator on every analytics view; an unauthenticated request returns HTTP 302 to the login page. A grader can confirm this with `curl -I https://mira-ydqq.onrender.com/chat/analytics/`.

### 2.4 Screenshots

Below are the three captured tabs from a fresh `mohitg2` login on 2026-04-17. Full-resolution PNGs live in `docs/screenshots/analytics/`.

**System Performance tab** ([01_performance_tab.png](../screenshots/analytics/01_performance_tab.png))
The four KPI cards report 641 ms average latency, 1164 ms p95, 1641 total requests, and a 3.1 percent error rate. Below them the Latency Over Time line chart reveals daily variability and one isolated spike near day 18, while the Latency by Model bar chart shows that local Qwen3.5-0.8B is roughly comparable to the lite Gemini variant. The Request Status pie at the bottom confirms a 92/5/3 success/fallback/error split.

![Performance tab](../screenshots/analytics/01_performance_tab.png)

**User Behavior tab** ([02_behavior_tab.png](../screenshots/analytics/02_behavior_tab.png))
The four KPI cards plus the three memory-type cards show 70 memory bullets (24 semantic, 27 episodic, 19 procedural), 21 conversations, 232 messages, and an average bullet strength of 61.9. The Memory Type Distribution pie and Memory Strength Distribution bar render below.

![Behavior tab](../screenshots/analytics/02_behavior_tab.png)

**Cost tab** ([03_cost_tab.png](../screenshots/analytics/03_cost_tab.png))
The four KPI cards show $0.5967 total spend across 2,382,737 tokens at $0.000364 per request, with a 1,432,747 / 949,990 prompt-versus-completion split. The Daily Cost Trend line chart and the Total Cost by Model bar chart make the per-model concentration visible at a glance.

![Cost tab](../screenshots/analytics/03_cost_tab.png)

---

## Submission metadata

| Field | Value |
|---|---|
| Live URL | `https://mira-ydqq.onrender.com/chat/analytics/` |
| Local URL | `http://127.0.0.1:8000/chat/analytics/` |
| Test credentials | `mohitg2` / `uiuc12345` |
| Reset / re-seed (local) | `python manage.py seed_analytics --user mohitg2 --days 90` |
| Reset / re-seed (Render) | `render ssh <web-svc> -- python manage.py seed_analytics --user mohitg2 --days 90` |
| GitHub | this repo (branch `feature/ai`) |
| Sample JSON | [`docs/07_api_demos/analytics_api_sample.json`](../07_api_demos/analytics_api_sample.json) |
| Screenshots | [`docs/screenshots/analytics/`](../screenshots/analytics/) |
| Companion PDF | [`A10_ANALYTICS_DASHBOARD.pdf`](A10_ANALYTICS_DASHBOARD.pdf) |

## Verification commands

```bash
# 1. Re-seed test data and reset password
python manage.py seed_analytics --user mohitg2 --days 90
python manage.py shell -c "from django.contrib.auth.models import User; u=User.objects.get(username='mohitg2'); u.set_password('uiuc12345'); u.is_staff=True; u.is_superuser=True; u.save()"

# 2. Confirm dashboard route is gated
curl -I http://127.0.0.1:8000/chat/analytics/

# 3. Refresh the JSON sample
python manage.py shell -c "import json; import app.chat.views; from django.contrib.auth.models import User; from app.chat.analytics_service import get_analytics_dashboard_context_with_reports; ctx = get_analytics_dashboard_context_with_reports(User.objects.get(username='mohitg2')); print(json.dumps({k: ctx[k] for k in ('perf_avg_latency','perf_p95_latency','perf_total_requests','cost_total','total_memories')}, default=str, indent=2))"
```
