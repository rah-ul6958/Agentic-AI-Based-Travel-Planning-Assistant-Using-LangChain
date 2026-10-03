import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

from langchain_groq import ChatGroq

from config.settings import (
    BUDGET_PROFILES,
    MAX_TRAVELLERS,
    MAX_TRIP_DAYS,
    get_setting,
    groq_model,
    llm_available,
    load_environment,
)
from services.live_travel_service import default_travel_date
from tools.all_tools import ALL_TOOLS
from utils.formatting import format_duration, format_rupees
from utils.trip_math import default_return_date, hotel_nights, rooms_needed

load_environment()
logger = logging.getLogger(__name__)


# ── Destination fallbacks (used if LLM fails) ────────────────────────────────

DESTINATION_FALLBACKS = {
    "goa": {
        "places": ["Baga Beach", "Fort Aguada", "Basilica of Bom Jesus", "Anjuna Flea Market", "Dudhsagar Waterfalls", "Calangute Beach"],
        "themes": ["Beach Arrival", "Heritage & Culture", "Markets & Sunsets"],
        "tips": [
            "Book scooters only from verified rentals and carry your licence",
            "Keep sunscreen, water, and light cotton clothing handy at all times",
            "Reserve popular beach shacks in advance on weekends",
            "Start Old Goa church visits early to avoid midday heat",
        ],
    },
    "jaipur": {
        "places": ["Amber Fort", "City Palace", "Hawa Mahal", "Jantar Mantar", "Nahargarh Fort", "Johari Bazaar"],
        "themes": ["Royal Forts", "Old City Walk", "Markets & Views"],
        "tips": [
            "Start fort visits early for cooler weather and fewer crowds",
            "Use app-based rides between spread-out monuments",
            "Keep cash for local markets and small food stalls",
            "Hire a local guide at Amber Fort for the best stories",
        ],
    },
    "manali": {
        "places": ["Hadimba Temple", "Old Manali", "Solang Valley", "Mall Road", "Vashisht Hot Springs", "Atal Tunnel"],
        "themes": ["Mountain Arrival", "Adventure Valley", "Cafe Trail"],
        "tips": [
            "Carry layers because evenings get cold quickly",
            "Check road conditions before Solang or Atal Tunnel plans",
            "Acclimatise on day one before any high-altitude activities",
        ],
    },
    "kerala": {
        "places": ["Fort Kochi", "Alleppey Backwaters", "Munnar Tea Gardens", "Mattancherry Palace", "Varkala Cliff", "Kumarakom"],
        "themes": ["Coastal Culture", "Backwaters", "Tea & Hills"],
        "tips": [
            "Keep rain protection handy during monsoon months",
            "Book houseboats in advance and confirm meal inclusions",
            "Plan extra travel time between hill and coastal regions",
        ],
    },
    "delhi": {
        "places": ["Red Fort", "India Gate", "Qutub Minar", "Chandni Chowk", "Humayun's Tomb", "Lotus Temple"],
        "themes": ["Mughal Heritage", "Cultural Delhi", "Markets & Food"],
        "tips": [
            "Use the Delhi Metro to avoid traffic between monuments",
            "Visit monuments early morning to beat heat and crowds",
            "Try street food at Chandni Chowk but stick to busy stalls",
        ],
    },
    "mumbai": {
        "places": ["Gateway of India", "Marine Drive", "Elephanta Caves", "Colaba Causeway", "Dharavi", "Bandra Bandstand"],
        "themes": ["Heritage Waterfront", "Art & Culture", "Food & Nightlife"],
        "tips": [
            "Use local trains for fast cross-city travel",
            "Evenings at Marine Drive are magical and free",
            "Book Elephanta ferry early to avoid long queues",
        ],
    },
    "kolkata": {
        "places": ["Victoria Memorial", "Howrah Bridge", "Dakshineswar Temple", "Park Street", "Indian Museum", "Kumartuli"],
        "themes": ["Colonial Heritage", "Cultural Walk", "Food & Art"],
        "tips": [
            "Kolkata taxis are metered and reliable",
            "Try kathi rolls and mishti doi from local shops",
            "The Victoria Memorial museum is best in the morning light",
        ],
    },
    "hyderabad": {
        "places": ["Charminar", "Golconda Fort", "Hussain Sagar Lake", "Laad Bazaar", "Ramoji Film City", "Salar Jung Museum"],
        "themes": ["Nizam Heritage", "Old City Walk", "Food & Lakes"],
        "tips": [
            "Try Hyderabadi biryani from Paradise or Bawarchi",
            "Auto-rickshaws are good for short distances in the old city",
            "Golconda sound and light show is excellent in the evening",
        ],
    },
    "bangalore": {
        "places": ["Lalbagh Botanical Garden", "Cubbon Park", "MG Road", "Tipu Sultan's Summer Palace", "Ulsoor Lake", "Vidhana Soudha"],
        "themes": ["Gardens & Parks", "Heritage Trail", "Food & Pubs"],
        "tips": [
            "Traffic is heavy; use Namma Metro for key routes",
            "Evenings on Church Street and Brigade Road are lively",
            "Bangalore weather is mild year-round, making it easy to walk",
        ],
    },
    "chennai": {
        "places": ["Marina Beach", "Kapaleeshwarar Temple", "Fort St. George", "T. Nagar Market", "San Thome Basilica", "Mylapore"],
        "themes": ["Coastal Chennai", "Temple Trail", "Markets & Food"],
        "tips": [
            "Visit temples early and dress modestly with shoulders covered",
            "Try a filter coffee and a full South Indian thali",
            "Avoid Marina Beach swims; currents are strong",
        ],
    },
}

