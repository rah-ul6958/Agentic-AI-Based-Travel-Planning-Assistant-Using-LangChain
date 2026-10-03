import json
from datetime import datetime

from langchain_core.tools import tool

from services.live_travel_service import (
    LiveDataError,
    default_travel_date,
    fetch_live_flights,
    live_data_enabled,
)
from tools.data_access import load_json_dataset
from utils.formatting import format_time, parse_iso_duration_hours

MIN_LAYOVER_MINUTES = 60


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
        "stops": 0,
        "data_source": "sample",
    }


def _minutes_of_day(value: str) -> int | None:
    try:
        moment = datetime.fromisoformat(value)
        return moment.hour * 60 + moment.minute
    except (TypeError, ValueError):
        return None


def _build_connection(first: dict, second: dict) -> dict:
    """Combine two legs into a 1-stop itinerary. Sample data has no real dates,
    so layover is computed on time-of-day and rolls to the next day if too short."""
    arrive = _minutes_of_day(first["arrival_time"])
    depart = _minutes_of_day(second["departure_time"])
    layover = 120 if arrive is None or depart is None else (depart - arrive) % 1440
    if layover < MIN_LAYOVER_MINUTES:
        layover += 1440
    total_hours = first["duration_hrs"] + second["duration_hrs"] + layover / 60

    return {
        "flight_id": f'{first["flight_id"]}+{second["flight_id"]}',
        "airline": first["airline"] if first["airline"] == second["airline"]
        else f'{first["airline"]} / {second["airline"]}',
        "source": first["source"],
        "destination": second["destination"],
        "via": first["destination"],
        "departure_time": first["departure_time"],
        "arrival_time": second["arrival_time"],
        "departure_display": first["departure_display"],
        "arrival_display": second["arrival_display"],
        "layover_hrs": round(layover / 60, 1),
        "duration_hrs": round(total_hours, 1),
        "price": first["price"] + second["price"],
        "stops": 1,
        "legs": [first, second],
    }


def find_connections(flights: list[dict], source: str, destination: str) -> list[dict]:
    src, dst = source.strip().lower(), destination.strip().lower()
    connections = []
    for first in flights:
        if first["source"].lower() != src or first["destination"].lower() == dst:
            continue
        hub = first["destination"].lower()
        for second in flights:
            if second["source"].lower() == hub and second["destination"].lower() == dst:
                connections.append(_build_connection(first, second))
    return sorted(connections, key=lambda f: (f["price"], f["duration_hrs"]))


def _summarize(results: list[dict], **extra) -> str:
    cheapest = min(results, key=lambda f: f["price"])
    fastest = min(results, key=lambda f: f["duration_hrs"])
    best_value = min(results, key=lambda f: f["price"] / max(f["duration_hrs"], 0.5))
    return json.dumps({
        "found": True,
        **extra,
        "cheapest_flight": cheapest,
        "fastest_flight": fastest,
        "best_value_flight": best_value,
        "all_options_count": len(results),
        "all_options": sorted(results, key=lambda f: f["price"])[:8],
    }, indent=2, ensure_ascii=False)


@tool
def search_flights(source: str, destination: str, travel_date: str = "") -> str:
    """Search flights from source city to destination city on travel_date (YYYY-MM-DD).
    Uses real-time Google Flights data when SERPAPI_API_KEY is set, otherwise the
    sample dataset (with 1-stop connections when no direct flight exists).
    Returns cheapest option, fastest option, and all available flights."""
    live_error = ""
    if live_data_enabled():
        try:
            results = fetch_live_flights(source, destination, travel_date or default_travel_date())
            connecting = all(f["stops"] for f in results)
            return _summarize(results, data_source="live", connecting=connecting)
        except LiveDataError as exc:
            live_error = str(exc)

    try:
        raw_flights = load_json_dataset("flights.json")
        flights = [_normalize_flight(f) for f in raw_flights]

        results = [
            f for f in flights
            if f["source"].strip().lower() == source.strip().lower()
            and f["destination"].strip().lower() == destination.strip().lower()
        ]
        connecting = False
        if not results:
            results = find_connections(flights, source, destination)[:5]
            connecting = bool(results)

        if not results:
            available_routes = sorted({
                f'{f["source"]} → {f["destination"]}' for f in flights
            })
            return json.dumps({
                "found": False,
                "data_source": "sample",
                "live_error": live_error,
                "message": f"No direct or 1-stop flights found from {source} to {destination}.",
                "tip": "Consider train or road travel, or check available_routes.",
                "available_routes": available_routes,
            }, indent=2, ensure_ascii=False)

        return _summarize(results, data_source="sample", live_error=live_error, connecting=connecting)

    except Exception as exc:
        return json.dumps({"error": f"Flight search failed: {exc}"})
