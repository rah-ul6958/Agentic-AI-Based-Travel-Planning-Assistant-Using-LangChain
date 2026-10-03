import json

from langchain_core.tools import tool

from services.live_travel_service import (
    LiveDataError,
    default_travel_date,
    fetch_live_hotels,
    live_data_enabled,
)
from tools.data_access import load_json_dataset


def _normalize_hotel(hotel: dict) -> dict:
    """Normalize hotel record — handles both 'rating' and 'stars' field names."""
    # Data uses 'stars', but keep backward compat with 'rating' too
    stars = hotel.get("stars") or hotel.get("rating") or 3.0
    return {
        "hotel_id": hotel.get("hotel_id", ""),
        "name": hotel.get("name", "Unknown hotel"),
        "city": hotel.get("city", ""),
        "rating": float(stars),
        "stars": float(stars),
        "price_per_night": float(hotel.get("price_per_night", 0)),
        "type": hotel.get("type", "Hotel"),
        "amenities": hotel.get("amenities", []),
        "data_source": "sample",
    }


def _summarize(city_hotels: list[dict], max_price: float, min_rating: float, **extra) -> str:
    results = [
        h for h in city_hotels
        if h["price_per_night"] <= max_price and h["rating"] >= min_rating
    ]
    relaxed = not results
    if relaxed:
        # Nothing matches the budget profile: fall back to all hotels, cheapest first
        results = city_hotels

    cheapest = min(results, key=lambda h: h["price_per_night"])
    recommended = cheapest if relaxed else max(
        results, key=lambda h: (h["rating"], h.get("guest_rating") or 0, -h["price_per_night"])
    )
    best_value = min(results, key=lambda h: h["price_per_night"] / max(h["rating"], 1))

    return json.dumps({
        "found": True,
        **extra,
        "recommended": recommended,
        "cheapest": cheapest,
        "best_value": best_value,
        "relaxed_filters": relaxed,
        "all_options": sorted(results, key=lambda h: (-h["rating"], h["price_per_night"]))[:8],
    }, indent=2, ensure_ascii=False)


@tool
def search_hotels(city: str, max_price: int = 10000, min_rating: float = 3.0,
                  check_in: str = "", nights: int = 2) -> str:
    """Search hotels in a city. Filters by max price per night and minimum star rating.
    Uses real-time Google Hotels prices for check_in (YYYY-MM-DD) when SERPAPI_API_KEY
    is set, otherwise the sample dataset.
    Returns recommended (best rated), cheapest, and all matching options."""
    live_error = ""
    if live_data_enabled():
        try:
            live = fetch_live_hotels(city, check_in or default_travel_date(), nights)
            return _summarize(live, max_price, min_rating, data_source="live")
        except LiveDataError as exc:
            live_error = str(exc)

    try:
        raw_hotels = load_json_dataset("hotels.json")
        hotels = [_normalize_hotel(h) for h in raw_hotels]

        city_hotels = [h for h in hotels if h["city"].strip().lower() == city.strip().lower()]

        if not city_hotels:
            available_cities = sorted({h["city"] for h in hotels})
            return json.dumps({
                "found": False,
                "data_source": "sample",
                "live_error": live_error,
                "message": f"No hotels found in {city}.",
                "available_cities": available_cities,
            }, indent=2, ensure_ascii=False)

        return _summarize(city_hotels, max_price, min_rating, data_source="sample", live_error=live_error)

    except Exception as exc:
        return json.dumps({"error": f"Hotel search failed: {exc}"})