# ── LLM prompt ────────────────────────────────────────────────────────────────

ITINERARY_PROMPT = """You are an expert Indian travel planner creating a complete, personalised itinerary.

Use the tool results provided below as your only data source. Do NOT invent flight numbers, prices, or hotel names — use what is in the tool data.

Return your itinerary using EXACTLY this format (plain text, no markdown, no bold, keep the header names verbatim, one section per line):

TRIP_SUMMARY: {destination} for {days} days - {budget_level} budget
FLIGHT_SELECTED: {flight_line}
RETURN_FLIGHT_SELECTED: {return_flight_line}
HOTEL_SELECTED: {hotel_line}
WEATHER_FORECAST: {weather_line}
DAY_ITINERARY:
Day 1 - [Theme]: Morning: [specific place from data + what to do there]. Afternoon: [specific place + activity]. Evening: [activity or place].
Day 2 - [Theme]: Morning: [place + activity]. Afternoon: [place + activity]. Evening: [activity].
[Continue for all {days} days using real place names from the places data]
BUDGET_BREAKDOWN: {budget_line}
TRAVEL_TIPS: [tip 1]; [tip 2]; [tip 3]; [tip 4]

Rules:
- FLIGHT_SELECTED, RETURN_FLIGHT_SELECTED, HOTEL_SELECTED, WEATHER_FORECAST and BUDGET_BREAKDOWN are pre-computed from the tools: copy them exactly as shown above. Never write your own prices or numbers.
- WEATHER: Use the forecast only to adapt the plan (for example indoor options on rainy days). If it says "Not available", do not guess the weather.
- PLACES: Use actual place names from the places tool result; spread them across the days and avoid repeats.
- Day 1 should account for arrival; the last day should leave time for the return flight.
- Write day themes that match the destination character (beach, heritage, mountains etc.)
- Be specific and practical, not generic. Tips must be specific to {destination}.

Source city: {source}
Destination: {destination}
Duration: {days} days ({nights} hotel nights)
Travellers: {travellers}
Budget level: {budget_level}

TOOL RESULTS:
{tool_results}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

class TravelPlanningError(RuntimeError):
    pass


TOOL_MAP = {t.name: t for t in ALL_TOOLS}


def _invoke_tool(name: str, payload: dict, thought_container=None) -> str:
    logger.info("Calling tool: %s", name)
    if thought_container:
        try:
            thought_container.markdown(f"🔍 Running `{name}`...")
        except Exception:
            pass
    return TOOL_MAP[name].invoke(payload)


def _load(raw: str) -> dict:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _selected_flight(flights_raw: str) -> dict:
    data = _load(flights_raw)
    return data.get("cheapest_flight") or data.get("fastest_flight") or {}


def _selected_hotel(hotels_raw: str) -> dict:
    data = _load(hotels_raw)
    return data.get("recommended") or data.get("cheapest") or {}


def _flight_price(flights_raw: str) -> float:
    """Per-person price of the chosen flight, or 0 when no flight was found."""
    return float(_selected_flight(flights_raw).get("price", 0) or 0)


def describe_flight(flight: dict, source: str = "", destination: str = "") -> str:
    if not flight:
        return (f"No flights found from {source} to {destination} | "
                "Train or road travel is needed, or try a nearby airport")
    parts = [
        f"{flight.get('airline', 'Airline')} {flight.get('flight_id', '')}".strip(),
        f"{format_rupees(flight.get('price', 0))} per person",
        f"Departs {flight.get('departure_display', 'TBD')} arrives {flight.get('arrival_display', 'TBD')}",
        f"Duration {format_duration(flight.get('duration_hrs', 0))}",
        (f"{flight['stops']} stop{'s' if flight['stops'] > 1 else ''} via {flight.get('via') or 'hub'}"
         if flight.get("stops") else "Non-stop"),
    ]
    if flight.get("travel_date"):
        parts.insert(2, f"Date {flight['travel_date']}")
    if flight.get("airport_note"):
        parts.append(flight["airport_note"])
    return " | ".join(parts)


def describe_hotel(hotel: dict, destination: str = "", rooms: int = 1) -> str:
    if not hotel:
        return f"No hotels in our dataset for {destination} | Book a well-reviewed central stay"
    nights = int(hotel.get("nights", 1) or 1)
    price = f"{format_rupees(hotel.get('price_per_night', 0))}/night per room"
    if hotel.get("price_note"):
        price += f" ({hotel['price_note']})"
    parts = [hotel.get("name", "Hotel")]
    if hotel.get("stars"):
        parts.append(f"{hotel['stars']} star")
    if hotel.get("guest_rating"):
        parts.append(f"Guest rating {hotel['guest_rating']}/5")
    parts += [
        price,
        f"{rooms} room{'s' if rooms > 1 else ''} x {nights} night{'s' if nights > 1 else ''}",
        hotel.get("type", "Hotel"),
        f"Amenities: {', '.join(hotel.get('amenities', [])) or 'not listed'}",
    ]
    return " | ".join(parts)


def describe_weather(weather_raw: str) -> str:
    forecast = _load(weather_raw).get("forecast", [])
    return " | ".join(
        f"Day{i + 1}:{w['date']} {w['condition']} {w['max_temp_c']:.0f}C/{w['min_temp_c']:.0f}C"
        for i, w in enumerate(forecast)
    )


def _fixed_sections(source: str, destination: str, days: int, budget_level: str,
                    tool_results: dict, rooms: int) -> dict:
    """Sections built only from tool data. They replace whatever the LLM wrote,
    so prices, totals and weather never come from the LLM."""
    weather_line = describe_weather(tool_results.get("weather", ""))
    return {
        "summary": f"{destination.title()} for {days} days - {budget_level} budget",
        "flight": describe_flight(_selected_flight(tool_results.get("flights", "")), source, destination),
        "return_flight": describe_flight(_selected_flight(tool_results.get("return_flights", "")),
                                         destination, source),
        "hotel": describe_hotel(_selected_hotel(tool_results.get("hotels", "")), destination, rooms),
        "weather": [item.strip() for item in weather_line.split("|") if item.strip()],
    }


def describe_budget(budget_raw: str) -> str:
    formatted = _load(budget_raw).get("formatted", {})
    if not formatted:
        return ""
    return (f"Flight:{formatted.get('flight', '')} | Hotel:{formatted.get('hotel', '')} | "
            f"Food&Travel:{formatted.get('food_and_travel', '')} | TOTAL:{formatted.get('total', '')}")


def _build_fallback(source, destination, days, budget_level, tool_results, rooms=1):
    """Deterministic itinerary used when the LLM is unavailable."""
    fb = DESTINATION_FALLBACKS.get(destination.lower(), {})
    fixed = _fixed_sections(source, destination, days, budget_level, tool_results, rooms)

    places = [p.get("name") for p in _load(tool_results.get("places", "")).get("top_places", []) if p.get("name")]
    places = places or fb.get("places") or [
        f"{destination} city centre", "the local market", "a heritage site",
        "a scenic viewpoint", "a popular food street", "a cultural landmark",
    ]
    themes = fb.get("themes", ["Arrival & Orientation", "Local Highlights", "Culture & Food"])
    tips = fb.get("tips", ["Keep digital copies of all bookings",
                           "Start sightseeing early to avoid crowds",
                           "Confirm local transport fares before boarding"])

    day_lines = []
    for i in range(days):
        p1, p2, p3 = (places[(i * 2 + k) % len(places)] for k in range(3))
        theme = themes[i % len(themes)]
        morning = (f"Arrive in {destination.title()}, check in and freshen up" if i == 0
                   else f"Visit {p1} and explore the area")
        evening = ("Pick up souvenirs, pack up and head out for your return flight"
                   if i == days - 1 and days > 1 else f"Wind down around {p3} for dinner or a walk")
        day_lines.append(
            f"Day {i + 1} - {theme}: Morning: {morning}. "
            f"Afternoon: Head to {p2} with time for local food. Evening: {evening}."
        )

    return "\n".join([
        f"TRIP_SUMMARY: {fixed['summary']}",
        f"FLIGHT_SELECTED: {fixed['flight']}",
        f"RETURN_FLIGHT_SELECTED: {fixed['return_flight']}",
        f"HOTEL_SELECTED: {fixed['hotel']}",
        f"WEATHER_FORECAST: {' | '.join(fixed['weather'])}",
        "DAY_ITINERARY:",
        "\n".join(day_lines),
        f"BUDGET_BREAKDOWN: {describe_budget(tool_results.get('budget', ''))}",
        f"TRAVEL_TIPS: {'; '.join(tips)}",
    ])


# ── Main planning function ────────────────────────────────────────────────────

def _data_sources(tool_results: dict) -> tuple[dict, list[str]]:
    sources, errors = {}, []
    for name in ("flights", "return_flights", "hotels"):
        raw = tool_results.get(name, "")
        data = _load(raw)
        sources[name] = data.get("data_source", "sample")
        if data.get("live_error"):
            errors.append(f"{name.replace('_', ' ')}: {data['live_error']}")
    return sources, errors


def _live_details(tool_results: dict) -> dict:
    """Where each card's data came from, Google's price insights, and the booking
    tokens needed for the optional "See booking options" button."""
    details = {"freshness": {}, "price_insights": {}, "booking": {}}
    for name in ("flights", "return_flights", "hotels"):
        data = _load(tool_results.get(name, ""))
        details["freshness"][name] = {
            "data_source": data.get("data_source", "sample"),
            "fetched_at": data.get("fetched_at"),
            "from_cache": bool(data.get("from_cache")),
        }
        if name == "hotels":
            continue
        details["price_insights"][name] = data.get("price_insights") or {}
        flight = _selected_flight(tool_results.get(name, ""))
        if flight.get("booking_token"):
            details["booking"][name] = {"token": flight["booking_token"],
                                        "search": flight.get("booking_search", {})}
    return details


def _booking_links(source: str, destination: str, start_date: str, return_date: str,
                   hotels_raw: str) -> dict:
    hotel = _selected_hotel(hotels_raw)
    flight_query = f"Flights from {source} to {destination}" + (f" on {start_date}" if start_date else "")
    return_query = f"Flights from {destination} to {source}" + (f" on {return_date}" if return_date else "")
    hotel_query = f"{hotel.get('name', 'hotels')} {destination}"
    return {
        "flight": "https://www.google.com/travel/flights?q=" + quote_plus(flight_query),
        "return_flight": "https://www.google.com/travel/flights?q=" + quote_plus(return_query),
        "hotel": hotel.get("link") or "https://www.google.com/travel/search?q=" + quote_plus(hotel_query),
    }


def make_llm(max_tokens: int = 4096):
    """The Groq chat model used by the agent and by the itinerary writer."""
    model = groq_model()
    return ChatGroq(
        model=model,
        temperature=0.15,
        api_key=get_setting("GROQ_API_KEY"),
        max_retries=2,
        timeout=60,
        max_tokens=max_tokens,
        # gpt-oss models reason before answering; keep it short so output isn't truncated
        **({"reasoning_effort": "low"} if "gpt-oss" in model else {}),
    )


def prepare_trip(source: str, destination: str, days: int, budget_level: str,
                 start_date: str = "", return_date: str = "", travellers: int = 1) -> dict:
    """Clean up the user's choices into one trip dict that every step shares."""
    source = source.strip().title()
    destination = destination.strip().title()
    days = max(1, min(int(days), MAX_TRIP_DAYS))
    travellers = max(1, min(int(travellers), MAX_TRAVELLERS))
    budget_level = budget_level if budget_level in BUDGET_PROFILES else "Medium"

    # Trip dates: return on the last day unless a valid return date is given.
    start_date = start_date or default_travel_date()
    if not return_date or return_date < start_date:
        return_date = default_return_date(start_date, days)
    return {
        "source": source, "destination": destination, "days": days,
        "budget_level": budget_level, "travellers": travellers,
        "start_date": start_date, "return_date": return_date, "nights": hotel_nights(days),
    }


