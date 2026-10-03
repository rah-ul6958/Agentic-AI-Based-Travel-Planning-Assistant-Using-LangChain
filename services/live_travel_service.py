"""Real-time flights and hotels via SerpApi (Google Flights + Google Hotels).

Enabled when SERPAPI_API_KEY is set. Every function raises LiveDataError on any
failure so the tools can fall back to the bundled sample datasets.
"""
import os
import time
from datetime import date, datetime, timedelta

import requests

SERPAPI_URL = "https://serpapi.com/search.json"
CACHE_TTL_SECONDS = 30 * 60

# Google Flights accepts comma-separated airport codes.
CITY_AIRPORTS = {
    "delhi": "DEL",
    "mumbai": "BOM",
    "goa": "GOI,GOX",
    "bangalore": "BLR",
    "jaipur": "JAI",
    "kerala": "COK",
    "manali": "KUU",
    "chennai": "MAA",
    "hyderabad": "HYD",
    "kolkata": "CCU",
}

HOTEL_QUERIES = {
    "kerala": "hotels in Kochi, Kerala",
    "goa": "hotels in North Goa",
}

_cache: dict[tuple, tuple[float, object]] = {}


class LiveDataError(RuntimeError):
    pass


def live_data_enabled() -> bool:
    key = os.getenv("SERPAPI_API_KEY", "").strip()
    return bool(key) and key != "your_serpapi_key_here"


def default_travel_date() -> str:
    return str(date.today() + timedelta(days=7))


def _serpapi(params: dict) -> dict:
    if not live_data_enabled():
        raise LiveDataError("SERPAPI_API_KEY not set")

    cache_key = tuple(sorted(params.items()))
    cached = _cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    try:
        response = requests.get(
            SERPAPI_URL,
            params={**params, "api_key": os.getenv("SERPAPI_API_KEY", "").strip(),
                    "currency": "INR", "gl": "in", "hl": "en"},
            timeout=25,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise LiveDataError(f"SerpApi request failed: {type(exc).__name__}") from exc

    if data.get("error"):
        raise LiveDataError(f"SerpApi: {data['error']}")
    if not response.ok:
        raise LiveDataError(f"SerpApi HTTP {response.status_code}")

    _cache[cache_key] = (time.monotonic(), data)
    return data


def _clock(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").strftime("%H:%M")
    except (TypeError, ValueError):
        return str(value or "TBD")


def _normalize_offer(offer: dict, source: str, destination: str) -> dict | None:
    legs = offer.get("flights") or []
    price = offer.get("price")
    if not legs or not price:
        return None

    first, last = legs[0], legs[-1]
    airlines = list(dict.fromkeys(leg.get("airline", "") for leg in legs if leg.get("airline")))
    layovers = offer.get("layovers") or []
    total_minutes = offer.get("total_duration") or sum(leg.get("duration", 0) for leg in legs)

    return {
        "flight_id": " + ".join(leg.get("flight_number", "") for leg in legs).strip(" +"),
        "airline": " / ".join(airlines) or "Airline",
        "source": source,
        "destination": destination,
        "departure_time": first.get("departure_airport", {}).get("time", ""),
        "arrival_time": last.get("arrival_airport", {}).get("time", ""),
        "departure_display": _clock(first.get("departure_airport", {}).get("time")),
        "arrival_display": _clock(last.get("arrival_airport", {}).get("time")),
        "duration_hrs": round(total_minutes / 60, 1),
        "price": float(price),
        "stops": len(layovers),
        "via": ", ".join(l.get("id") or l.get("name", "") for l in layovers),
        "layover_hrs": round(sum(l.get("duration", 0) for l in layovers) / 60, 1),
        "travel_date": (first.get("departure_airport", {}).get("time") or "")[:10],
        "data_source": "live",
    }


def fetch_live_flights(source: str, destination: str, travel_date: str) -> list[dict]:
    src = CITY_AIRPORTS.get(source.strip().lower())
    dst = CITY_AIRPORTS.get(destination.strip().lower())
    if not src or not dst:
        raise LiveDataError(f"No airport mapping for {source} or {destination}")

    data = _serpapi({
        "engine": "google_flights",
        "departure_id": src,
        "arrival_id": dst,
        "outbound_date": travel_date,
        "type": 2,  # one way
        "adults": 1,
    })
    offers = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    flights = [f for f in (_normalize_offer(o, source, destination) for o in offers) if f]
    if not flights:
        raise LiveDataError(f"No live flights found for {source} → {destination} on {travel_date}")
    return flights


def _normalize_property(prop: dict, city: str) -> dict | None:
    price = (prop.get("rate_per_night") or {}).get("extracted_lowest")
    if not price or not prop.get("name"):
        return None
    guest_rating = prop.get("overall_rating")
    stars = prop.get("extracted_hotel_class") or (round(guest_rating) if guest_rating else 3)
    return {
        "hotel_id": prop.get("property_token", ""),
        "name": prop["name"],
        "city": city,
        "rating": float(stars),
        "stars": float(stars),
        "guest_rating": guest_rating,
        "reviews": prop.get("reviews"),
        "price_per_night": float(price),
        "type": (prop.get("type") or "hotel").title(),
        "amenities": (prop.get("amenities") or [])[:6],
        "link": prop.get("link", ""),
        "data_source": "live",
    }


def fetch_live_hotels(city: str, check_in: str, nights: int) -> list[dict]:
    check_out = str(date.fromisoformat(check_in) + timedelta(days=max(int(nights), 1)))
    data = _serpapi({
        "engine": "google_hotels",
        "q": HOTEL_QUERIES.get(city.strip().lower(), f"hotels in {city}"),
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": 2,
    })
    hotels = [h for h in (_normalize_property(p, city) for p in data.get("properties") or []) if h]
    if not hotels:
        raise LiveDataError(f"No live hotels found in {city} for {check_in}")
    return hotels
