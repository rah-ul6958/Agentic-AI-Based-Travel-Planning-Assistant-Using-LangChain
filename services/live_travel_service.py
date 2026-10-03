"""Real-time flights and hotels via SerpApi (Google Flights + Google Hotels).

Enabled when SERPAPI_API_KEY is set. Every function raises LiveDataError on any
failure so the tools can fall back to the bundled sample datasets.
"""
import logging
import threading
import time
from datetime import date, datetime, timedelta

import requests
import streamlit as st

from config.settings import get_setting
from utils.trip_math import check_out_date

logger = logging.getLogger(__name__)

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

# Other airports the agent may try when a city's own airport has no flights.
# (name, IATA code, how far it is from the city by road - approximate)
NEARBY_AIRPORTS = {
    "manali": [("Kullu-Manali (Bhuntar)", "KUU", "about 50 km by road"),
               ("Chandigarh", "IXC", "about 300 km by road"),
               ("Delhi", "DEL", "about 540 km by road or overnight bus")],
    "goa": [("Belagavi", "IXG", "about 150 km by road"),
            ("Mangaluru", "IXE", "about 360 km by road")],
    "kerala": [("Thiruvananthapuram", "TRV", "about 200 km from Kochi"),
               ("Kozhikode", "CCJ", "about 180 km from Kochi")],
    "jaipur": [("Delhi", "DEL", "about 280 km by road or train")],
    "mumbai": [("Pune", "PNQ", "about 150 km by road")],
    "delhi": [("Jaipur", "JAI", "about 280 km by road or train")],
    "bangalore": [("Mysuru", "MYQ", "about 150 km by road")],
    "chennai": [("Tirupati", "TIR", "about 140 km by road")],
    "hyderabad": [("Vijayawada", "VGA", "about 270 km by road")],
    "kolkata": [("Durgapur", "RDP", "about 170 km by road")],
}

# Airport code -> one of our cities, so sample data can also be searched by code
AIRPORT_CITIES = {code: city.title() for city, codes in CITY_AIRPORTS.items() for code in codes.split(",")}

HOTEL_QUERIES = {
    "kerala": "hotels in Kochi, Kerala",
    "goa": "hotels in North Goa",
}

# Remembers, per thread, whether the last request really called SerpApi.
# st.cache_data runs the function in the calling thread, so this is reliable even
# when the agent runs several searches in parallel.
_last_request = threading.local()


class LiveDataError(RuntimeError):
    pass


class NoResultsError(LiveDataError):
    """SerpApi worked, but Google had nothing for this search. This is a real answer
    (for example "no flights on this route that day"), not a failure."""


def _is_empty_result(data: dict) -> bool:
    """SerpApi docs: a search with no results still has search_metadata.status
    "Success", plus an error message saying Google returned no results."""
    status = (data.get("search_metadata") or {}).get("status")
    return status == "Success" and "returned any results" in str(data.get("error", ""))


def live_data_enabled() -> bool:
    key = get_setting("SERPAPI_API_KEY")
    return bool(key) and key != "your_serpapi_key_here"


def default_travel_date() -> str:
    return str(date.today() + timedelta(days=7))


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _cached_request(search: tuple) -> tuple[dict, float]:
    """The real SerpApi call. st.cache_data keeps each answer for 30 minutes and
    shares it with every user of this server. Failures raise, so they are never
    cached. The API key is read here, so it is not part of the cache key."""
    _last_request.called_api = True
    try:
        response = requests.get(
            SERPAPI_URL,
            params={**dict(search), "api_key": get_setting("SERPAPI_API_KEY"),
                    "currency": "INR", "gl": "in", "hl": "en"},
            timeout=25,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        # Only the error type: request errors can contain the URL with the API key
        raise LiveDataError(f"SerpApi request failed: {type(exc).__name__}") from exc

    if data.get("error") and not _is_empty_result(data):
        raise LiveDataError(f"SerpApi: {data['error']}")
    if not response.ok:
        raise LiveDataError(f"SerpApi HTTP {response.status_code}")
    return data, time.time()


def _serpapi(params: dict) -> tuple[dict, float, bool]:
    """Call SerpApi, or reuse a result from the last 30 minutes.
    Returns (data, fetched_at as a Unix timestamp, from_cache)."""
    if not live_data_enabled():
        raise LiveDataError("SERPAPI_API_KEY not set")

    _last_request.called_api = False
    try:
        data, fetched_at = _cached_request(tuple(sorted(params.items())))
    except LiveDataError as exc:
        # Logs the search type and reason only: never the key or the request URL
        logger.warning("SerpApi %s search failed: %s", params.get("engine", "?"), exc)
        raise
    from_cache = not _last_request.called_api
    logger.info("SerpApi %s search: %s", params.get("engine", "?"), "cached" if from_cache else "live")
    return data, fetched_at, from_cache


def clear_cache() -> None:
    """Forget all saved SerpApi answers (used by the tests)."""
    _cached_request.clear()


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
        # Used later, only if the user asks for booking options
        "booking_token": offer.get("booking_token", ""),
        "data_source": "live",
    }


