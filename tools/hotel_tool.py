import json

from langchain.tools import tool

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
    }


@tool
def search_hotels(city: str, max_price: int = 10000, min_rating: float = 3.0) -> str:
    """Search hotels in a city. Filters by max price per night and minimum star rating.
    Returns recommended (best rated), cheapest, and all matching options."""
    try:
        raw_hotels = load_json_dataset("hotels.json")
        hotels = [_normalize_hotel(h) for h in raw_hotels]

        city_hotels = [h for h in hotels if h["city"].strip().lower() == city.strip().lower()]

        if not city_hotels:
            available_cities = sorted({h["city"] for h in hotels})
            return json.dumps({
                "found": False,
                "message": f"No hotels found in {city}.",
                "available_cities": available_cities,
            }, indent=2)

        results = [
            h for h in city_hotels
            if h["price_per_night"] <= max_price and h["rating"] >= min_rating
        ]

        relaxed = False
        if not results:
            # Relax filters and return all city hotels
            results = city_hotels
            relaxed = True

        # Best value: highest stars per rupee
        recommended = max(results, key=lambda h: (h["rating"], -h["price_per_night"]))
        cheapest = min(results, key=lambda h: h["price_per_night"])
        best_value = min(results, key=lambda h: h["price_per_night"] / max(h["rating"], 1))

        return json.dumps({
            "found": True,
            "recommended": recommended,
            "cheapest": cheapest,
            "best_value": best_value,
            "relaxed_filters": relaxed,
            "all_options": sorted(results, key=lambda h: (-h["rating"], h["price_per_night"])),
        }, indent=2)

    except Exception as exc:
        return json.dumps({"error": f"Hotel search failed: {exc}"})