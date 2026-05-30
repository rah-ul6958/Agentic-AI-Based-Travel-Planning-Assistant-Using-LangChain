from datetime import date, timedelta

import requests

from config.settings import SUPPORTED_CITY_COORDS


WMO_DESCRIPTIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    51: "Light drizzle",
    61: "Light rain",
    63: "Moderate rain",
    71: "Light snow",
    80: "Rain showers",
    95: "Thunderstorm",
}

WMO_ICONS = {
    0: "☀️",
    1: "🌤️",
    2: "⛅",
    3: "☁️",
    45: "🌫️",
    51: "🌦️",
    61: "🌧️",
    63: "🌧️",
    71: "❄️",
    80: "🌦️",
    95: "⛈️",
}


def weather_icon(code: int) -> str:
    return WMO_ICONS.get(code, WMO_ICONS.get((code // 10) * 10, "🌡️"))


def weather_description(code: int) -> str:
    return WMO_DESCRIPTIONS.get(code, WMO_DESCRIPTIONS.get((code // 10) * 10, "Variable"))


def fetch_weather(city: str, days: int = 5) -> dict:
    city_key = city.strip().lower()
    if city_key not in SUPPORTED_CITY_COORDS:
        return {}

    lat, lon = SUPPORTED_CITY_COORDS[city_key]
    forecast_days = max(1, min(int(days), 7))
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
        f"&timezone=auto&forecast_days={forecast_days}"
    )
    response = requests.get(url, timeout=2.5)
    response.raise_for_status()
    return response.json()


def fallback_weather(city: str, days: int = 3) -> dict:
    forecast = []
    for index in range(max(1, min(int(days), 7))):
        travel_date = date.today() + timedelta(days=index)
        forecast.append(
            {
                "date": str(travel_date),
                "condition": "Partly cloudy",
                "max_temp_c": 32 - min(index, 4),
                "min_temp_c": 24,
                "precipitation_mm": 0.0,
            }
        )
    return {"city": city, "forecast": forecast, "note": "Live weather unavailable"}


def normalize_weather_payload(city: str, payload: dict, days: int) -> dict:
    daily = payload.get("daily", {})
    forecast = []
    max_items = min(days, len(daily.get("time", [])))

    for index in range(max_items):
        code = int(daily["weathercode"][index])
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
