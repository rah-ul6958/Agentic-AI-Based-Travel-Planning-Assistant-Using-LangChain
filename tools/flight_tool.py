import json

from langchain.tools import tool

from tools.data_access import load_json_dataset
from utils.formatting import format_time, parse_iso_duration_hours


def _normalize_flight(flight: dict) -> dict:
    """Normalize flight record — handles both 'from/to' and 'source/destination' schemas."""
    source = flight.get("from") or flight.get("source", "")
    destination = flight.get("to") or flight.get("destination", "")
    departure = flight.get("departure_time", "")
    arrival = flight.get("arrival_time", "")
    duration = flight.get("duration_hrs") or parse_iso_duration_hours(departure, arrival)

    return {
        "flight_id": flight.get("flight_id", ""),
        "airline": flight.get("airline", "Unknown airline"),
        "source": source,
        "destination": destination,
        "departure_time": departure,
        "arrival_time": arrival,
        "departure_display": format_time(departure),
        "arrival_display": format_time(arrival),
        "duration_hrs": round(duration, 1),
        "price": float(flight.get("price", 0)),
    }


@tool
def search_flights(source: str, destination: str) -> str:
    """Search available flights from source city to destination city.
    Returns cheapest option, fastest option, and all available flights."""
    try:
        raw_flights = load_json_dataset("flights.json")
        flights = [_normalize_flight(f) for f in raw_flights]

        results = [
            f for f in flights
            if f["source"].strip().lower() == source.strip().lower()
            and f["destination"].strip().lower() == destination.strip().lower()
        ]

        if not results:
            available_routes = sorted({
                f'{f["source"]} → {f["destination"]}' for f in flights
            })
            return json.dumps({
                "found": False,
                "message": f"No direct flights found from {source} to {destination}.",
                "tip": f"Try reversing the route or check available_routes.",
                "available_routes": available_routes,
            }, indent=2)

        cheapest = min(results, key=lambda f: f["price"])
        fastest = min(results, key=lambda f: f["duration_hrs"])
        best_value = min(
            results,
            key=lambda f: f["price"] / max(f["duration_hrs"], 0.5)
        )

        return json.dumps({
            "found": True,
            "cheapest_flight": cheapest,
            "fastest_flight": fastest,
            "best_value_flight": best_value,
            "all_options_count": len(results),
            "all_options": sorted(results, key=lambda f: f["price"]),
        }, indent=2)

    except Exception as exc:
        return json.dumps({"error": f"Flight search failed: {exc}"})