def run_searches(trip: dict, thought_container=None) -> dict:
    """The five standard searches every new plan needs."""
    profile = BUDGET_PROFILES[trip["budget_level"]]
    source, destination = trip["source"], trip["destination"]

    # ── Run all 5 tools ──
    # These searches do not depend on each other, so they run at the same time.
    # The budget tool runs afterwards because it needs their prices.
    searches = {
        "flights": ("search_flights",
                    {"source": source, "destination": destination,
                     "travel_date": trip["start_date"], "travellers": trip["travellers"]}),
        "return_flights": ("search_flights",
                           {"source": destination, "destination": source,
                            "travel_date": trip["return_date"], "travellers": trip["travellers"]}),
        "hotels": ("search_hotels",
                   {"city": destination,
                    "max_price": profile["max_price"],
                    "min_stars": profile["min_stars"],
                    "check_in": trip["start_date"],
                    "nights": trip["nights"],
                    "travellers": trip["travellers"]}),
        "weather": ("get_weather",
                    {"city": destination, "days": trip["days"], "start_date": trip["start_date"]}),
        "places": ("search_places", {"city": destination}),
    }
    with ThreadPoolExecutor(max_workers=len(searches)) as pool:
        jobs = {name: pool.submit(_invoke_tool, tool_name, payload, thought_container)
                for name, (tool_name, payload) in searches.items()}
        return {name: job.result() for name, job in jobs.items()}


