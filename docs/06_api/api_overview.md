# MEMORIA API Introduction

This document provides the detailed API introduction for Section 6 of the assignment.

Related files:
- [URL routes](../../app/chat/urls.py)
- [API views](../../app/chat/api.py)
- [Service layer](../../app/chat/service.py)
- [Holiday service](../../app/chat/holiday_service.py)
- [Project README](../../README.md)

## 1. API Purpose

MEMORIA exposes read-oriented APIs so frontend pages and future external clients can access user memory and conversation data in structured JSON format.

Primary goals:
- support current UI features (for example, sidebar conversation search)
- provide filtered data retrieval via query parameters
- demonstrate both FBV and CBV implementation styles in Django
- expose public analytics data for cross-site integration and Vega-Lite charts
- integrate external API data with internal analytics through a new endpoint

## 2. Base Route Group

All endpoints are under:
- `/chat/api/`

## 3. Authentication Scope

Four endpoints are user-scoped and protected by `@login_required`. Responses only include data that belongs to the authenticated user.

Two endpoints are public (no authentication required) and return aggregated platform-wide data. These power the Vega-Lite charts and enable external consumers to access daily activity statistics.

## 4. Endpoint Overview

### 4.1 `GET /chat/api/memories/` (FBV, Auth Required)

Returns memory bullet records for the authenticated user.

Supported filters:
- `q`: keyword search in memory content
- `type`: memory type filter
- `topic`: topic keyword filter
- `strength_min`: minimum strength threshold

Example:
- `/chat/api/memories/?q=python&type=1&strength_min=40`

### 4.2 `GET /chat/api/analytics/` (FBV, Auth Required)

Returns aggregated analytics summary for the authenticated user.

Payload includes:
- total memories/sessions/messages
- memory type distribution
- average strength
- helpful/harmful totals

### 4.3 `GET /chat/api/sessions/` (CBV, Auth Required)

Returns conversation session list for the authenticated user.

Supported filter:
- `q`: title search

Example:
- `/chat/api/sessions/?q=project`

### 4.4 `GET /chat/api/sessions/<session_id>/messages/` (CBV, Auth Required)

Returns message list for a specific session owned by the authenticated user.

Supported filter:
- `role`: role-based filter (1=SYSTEM, 2=USER, 3=ASSISTANT)

Example:
- `/chat/api/sessions/12/messages/?role=2`

### 4.5 `GET /chat/api/active-users/` (FBV, Public)

Returns daily active user counts across the platform with gap-filled date ranges for continuous charting. No authentication required.

Payload structure:
```json
{
  "count": 25,
  "results": [
    {
      "date": "2026-02-01",
      "active_users": 5,
      "message_count": 23
    }
  ]
}
```

Implementation details:
- Aggregates Message records using `TruncDate("created_at")` with `Count("session__user_id", distinct=True)` for unique active users per day
- Gap-fills missing dates within the min/max range so charts display continuous time series
- Powers the Vega-Lite bar chart at `/chat/charts/active-users/`

### 4.6 `GET /chat/api/active-users/holidays/` (FBV, Public)

Enriches the daily active user data with national holiday information from the external Nager.at Holiday API. No authentication required.

Supported filter:
- `country`: ISO 3166-1 alpha-2 country code (default: "US")
- `q`: alternative parameter name for country code

Example:
- `/chat/api/active-users/holidays/?country=CA`

Success response (HTTP 200):
```json
{
  "country_code": "US",
  "country_name": "United States",
  "years_covered": [2026],
  "count": 25,
  "results": [
    {
      "date": "2026-01-01",
      "active_users": 5,
      "message_count": 23,
      "is_national_holiday": true,
      "holiday_name": "New Year's Day",
      "holiday_local_name": "New Year's Day"
    }
  ],
  "analytics": {
    "holiday_days": 11,
    "non_holiday_days": 14,
    "avg_active_users_on_holidays": 4.5,
    "avg_active_users_on_non_holidays": 8.2
  }
}
```

Error responses:
- HTTP 400: invalid country code, returns `{"error": "invalid_country_code", "requested_country_code": "ZZ", "available_regions": [...]}`
- HTTP 503: external API unavailable, returns `{"error": "holiday_api_unavailable", "message": "..."}`

## 5. Response Design

Standard API endpoints return `JsonResponse` with list/count structures for easy frontend consumption.

Public endpoints use `json_dumps_params={"indent": 2}` for human-readable output. Error responses include structured error codes and diagnostic information to help callers identify and resolve issues.

## 6. External API Integration

### 6.1 Overview

The holiday endpoint (`/chat/api/active-users/holidays/`) demonstrates external API integration by combining data from the Nager.at Holiday API with internal daily activity metrics. The external data is never stored in the database; it is fetched, merged, and returned within a single request lifecycle.

### 6.2 External API Details

**API:** Nager.at Public Holiday API
**Base URL:** `https://date.nager.at/api/v3`
**Documentation:** https://date.nager.at/swagger/index.html

Endpoints consumed:
- `GET /AvailableCountries`: returns a list of supported country codes and names
- `GET /PublicHolidays/{year}/{countryCode}`: returns public holidays for a given year and country

### 6.3 Implementation

The integration is implemented in `app/chat/holiday_service.py` as an isolated module with no Django model dependencies beyond the service layer.

Key implementation details:

1. **HTTP client** (`_fetch_json`): wraps `requests.get()` with `params={}` and `timeout=5`, calls `response.raise_for_status()` to surface HTTP errors

2. **Country validation** (`_get_available_regions`): fetches the available country list from the external API, validates the requested country code against it, and raises `InvalidHolidayCountryCodeError` with the full region list if the code is invalid

3. **Holiday fetching** (`_get_public_holidays`): retrieves holidays for each year present in the internal activity data, builds an in-memory lookup dictionary keyed by date

4. **Data triangulation** (`get_daily_activity_with_holidays_payload`): calls `get_api_daily_active_users_payload()` to retrieve internal daily activity data, then merges it with the holiday lookup to enrich each day with `is_national_holiday`, `holiday_name`, and `holiday_local_name` fields

5. **Analytics processing**: accumulates holiday and non-holiday day counts and active user sums, then computes comparative averages (rounded to 2 decimal places)

### 6.4 Error Handling

Two custom exception classes provide granular error differentiation:

- `InvalidHolidayCountryCodeError`: raised when the requested country code is not found in the available regions. Carries `country_code` and `available_regions` attributes for the API view to include in the 400 response.

- `HolidayAPIUnavailableError`: raised when the external API request fails (network timeout, connection error, non-2xx status). The API view returns a 503 response.

Both exception types catch `requests.RequestException` (the base class for all requests library exceptions) and re-raise as the appropriate custom exception using `from exc` for exception chaining.

### 6.5 Data Flow

```
Client request
  -> api.py: extract ?country= parameter
  -> holiday_service.py: validate country code against external API
  -> service.py: query internal Message model for daily active user counts
  -> holiday_service.py: fetch holidays from external API for relevant years
  -> holiday_service.py: merge holiday data with internal data (in memory)
  -> holiday_service.py: compute comparative analytics
  -> api.py: return JsonResponse
```
