import json

from langchain_core.tools import tool

from services.live_travel_service import (
    LiveDataError,
    NoResultsError,
    default_travel_date,
    fetch_live_hotels,
    live_data_enabled,
)
from tools.data_access import load_json_dataset
from utils.trip_math import guests_per_room, rooms_needed


def _normalize_hotel(hotel: dict, nights: int) -> dict:
    """Normalize hotel record — handles both 'rating' and 'stars' field names."""
    # Data uses 'stars', but keep backward compat with 'rating' too
    stars = hotel.get("stars") or hotel.get("rating")
    price = float(hotel.get("price_per_night", 0))
    return {
        "hotel_id": hotel.get("hotel_id", ""),
        "name": hotel.get("name", "Unknown hotel"),
        "city": hotel.get("city", ""),
        "stars": int(stars) if stars else None,
        "guest_rating": None,  # the sample data has no guest reviews
        "price_per_night": price,
        "stay_price": price * nights,
        "nights": nights,
        "price_note": "",
        "type": hotel.get("type", "Hotel"),
        "amenities": hotel.get("amenities", []),
        "data_source": "sample",
    }


def _matches_budget(hotel: dict, max_price: float, min_stars: float) -> bool:
    if hotel["price_per_night"] > max_price:
        return False
    # Use the star class when we know it; otherwise filter by price only.
    if hotel["stars"] is None:
        return True
    return hotel["stars"] >= min_stars


def _summarize(city_hotels: list[dict], max_price: float, min_stars: float, **extra) -> str:
    results = [h for h in city_hotels if _matches_budget(h, max_price, min_stars)]
    relaxed = not results
    if relaxed:
        # Nothing matches the budget profile: fall back to all hotels, cheapest first
        results = city_hotels

    cheapest = min(results, key=lambda h: h["price_per_night"])
    recommended = cheapest if relaxed else max(
        results, key=lambda h: (h["stars"] or 0, h["guest_rating"] or 0, -h["price_per_night"])
    )
    best_value = min(results, key=lambda h: h["price_per_night"] / max(h["stars"] or 1, 1))

    return json.dumps({
        "found": True,
        **extra,
        "recommended": recommended,
        "cheapest": cheapest,
        "best_value": best_value,
        "relaxed_filters": relaxed,
        "all_options": sorted(results, key=lambda h: (-(h["stars"] or 0), h["price_per_night"]))[:8],
    }, indent=2, ensure_ascii=False)


@tool
def search_hotels(city: str, max_price: int = 10000, min_stars: int = 3,
                  check_in: str = "", nights: int = 2, travellers: int = 1,
                  strict_max_price: bool = False) -> str:
    """Search hotels in a city for `nights` nights from check_in (YYYY-MM-DD).
    max_price is the price per room per night; min_stars is the hotel star class
    (hotels without a known star class are filtered by price only).
    strict_max_price=True also asks Google Hotels itself for hotels under max_price
    (one extra live search) - use it when the chosen hotel is over budget.
    Uses real-time Google Hotels prices when SERPAPI_API_KEY is set, otherwise the
    sample dataset. Prices are per room; the result says how many rooms are needed.
    Returns recommended (best rated), cheapest, and all matching options."""
    nights = max(int(nights), 1)
    rooms = {"rooms": rooms_needed(travellers), "guests_per_room": guests_per_room(travellers)}
    live_error = ""
    if live_data_enabled():
        try:
            live = fetch_live_hotels(city, check_in or default_travel_date(), nights,
                                     adults=rooms["guests_per_room"],
                                     max_price=max_price if strict_max_price else None)
            return _summarize(live["hotels"], max_price, min_stars, data_source="live",
                              fetched_at=live["fetched_at"], from_cache=live["from_cache"], **rooms)
        except NoResultsError as exc:
            # Google answered that nothing matches: report it, never show sample hotels
            return json.dumps({"found": False, "data_source": "live", "message": str(exc), **rooms},
                              indent=2, ensure_ascii=False)
        except LiveDataError as exc:
            live_error = str(exc)

    try:
        raw_hotels = load_json_dataset("hotels.json")
        hotels = [_normalize_hotel(h, nights) for h in raw_hotels]

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

        return _summarize(city_hotels, max_price, min_stars, data_source="sample",
                          live_error=live_error, **rooms)

    except Exception as exc:
        return json.dumps({"error": f"Hotel search failed: {exc}"})