def rooms_for(trip: dict, tool_results: dict) -> int:
    return _load(tool_results.get("hotels", "")).get("rooms") or rooms_needed(trip["travellers"])


def compute_budget(trip: dict, tool_results: dict, thought_container=None) -> str:
    """Deterministic budget from the chosen flights and hotel (never from the LLM)."""
    profile = BUDGET_PROFILES[trip["budget_level"]]
    hotel = _selected_hotel(tool_results.get("hotels", ""))
    return _invoke_tool("estimate_budget",
                        {"outbound_flight_price": _flight_price(tool_results.get("flights", "")),
                         "return_flight_price": _flight_price(tool_results.get("return_flights", "")),
                         "hotel_stay_price": float(hotel.get("stay_price", 0) or 0),
                         "rooms": rooms_for(trip, tool_results),
                         "nights": trip["nights"],
                         "days": trip["days"],
                         "travellers": trip["travellers"],
                         "daily_food_travel": profile["daily_food_travel"],
                         "hotel_price_note": hotel.get("price_note", "")},
                        thought_container)


def _change_request_section(request: str, previous: dict | None) -> str:
    """Extra prompt text for a follow-up such as "make day 2 more relaxed"."""
    if not request:
        return ""
    previous = previous or {}
    return (
        "\n\nCHANGE REQUEST FROM THE TRAVELLER: " + request + "\n"
        "This updates an existing plan. Apply the request, keep everything else the same "
        "where possible, and still return the complete itinerary in the format above.\n"
        "CURRENT DAY PLAN:\n" + "\n".join(previous.get("days", [])) + "\n"
        "CURRENT TIPS: " + "; ".join(previous.get("tips", [])) + "\n"
    )


