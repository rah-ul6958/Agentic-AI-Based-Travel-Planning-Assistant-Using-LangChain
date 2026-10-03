import json

from langchain_core.tools import tool

from services.live_travel_service import CITY_AIRPORTS, NEARBY_AIRPORTS


@tool
def find_nearby_airports(city: str) -> str:
    """List a city's own airport and nearby alternative airports, with the approximate
    road distance to the city. Use it when a flight search finds no flights."""
    key = city.strip().lower()
    return json.dumps({
        "city": city,
        "main_airport": CITY_AIRPORTS.get(key, ""),
        "nearby": [{"name": name, "code": code, "distance": distance}
                   for name, code, distance in NEARBY_AIRPORTS.get(key, [])],
    }, indent=2, ensure_ascii=False)
