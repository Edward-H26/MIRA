import requests

from .service import get_api_daily_active_users_payload

HOLIDAY_API_BASE = "https://date.nager.at/api/v3"


class InvalidHolidayCountryCodeError(Exception):
    def __init__(self, country_code, available_regions):
        super().__init__(f"Invalid country code: {country_code}")
        self.country_code = country_code
        self.available_regions = available_regions


class HolidayAPIUnavailableError(Exception):
    pass


def _fetch_json(url, params=None):
    response = requests.get(url, params=params or {}, timeout=5)
    response.raise_for_status()
    return response.json()


def _get_available_regions():
    try:
        payload = _fetch_json(f"{HOLIDAY_API_BASE}/AvailableCountries", params={})
    except requests.RequestException as exc:
        raise HolidayAPIUnavailableError("Failed to fetch available regions.") from exc

    if not isinstance(payload, list):
        raise HolidayAPIUnavailableError("Holiday API returned unexpected region data.")

    regions = []
    for item in payload:
        country_code = (item.get("countryCode") or "").strip().upper()
        name = (item.get("name") or "").strip()
        if country_code and name:
            regions.append({"countryCode": country_code, "name": name})
    return regions


def _get_public_holidays(country_code, year):
    try:
        payload = _fetch_json(
            f"{HOLIDAY_API_BASE}/PublicHolidays/{year}/{country_code}",
            params={},
        )
    except requests.RequestException as exc:
        raise HolidayAPIUnavailableError("Failed to fetch public holiday data.") from exc

    if not isinstance(payload, list):
        raise HolidayAPIUnavailableError("Holiday API returned unexpected holiday data.")
    return payload


def get_daily_activity_with_holidays_payload(country_code="US"):
    normalized_country = (country_code or "US").strip().upper() or "US"
    available_regions = _get_available_regions()
    available_codes = {item["countryCode"] for item in available_regions}
    region_name_by_code = {
        item["countryCode"]: item["name"]
        for item in available_regions
    }

    if normalized_country not in available_codes:
        raise InvalidHolidayCountryCodeError(
            normalized_country,
            available_regions,
        )

    daily_payload = get_api_daily_active_users_payload()
    daily_results = list(daily_payload.get("results", []))

    years_to_fetch = sorted({int(row["date"][:4]) for row in daily_results})
    if not years_to_fetch:
        return {
            "country_code": normalized_country,
            "country_name": region_name_by_code.get(normalized_country),
            "years_covered": [],
            "count": 0,
            "results": [],
            "analytics": {
                "holiday_days": 0,
                "non_holiday_days": 0,
                "avg_active_users_on_holidays": None,
                "avg_active_users_on_non_holidays": None,
            },
        }

    holiday_by_date = {}
    for target_year in years_to_fetch:
        holidays = _get_public_holidays(normalized_country, target_year)
        for holiday in holidays:
            holiday_date = holiday.get("date")
            if not holiday_date:
                continue
            holiday_by_date[holiday_date] = {
                "name": holiday.get("name"),
                "local_name": holiday.get("localName"),
            }

    merged_results = []
    holiday_days = 0
    non_holiday_days = 0
    holiday_active_sum = 0
    non_holiday_active_sum = 0

    for row in daily_results:
        holiday = holiday_by_date.get(row["date"])
        is_holiday = holiday is not None
        active_users = row["active_users"]
        if is_holiday:
            holiday_days += 1
            holiday_active_sum += active_users
        else:
            non_holiday_days += 1
            non_holiday_active_sum += active_users

        merged_results.append(
            {
                "date": row["date"],
                "active_users": active_users,
                "message_count": row["message_count"],
                "is_national_holiday": is_holiday,
                "holiday_name": holiday["name"] if holiday else None,
                "holiday_local_name": holiday["local_name"] if holiday else None,
            }
        )

    holiday_avg = (
        round(holiday_active_sum / holiday_days, 2)
        if holiday_days else None
    )
    non_holiday_avg = (
        round(non_holiday_active_sum / non_holiday_days, 2)
        if non_holiday_days else None
    )

    return {
        "country_code": normalized_country,
        "country_name": region_name_by_code.get(normalized_country),
        "years_covered": years_to_fetch,
        "count": len(merged_results),
        "results": merged_results,
        "analytics": {
            "holiday_days": holiday_days,
            "non_holiday_days": non_holiday_days,
            "avg_active_users_on_holidays": holiday_avg,
            "avg_active_users_on_non_holidays": non_holiday_avg,
        },
    }