def write_itinerary(trip: dict, tool_results: dict, request: str = "",
                    previous: dict | None = None) -> tuple[dict, str, str]:
    """The LLM writes the days and tips (or the offline fallback does).
    Returns (parsed itinerary, mode, notice)."""
    source, destination, days = trip["source"], trip["destination"], trip["days"]
    budget_level = trip["budget_level"]
    rooms = rooms_for(trip, tool_results)
    budget = tool_results.get("budget", "")
    fixed = _fixed_sections(source, destination, days, budget_level, tool_results, rooms)

    # ── Ask LLM to compose itinerary ──
    mode, notice = "ai", ""
    try:
        if not llm_available():
            raise TravelPlanningError("GROQ_API_KEY not set")

        prompt = ITINERARY_PROMPT.format(
            source=source,
            destination=destination,
            days=days,
            budget_level=budget_level,
            nights=trip["nights"],
            travellers=trip["travellers"],
            flight_line=fixed["flight"],
            return_flight_line=fixed["return_flight"],
            hotel_line=fixed["hotel"],
            weather_line=" | ".join(fixed["weather"]) or "Not available",
            budget_line=describe_budget(budget),
            tool_results=json.dumps(
                {k: _load(v) for k, v in tool_results.items() if k != "budget"},
                indent=1, ensure_ascii=False,
            ),
        ) + _change_request_section(request, previous)
        raw = make_llm().invoke(prompt).content
        parsed = parse_itinerary(raw)
        if not parsed["days"]:
            raise TravelPlanningError("LLM response could not be parsed")

    except Exception as exc:
        # Error type and message only; Groq error messages do not contain the key
        logger.warning("LLM call failed (%s: %s); using deterministic fallback",
                       type(exc).__name__, str(exc)[:200])
        mode = "offline"
        notice = ("No GROQ_API_KEY configured — itinerary built directly from the travel data."
                  if "not set" in str(exc)
                  else f"AI planner unavailable ({type(exc).__name__}) — showing a data-driven itinerary instead.")
        raw = _build_fallback(source, destination, days, budget_level, tool_results, rooms)
        parsed = parse_itinerary(raw)
        if previous and previous.get("days"):
            # The offline writer cannot apply a change request, so keep the last day plan
            parsed["days"], parsed["tips"] = previous["days"], previous.get("tips", parsed["tips"])

    # Budget numbers always come from the deterministic budget tool.
    tool_budget = parse_itinerary(f"BUDGET_BREAKDOWN: {describe_budget(budget)}")["budget"]
    if tool_budget:
        parsed["budget"] = tool_budget
    # Flights, hotel, weather and the summary also come from code, never from the LLM.
    parsed.update(fixed)
    return parsed, mode, notice


