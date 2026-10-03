import json
import logging

from langchain_core.tools import tool

from services.weather_service import fallback_weather, fetch_weather, normalize_weather_payload

logger = logging.getLogger(__name__)


@tool
def get_weather(city: str, days: int = 3, start_date: str = "") -> str:
    """Get the weather forecast for a city for the given number of days from start_date (YYYY-MM-DD)."""
    try:
        payload = fetch_weather(city, days, start_date)
        if payload:
            data = normalize_weather_payload(city, payload, days)
            found = len(data["forecast"])
            data["available"] = found > 0
            if 0 < found < days:
                data["message"] = (f"Forecast available for the first {found} of {days} days; "
                                   "the remaining days are too far ahead to forecast.")
            if found:
                return json.dumps(data, indent=2)
    except Exception as exc:
        logger.warning("Open-Meteo forecast request failed: %s", type(exc).__name__)
    return json.dumps(fallback_weather(city, days, start_date), indent=2)