def fetch_live_flights(source: str, destination: str, travel_date: str,
                       from_airport: str = "", to_airport: str = "") -> dict:
    """Returns {"flights", "price_insights", "fetched_at", "from_cache"}.
    from_airport / to_airport (IATA codes) replace the cities' own airports.
    Raises NoResultsError when Google has no flights for this search."""
    src = from_airport.strip().upper() or CITY_AIRPORTS.get(source.strip().lower())
    dst = to_airport.strip().upper() or CITY_AIRPORTS.get(destination.strip().lower())
    if not src or not dst:
        raise LiveDataError(f"No airport mapping for {source} or {destination}")

    data, fetched_at, from_cache = _serpapi({
        "engine": "google_flights",
        "departure_id": src,
        "arrival_id": dst,
        "outbound_date": travel_date,
        "type": 2,  # one way
        # SerpApi's docs do not say whether "price" is per person or for all adults,
        # so we always search for 1 adult and multiply by travellers in the budget.
        "adults": 1,
    })
    offers = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    flights = [f for f in (_normalize_offer(o, source, destination) for o in offers) if f]
    if not flights:
        raise NoResultsError(f"No flights found from {src} to {dst} on {travel_date}")

    # The booking options request repeats the search parameters (see SerpApi docs)
    booking_search = {"departure_id": src, "arrival_id": dst, "outbound_date": travel_date}
    for flight in flights:
        flight["booking_search"] = booking_search

    insights = data.get("price_insights") or {}
    return {
        "flights": flights,
        # price_history is a long list we do not use, so it is left out
        "price_insights": {key: insights[key] for key in
                           ("lowest_price", "price_level", "typical_price_range") if key in insights},
        "fetched_at": fetched_at,
        "from_cache": from_cache,
    }


def fetch_booking_options(booking_token: str, departure_id: str, arrival_id: str,
                          outbound_date: str) -> dict:
    """Real seller list for one flight. Costs one SerpApi search, so it is only
    called when the user clicks "See booking options"."""
    if not booking_token:
        raise LiveDataError("This flight has no booking token")
    data, fetched_at, from_cache = _serpapi({
        "engine": "google_flights",
        "departure_id": departure_id,
        "arrival_id": arrival_id,
        "outbound_date": outbound_date,
        "type": 2,
        "adults": 1,
        "booking_token": booking_token,
    })

    options = []
    for item in data.get("booking_options") or []:
        # One-way results use "together"; "departing" appears for separate tickets
        choice = item.get("together") or item.get("departing") or {}
        if not choice.get("book_with"):
            continue
        request = choice.get("booking_request") or {}
        options.append({
            "seller": choice["book_with"],
            "price": choice.get("price"),
            "option_title": choice.get("option_title", ""),
            "url": request.get("url", ""),
            "post_data": request.get("post_data", ""),
        })
    if not options:
        raise LiveDataError("No booking options were returned for this flight")
    return {"options": options, "fetched_at": fetched_at, "from_cache": from_cache}


def _hotel_prices(prop: dict, nights: int) -> tuple[float, float, str] | None:
    """Return (price per night, price for the whole stay, price note) for one room.

    SerpApi documents rate_per_night / total_rate with "lowest" and a separate
    "before_taxes_fees" value. When both exist, "lowest" is the price after taxes
    and fees. When only the pre-tax value exists we use it and say so."""
    per_night = prop.get("rate_per_night") or {}
    whole_stay = prop.get("total_rate") or {}

    if per_night.get("extracted_lowest"):
        if "extracted_before_taxes_fees" in per_night:
            note = "incl. taxes"
        else:
            note = "taxes may be extra"
        night_price = float(per_night["extracted_lowest"])
        stay_price = whole_stay.get("extracted_lowest")
    elif per_night.get("extracted_before_taxes_fees"):
        note = "excl. taxes"
        night_price = float(per_night["extracted_before_taxes_fees"])
        stay_price = whole_stay.get("extracted_before_taxes_fees")
    else:
        return None

    # total_rate is "for the entire trip"; if it is missing, use nightly price x nights
    stay_price = float(stay_price) if stay_price else night_price * nights
    return night_price, stay_price, note


def _normalize_property(prop: dict, city: str, nights: int) -> dict | None:
    prices = _hotel_prices(prop, nights)
    if not prices or not prop.get("name"):
        return None
    night_price, stay_price, note = prices
    return {
        "hotel_id": prop.get("property_token", ""),
        "name": prop["name"],
        "city": city,
        # Star class and guest rating are different things, so they stay separate.
        # stars is None when Google does not report a hotel class.
        "stars": prop.get("extracted_hotel_class"),
        "guest_rating": prop.get("overall_rating"),
        "reviews": prop.get("reviews"),
        "price_per_night": night_price,
        "stay_price": stay_price,
        "nights": nights,
        "price_note": note,
        "type": (prop.get("type") or "hotel").title(),
        "amenities": (prop.get("amenities") or [])[:6],
        "link": prop.get("link", ""),
        "data_source": "live",
    }


def fetch_live_hotels(city: str, check_in: str, nights: int, adults: int = 2,
                      max_price: int | None = None) -> dict:
    """Prices are for one room for `adults` guests (SerpApi has no rooms parameter).
    max_price asks Google Hotels itself for cheaper hotels (one new search).
    Returns {"hotels", "fetched_at", "from_cache"}."""
    nights = max(int(nights), 1)
    search = {
        "engine": "google_hotels",
        "q": HOTEL_QUERIES.get(city.strip().lower(), f"hotels in {city}"),
        "check_in_date": check_in,
        "check_out_date": check_out_date(check_in, nights),
        "adults": adults,
    }
    if max_price:
        search["max_price"] = int(max_price)  # SerpApi: "upper bound of price range"
    data, fetched_at, from_cache = _serpapi(search)
    properties = data.get("properties") or []
    hotels = [h for h in (_normalize_property(p, city, nights) for p in properties) if h]
    if not hotels:
        raise NoResultsError(f"No hotels found in {city} for {check_in}")
    return {"hotels": hotels, "fetched_at": fetched_at, "from_cache": from_cache}