def build_result(trip: dict, tool_results: dict, parsed: dict, mode: str, notice: str,
                 agent_notes: list | None = None) -> dict:
    """Everything the UI needs, plus the state needed for follow-up requests."""
    data_sources, live_errors = _data_sources(tool_results)
    if live_errors:
        notice = " ".join(filter(None, [
            notice, "Live prices unavailable (" + "; ".join(live_errors) + ") — using sample data.",
        ]))
    profile = BUDGET_PROFILES[trip["budget_level"]]
    hotel = _selected_hotel(tool_results.get("hotels", ""))
    # Judge the chosen hotel against the user's budget level (not an agent's search cap)
    if hotel and (hotel.get("price_per_night", 0) > profile["max_price"]
                  or (hotel.get("stars") and hotel["stars"] < profile["min_stars"])):
        limit = format_rupees(profile["max_price"])
        notice = " ".join(filter(None, [
            notice, f"No hotel matched the {trip['budget_level']} budget (up to {limit} per room per night "
                    f"and the star rating), so the cheapest available hotel is shown.",
        ]))

    weather_data = _load(tool_results.get("weather", ""))
    return {"success": True, "raw": format_itinerary_text(parsed), "parsed": parsed,
            "mode": mode, "notice": notice, "data_sources": data_sources,
            "start_date": trip["start_date"], "return_date": trip["return_date"],
            "travellers": trip["travellers"], "nights": trip["nights"],
            "rooms": rooms_for(trip, tool_results),
            "weather_message": weather_data.get("message", ""),
            **_live_details(tool_results),
            "links": _booking_links(trip["source"], trip["destination"], trip["start_date"],
                                    trip["return_date"], tool_results.get("hotels", "")),
            "agent_notes": list(agent_notes or []),
            # Kept so a follow-up request can reuse these results instead of searching again
            "state": {"trip": trip, "tool_results": tool_results}}


