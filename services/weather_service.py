from datetime import date, timedelta

import requests

from config.settings import SUPPORTED_CITY_COORDS


# Full WMO weather interpretation table used by Open-Meteo.
WMO_CODES = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Foggy", "🌫️"),
    48: ("Rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Drizzle", "🌦️"),
    55: ("Dense drizzle", "🌧️"),
    56: ("Freezing drizzle", "🌧️"),
    57: ("Freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"),
    67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"),
    73: ("Snow", "🌨️"),
    75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "🌨️"),
    80: ("Rain showers", "🌦️"),
    81: ("Rain showers", "🌧️"),
    82: ("Violent showers", "⛈️"),
    85: ("Snow showers", "🌨️"),
    86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm, hail", "⛈️"),
    99: ("Thunderstorm, hail", "⛈️"),
}


def weather_icon(code: int) -> str:
    return WMO_CODES.get(code, ("", "🌡️"))[1]


def weather_description(code: int) -> str:
    return WMO_CODES.get(code, ("Variable", ""))[0]


MAX_FORECAST_DAYS = 16  # Open-Meteo forecast horizon


def last_forecast_date() -> date:
    """The furthest day Open-Meteo can forecast (today counts as day 1)."""
    return date.today() + timedelta(days=MAX_FORECAST_DAYS - 1)


def forecast_available(start_date: str = "") -> bool:
    start = date.fromisoformat(start_date) if start_date else date.today()
    return start <= last_forecast_date()


def fetch_weather(city: str, days: int = 5, start_date: str = "") -> dict:
    city_key = city.strip().lower()
    if city_key not in SUPPORTED_CITY_COORDS:
        return {}

    lat, lon = SUPPORTED_CITY_COORDS[city_key]
    days = max(1, min(int(days), 7))
    start = date.fromisoformat(start_date) if start_date else date.today()
    start = max(start, date.today())
    end = start + timedelta(days=days - 1)
    if start > last_forecast_date():
        return {}  # beyond the forecast horizon
    # If only part of the trip is within range, fetch the days we can forecast.
    end = min(end, last_forecast_date())

    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
            "timezone": "auto",
            "start_date": str(start),
            "end_date": str(end),
        },
        timeout=4,
    )
    response.raise_for_status()
    return response.json()


def fallback_weather(city: str, days: int = 3, start_date: str = "") -> dict:
    """Used when there is no real forecast. It never invents weather data."""
    if not forecast_available(start_date):
        check_from = date.fromisoformat(start_date) - timedelta(days=MAX_FORECAST_DAYS - 1)
        message = (f"Forecast not available yet. Forecasts cover about {MAX_FORECAST_DAYS} days ahead, "
                   f"so check again from {check_from.strftime('%d %b %Y')}.")
    else:
        message = "Weather forecast is unavailable right now. Please check again later."
    return {"city": city, "forecast": [], "available": False, "message": message}


def normalize_weather_payload(city: str, payload: dict, days: int) -> dict:
    daily = payload.get("daily", {})
    forecast = []
    max_items = min(days, len(daily.get("time", [])))

    for index in range(max_items):
        code = int(daily["weathercode"][index] or 0)
        forecast.append(
            {
                "date": daily["time"][index],
                "condition": weather_description(code),
                "icon": weather_icon(code),
                "max_temp_c": daily["temperature_2m_max"][index],
                "min_temp_c": daily["temperature_2m_min"][index],
                "precipitation_mm": daily["precipitation_sum"][index],
            }
        )

    return {"city": city, "forecast": forecast}
