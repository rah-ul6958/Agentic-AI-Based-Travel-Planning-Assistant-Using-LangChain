import json

from langchain.tools import tool

from services.weather_service import fallback_weather, fetch_weather, normalize_weather_payload


@tool
def get_weather(city: str, days: int = 3) -> str:
    """Get weather forecast for a city for the given number of days."""
    try:
        payload = fetch_weather(city, days)
        if not payload:
            return json.dumps(fallback_weather(city, days), indent=2)
        return json.dumps(normalize_weather_payload(city, payload, days), indent=2)
    except Exception:
        return json.dumps(fallback_weather(city, days), indent=2)