AGENT_UNAVAILABLE = ("The planning agent (LangGraph) could not be loaded, so the plan uses the "
                     "standard searches only. Run the app from the project's venv to enable it.")


def _load_graph():
    """The LangGraph agent, or None if langgraph cannot be imported here (for example
    an environment where langgraph and langchain-core versions do not match)."""
    try:
        from agent import graph
        return graph
    except ImportError as exc:
        logger.warning("LangGraph unavailable (%s); using the simple pipeline", exc)
        return None


def run_without_agent(trip: dict, thought_container=None) -> dict:
    """The same steps as the graph, one after another, without the agent loop."""
    tool_results = run_searches(trip, thought_container)
    tool_results["budget"] = compute_budget(trip, tool_results, thought_container)
    parsed, mode, notice = write_itinerary(trip, tool_results)
    return build_result(trip, tool_results, parsed, mode, " ".join(filter(None, [notice, AGENT_UNAVAILABLE])))


def plan_trip(source: str, destination: str, days: int,
              budget_level: str, thought_container=None, start_date: str = "",
              return_date: str = "", travellers: int = 1) -> dict:
    """Run all tools then ask LLM to compose final itinerary. Returns structured result.
    The steps are run by the LangGraph agent in agent/graph.py."""
    try:
        trip = prepare_trip(source, destination, days, budget_level, start_date, return_date, travellers)
        graph = _load_graph()
        if graph is None:
            return run_without_agent(trip, thought_container)
        return graph.run_graph(trip, thought_container=thought_container)

    except Exception as exc:
        logger.exception("Trip planning failed")
        return {"success": False, "raw": str(exc), "parsed": {}}


def describe_changes(old: dict, new: dict) -> list[str]:
    """What a follow-up request changed, written by code so every number is real."""
    before, after = old.get("parsed", {}), new.get("parsed", {})
    lines = []
    for key, label in (("flight", "Outbound flight"), ("return_flight", "Return flight"), ("hotel", "Hotel")):
        old_name = before.get(key, "").split("|")[0].strip()
        new_name = after.get(key, "").split("|")[0].strip()
        if old_name != new_name:
            lines.append(f"{label}: {old_name} -> {new_name}")
    old_total = before.get("budget", {}).get("TOTAL")
    new_total = after.get("budget", {}).get("TOTAL")
    if old_total != new_total:
        lines.append(f"Estimated total: {old_total} -> {new_total}")
    if before.get("days") != after.get("days"):
        lines.append("Day-by-day plan updated")
    return lines or ["No changes were needed"]


def revise_trip(previous_result: dict, request: str) -> dict:
    """Apply a follow-up request ("find a cheaper hotel", "make day 2 more relaxed")
    to an existing plan. The agent re-runs only the tools the request needs and
    reuses every other result from the previous plan."""
    request = (request or "").strip()[:500]
    state = previous_result.get("state") or {}
    if not request or not state.get("tool_results"):
        return {"success": False, "raw": "There is no plan to change yet.", "parsed": {}}
    if not llm_available():
        return {"success": False, "parsed": {},
                "raw": "Follow-up changes need the AI planner. Add GROQ_API_KEY to use them."}
    graph = _load_graph()
    if graph is None:
        return {"success": False, "parsed": {}, "raw": AGENT_UNAVAILABLE}
    try:
        result = graph.run_graph(state["trip"], request=request, previous=previous_result.get("parsed", {}),
                                 tool_results=state["tool_results"])
        result["changes"] = describe_changes(previous_result, result)
        return result
    except Exception as exc:
        logger.exception("Follow-up request failed")
        return {"success": False, "raw": str(exc), "parsed": {}}


