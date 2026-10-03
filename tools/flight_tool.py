import json
from datetime import datetime

from langchain_core.tools import tool

from services.live_travel_service import (
    AIRPORT_CITIES,
    NEARBY_AIRPORTS,
    LiveDataError,
    NoResultsError,
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


def _airport_note(source: str, destination: str, from_airport: str, to_airport: str) -> str:
    """Explain the extra road travel when a nearby airport is used."""
    notes = []
    for city, code, word in ((source, from_airport, "from"), (destination, to_airport, "to")):
        code = code.strip().upper()
        if not code:
            continue
        nearby = {c: (name, distance) for name, c, distance in NEARBY_AIRPORTS.get(city.strip().lower(), [])}
        if code in nearby:
            name, distance = nearby[code]
            action = "Departs from" if word == "from" else "Arrives at"
            notes.append(f"{action} {name} ({code}), {distance} {word} {city.title()}")
        elif AIRPORT_CITIES.get(code, "").lower() != city.strip().lower():
            notes.append(f"Uses {code} airport instead of the {city.title()} airport")
    return "; ".join(notes)


def _not_found(source: str, destination: str, message: str, **extra) -> str:
    """No flights: suggest nearby airports so the agent (or the user) can try them."""
    nearby = {
        city: [{"name": name, "code": code, "distance": distance}
               for name, code, distance in NEARBY_AIRPORTS.get(city.strip().lower(), [])]
        for city in (source, destination)
    }
    return json.dumps({
        "found": False,
        **extra,
        "message": message,
        "tip": "Try a nearby airport with from_airport / to_airport, or travel by train or road.",
        "nearby_airports": nearby,
    }, indent=2, ensure_ascii=False)


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
def search_flights(source: str, destination: str, travel_date: str = "", travellers: int = 1,
                   from_airport: str = "", to_airport: str = "") -> str:
    """Search one-way flights from source city to destination city on travel_date (YYYY-MM-DD).
    Call it twice for a round trip (outbound, then the return leg with the cities swapped).
    from_airport / to_airport are optional IATA codes (for example "IXC") to use a
    nearby airport instead of the city's own airport.
    Uses real-time Google Flights data when SERPAPI_API_KEY is set, otherwise the
    sample dataset (with 1-stop connections when no direct flight exists).
    Every price is per person; the budget tool multiplies by travellers.
    Returns cheapest option, fastest option, and all available flights, or found=false
    with nearby airport suggestions."""
    travel_date = travel_date or default_travel_date()
    trip_info = {"travel_date": travel_date, "travellers": max(int(travellers), 1),
                 "price_basis": "per person"}
    note = _airport_note(source, destination, from_airport, to_airport)
    live_error = ""
    if live_data_enabled():
        try:
            live = fetch_live_flights(source, destination, travel_date, from_airport, to_airport)
            results = [{**f, "airport_note": note} if note else f for f in live["flights"]]
            connecting = all(f["stops"] for f in results)
            return _summarize(results, data_source="live", connecting=connecting,
                              fetched_at=live["fetched_at"], from_cache=live["from_cache"],
                              price_insights=live["price_insights"], **trip_info)
        except NoResultsError as exc:
            # Google answered that there are no flights: report it, never show sample flights
            return _not_found(source, destination, str(exc), data_source="live", **trip_info)
        except LiveDataError as exc:
            live_error = str(exc)

    try:
        raw_flights = load_json_dataset("flights.json")
        flights = [_normalize_flight(f) for f in raw_flights]

        # Sample data is stored by city, so an airport code is looked up as its city
        from_city = AIRPORT_CITIES.get(from_airport.strip().upper(), "") if from_airport else source
        to_city = AIRPORT_CITIES.get(to_airport.strip().upper(), "") if to_airport else destination

        results = [
            f for f in flights
            if f["source"].strip().lower() == from_city.strip().lower()
            and f["destination"].strip().lower() == to_city.strip().lower()
        ]
        connecting = False
        if not results and from_city and to_city:
            results = find_connections(flights, from_city, to_city)[:5]
            connecting = bool(results)

        # Sample flights have placeholder dates, so show them on the requested day.
        results = [{**f, "travel_date": travel_date, **({"airport_note": note} if note else {})}
                   for f in results]

        if not results:
            available_routes = sorted({
                f'{f["source"]} → {f["destination"]}' for f in flights
            })
            return _not_found(source, destination,
                              f"No direct or 1-stop flights found from {source} to {destination}.",
                              data_source="sample", live_error=live_error,
                              available_routes=available_routes, **trip_info)

        return _summarize(results, data_source="sample", live_error=live_error,
                          connecting=connecting, **trip_info)

    except Exception as exc:
        return json.dumps({"error": f"Flight search failed: {exc}"})
