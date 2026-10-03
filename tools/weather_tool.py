import json

from langchain_core.tools import tool

from services.weather_service import fallback_weather, fetch_weather, normalize_weather_payload


@tool
def get_weather(city: str, days: int = 3, start_date: str = "") -> str:
    """Get the weather forecast for a city for the given number of days from start_date (YYYY-MM-DD)."""
    try:
        payload = fetch_weather(city, days, start_date)
        if payload:
            return json.dumps(normalize_weather_payload(city, payload, days), indent=2)
    except Exception:
        pass
    return json.dumps(fallback_weather(city, days, start_date), indent=2)