# ── Parser ────────────────────────────────────────────────────────────────────

SECTION_RE = re.compile(
    r"^(TRIP_SUMMARY|FLIGHT_SELECTED|RETURN_FLIGHT_SELECTED|HOTEL_SELECTED|WEATHER_FORECAST|"
    r"DAY_ITINERARY|BUDGET_BREAKDOWN|TRAVEL_TIPS)\s*:\s*(.*)$",
    re.IGNORECASE,
)
DAY_RE = re.compile(r"^day\s*\d+", re.IGNORECASE)


def _split_budget(text: str, budget: dict) -> None:
    for item in text.split("|"):
        if ":" in item:
            key, value = item.split(":", 1)
            if key.strip() and value.strip():
                budget[key.strip()] = value.strip()


def _split_tips(text: str) -> list[str]:
    return [t.strip(" .") for t in re.split(r";|(?<=\.)\s+(?=[A-Z])", text) if t.strip(" .")]


def parse_itinerary(text: str) -> dict:
    """Parse structured agent output into a dict for the UI."""
    result = {
        "summary": "", "flight": "", "return_flight": "", "hotel": "",
        "weather": [], "days": [], "budget": {}, "tips": [],
    }

    section = None
    for raw_line in (text or "").splitlines():
        line = raw_line.replace("**", "").replace("__", "").strip()
        line = re.sub(r"^[-*#•>\s]+", "", line).strip()
        if not line:
            continue

        header = SECTION_RE.match(line)
        if header:
            section = header.group(1).upper()
            value = header.group(2).strip()
            if section == "TRIP_SUMMARY":
                result["summary"] = value
            elif section == "FLIGHT_SELECTED":
                result["flight"] = value
            elif section == "RETURN_FLIGHT_SELECTED":
                result["return_flight"] = value
            elif section == "HOTEL_SELECTED":
                result["hotel"] = value
            elif section == "WEATHER_FORECAST":
                result["weather"].extend(i.strip() for i in value.split("|") if i.strip())
            elif section == "BUDGET_BREAKDOWN":
                _split_budget(value, result["budget"])
            elif section == "TRAVEL_TIPS":
                result["tips"].extend(_split_tips(value))
            elif section == "DAY_ITINERARY" and DAY_RE.match(value):
                result["days"].append(value)
            continue

        if section == "DAY_ITINERARY":
            if DAY_RE.match(line):
                result["days"].append(line)
            elif result["days"]:
                result["days"][-1] += " " + line
        elif section == "WEATHER_FORECAST":
            result["weather"].extend(i.strip() for i in line.split("|") if i.strip())
        elif section == "BUDGET_BREAKDOWN":
            _split_budget(line, result["budget"])
        elif section == "TRAVEL_TIPS":
            result["tips"].extend(_split_tips(re.sub(r"^\d+[.)]\s*", "", line)))

    result["tips"] = [t[0].upper() + t[1:] for t in result["tips"] if len(t) > 8][:6]
    return result


def format_itinerary_text(parsed: dict) -> str:
    """Turn parsed sections back into the standard text format (used for downloads),
    so the downloaded text always matches what the app shows."""
    budget = " | ".join(f"{key}:{value}" for key, value in parsed.get("budget", {}).items())
    weather = " | ".join(parsed.get("weather", [])) or "Not available yet"
    return "\n".join([
        f"TRIP_SUMMARY: {parsed.get('summary', '')}",
        f"FLIGHT_SELECTED: {parsed.get('flight', '')}",
        f"RETURN_FLIGHT_SELECTED: {parsed.get('return_flight', '')}",
        f"HOTEL_SELECTED: {parsed.get('hotel', '')}",
        f"WEATHER_FORECAST: {weather}",
        "DAY_ITINERARY:",
        *parsed.get("days", []),
        f"BUDGET_BREAKDOWN: {budget}",
        f"TRAVEL_TIPS: {'; '.join(parsed.get('tips', []))}",
    ])
