import json
import logging
import os
import re
from urllib.parse import quote_plus

from langchain_groq import ChatGroq

from config.settings import BUDGET_PROFILES, groq_model, llm_available, load_environment
from tools.all_tools import ALL_TOOLS
from utils.formatting import format_duration, format_rupees

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
HOTEL_SELECTED: {hotel_line}
WEATHER_FORECAST: Day1:[YYYY-MM-DD] [condition] [max]C/[min]C | Day2:[YYYY-MM-DD] [condition] [max]C/[min]C | ...
DAY_ITINERARY:
Day 1 - [Theme]: Morning: [specific place from data + what to do there]. Afternoon: [specific place + activity]. Evening: [activity or place].
Day 2 - [Theme]: Morning: [place + activity]. Afternoon: [place + activity]. Evening: [activity].
[Continue for all {days} days using real place names from the places data]
BUDGET_BREAKDOWN: {budget_line}
TRAVEL_TIPS: [tip 1]; [tip 2]; [tip 3]; [tip 4]

Rules:
- FLIGHT_SELECTED, HOTEL_SELECTED and BUDGET_BREAKDOWN are pre-computed from the tools: copy them exactly as shown above.
- WEATHER: Use the real forecast dates and temperatures from the weather tool result, one entry per day.
- PLACES: Use actual place names from the places tool result; spread them across the days and avoid repeats.
- Day 1 should account for arrival; the last day should leave time for departure.
- Write day themes that match the destination character (beach, heritage, mountains etc.)
- Be specific and practical, not generic. Tips must be specific to {destination}.

Source city: {source}
Destination: {destination}
Duration: {days} days
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


def _extract_costs(flights_raw: str, hotels_raw: str) -> tuple[float, float]:
    flight_cost = float(_selected_flight(flights_raw).get("price", 0) or 0)
    hotel_cost = float(_selected_hotel(hotels_raw).get("price_per_night", 0) or 0)
    return flight_cost, hotel_cost


def describe_flight(flight: dict, source: str = "", destination: str = "") -> str:
    if not flight:
        return (f"No flights from {source} to {destination} in our dataset | "
                "Consider train or road travel")
    parts = [
        f"{flight.get('airline', 'Airline')} {flight.get('flight_id', '')}".strip(),
        format_rupees(flight.get("price", 0)),
        f"Departs {flight.get('departure_display', 'TBD')} arrives {flight.get('arrival_display', 'TBD')}",
        f"Duration {format_duration(flight.get('duration_hrs', 0))}",
        (f"{flight['stops']} stop{'s' if flight['stops'] > 1 else ''} via {flight.get('via') or 'hub'}"
         if flight.get("stops") else "Non-stop"),
    ]
    if flight.get("travel_date"):
        parts.insert(2, f"Date {flight['travel_date']}")
    return " | ".join(parts)


def describe_hotel(hotel: dict, destination: str = "") -> str:
    if not hotel:
        return f"No hotels in our dataset for {destination} | Book a well-reviewed central stay"
    amenities = ", ".join(hotel.get("amenities", [])) or "wifi"
    stars = hotel.get("stars", hotel.get("rating", 3))
    guest = f" | Guest rating {hotel['guest_rating']}/5" if hotel.get("guest_rating") else ""
    return (f"{hotel.get('name', 'Hotel')} | {float(stars):g} star{guest} | "
            f"{format_rupees(hotel.get('price_per_night', 0))}/night | "
            f"{hotel.get('type', 'Hotel')} | Amenities: {amenities}")


def describe_budget(budget_raw: str) -> str:
    formatted = _load(budget_raw).get("formatted", {})
    if not formatted:
        return ""
    return (f"Flight:{formatted.get('flight', '')} | Hotel:{formatted.get('hotel', '')} | "
            f"Food&Travel:{formatted.get('food_and_travel', '')} | TOTAL:{formatted.get('total', '')}")


def _build_fallback(source, destination, days, budget_level, tool_results):
    """Deterministic itinerary used when the LLM is unavailable."""
    fb = DESTINATION_FALLBACKS.get(destination.lower(), {})

    places = [p.get("name") for p in _load(tool_results.get("places", "")).get("top_places", []) if p.get("name")]
    places = places or fb.get("places") or [
        f"{destination} city centre", "the local market", "a heritage site",
        "a scenic viewpoint", "a popular food street", "a cultural landmark",
    ]
    themes = fb.get("themes", ["Arrival & Orientation", "Local Highlights", "Culture & Food"])
    tips = fb.get("tips", ["Keep digital copies of all bookings",
                           "Start sightseeing early to avoid crowds",
                           "Confirm local transport fares before boarding"])

    forecast = _load(tool_results.get("weather", "")).get("forecast", [])
    weather_str = " | ".join(
        f"Day{i + 1}:{w['date']} {w['condition']} {w['max_temp_c']:.0f}C/{w['min_temp_c']:.0f}C"
        for i, w in enumerate(forecast[:days])
    )

    day_lines = []
    for i in range(days):
        p1, p2, p3 = (places[(i * 2 + k) % len(places)] for k in range(3))
        theme = themes[i % len(themes)]
        morning = (f"Arrive in {destination.title()}, check in and freshen up" if i == 0
                   else f"Visit {p1} and explore the area")
        evening = ("Pick up souvenirs, pack up and head out for your departure"
                   if i == days - 1 and days > 1 else f"Wind down around {p3} for dinner or a walk")
        day_lines.append(
            f"Day {i + 1} - {theme}: Morning: {morning}. "
            f"Afternoon: Head to {p2} with time for local food. Evening: {evening}."
        )

    return "\n".join([
        f"TRIP_SUMMARY: {destination.title()} for {days} days - {budget_level} budget",
        f"FLIGHT_SELECTED: {describe_flight(_selected_flight(tool_results.get('flights', '')), source, destination)}",
        f"HOTEL_SELECTED: {describe_hotel(_selected_hotel(tool_results.get('hotels', '')), destination)}",
        f"WEATHER_FORECAST: {weather_str}",
        "DAY_ITINERARY:",
        "\n".join(day_lines),
        f"BUDGET_BREAKDOWN: {describe_budget(tool_results.get('budget', ''))}",
        f"TRAVEL_TIPS: {'; '.join(tips)}",
    ])


# ── Main planning function ────────────────────────────────────────────────────

def _data_sources(flights_raw: str, hotels_raw: str) -> tuple[dict, list[str]]:
    sources, errors = {}, []
    for name, raw in (("flights", flights_raw), ("hotels", hotels_raw)):
        data = _load(raw)
        sources[name] = data.get("data_source", "sample")
        if data.get("live_error"):
            errors.append(f"{name}: {data['live_error']}")
    return sources, errors


def _booking_links(source: str, destination: str, start_date: str, hotels_raw: str) -> dict:
    hotel = _selected_hotel(hotels_raw)
    flight_query = f"Flights from {source} to {destination}" + (f" on {start_date}" if start_date else "")
    hotel_query = f"{hotel.get('name', 'hotels')} {destination}"
    return {
        "flight": "https://www.google.com/travel/flights?q=" + quote_plus(flight_query),
        "hotel": hotel.get("link") or "https://www.google.com/travel/search?q=" + quote_plus(hotel_query),
    }


def plan_trip(source: str, destination: str, days: int,
              budget_level: str, thought_container=None, start_date: str = "") -> dict:
    """Run all tools then ask LLM to compose final itinerary. Returns structured result."""
    try:
        source = source.strip().title()
        destination = destination.strip().title()
        days = max(1, min(int(days), 7))
        profile = BUDGET_PROFILES.get(budget_level, BUDGET_PROFILES["Medium"])

        # ── Run all 5 tools ──
        flights = _invoke_tool("search_flights",
                               {"source": source, "destination": destination,
                                "travel_date": start_date},
                               thought_container)
        hotels = _invoke_tool("search_hotels",
                              {"city": destination,
                               "max_price": profile["max_price"],
                               "min_rating": profile["min_rating"],
                               "check_in": start_date,
                               "nights": days},
                              thought_container)
        weather = _invoke_tool("get_weather",
                               {"city": destination, "days": days, "start_date": start_date},
                               thought_container)
        places = _invoke_tool("search_places",
                              {"city": destination},
                              thought_container)
        flight_cost, hotel_cost = _extract_costs(flights, hotels)
        budget = _invoke_tool("estimate_budget",
                              {"flight_cost": flight_cost,
                               "hotel_cost_per_night": hotel_cost,
                               "num_nights": days,
                               "daily_food_travel": profile["daily_food_travel"]},
                              thought_container)

        tool_results = {
            "flights": flights,
            "hotels": hotels,
            "weather": weather,
            "places": places,
            "budget": budget,
        }

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
                flight_line=describe_flight(_selected_flight(flights), source, destination),
                hotel_line=describe_hotel(_selected_hotel(hotels), destination),
                budget_line=describe_budget(budget),
                tool_results=json.dumps(
                    {k: _load(v) for k, v in tool_results.items() if k != "budget"},
                    indent=1, ensure_ascii=False,
                ),
            )
            model = groq_model()
            llm = ChatGroq(
                model=model,
                temperature=0.15,
                api_key=os.getenv("GROQ_API_KEY"),
                max_retries=2,
                timeout=60,
                max_tokens=4096,
                # gpt-oss models reason before answering; keep it short so output isn't truncated
                **({"reasoning_effort": "low"} if "gpt-oss" in model else {}),
            )
            raw = llm.invoke(prompt).content
            parsed = parse_itinerary(raw)
            if not parsed["days"]:
                raise TravelPlanningError("LLM response could not be parsed")

        except Exception as exc:
            logger.warning("LLM call failed (%s); using deterministic fallback", exc)
            mode = "offline"
            notice = ("No GROQ_API_KEY configured — itinerary built directly from the travel data."
                      if "not set" in str(exc)
                      else f"AI planner unavailable ({type(exc).__name__}) — showing a data-driven itinerary instead.")
            raw = _build_fallback(source, destination, days, budget_level, tool_results)
            parsed = parse_itinerary(raw)

        # Budget numbers always come from the deterministic budget tool.
        tool_budget = parse_itinerary(f"BUDGET_BREAKDOWN: {describe_budget(budget)}")["budget"]
        if tool_budget:
            parsed["budget"] = tool_budget

        data_sources, live_errors = _data_sources(flights, hotels)
        if live_errors:
            notice = " ".join(filter(None, [
                notice, "Live prices unavailable (" + "; ".join(live_errors) + ") — using sample data.",
            ]))

        return {"success": True, "raw": raw, "parsed": parsed, "mode": mode, "notice": notice,
                "data_sources": data_sources, "start_date": start_date,
                "links": _booking_links(source, destination, start_date, hotels)}

    except Exception as exc:
        logger.exception("Trip planning failed")
        return {"success": False, "raw": str(exc), "parsed": {}}


# ── Parser ────────────────────────────────────────────────────────────────────

SECTION_RE = re.compile(
    r"^(TRIP_SUMMARY|FLIGHT_SELECTED|HOTEL_SELECTED|WEATHER_FORECAST|"
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
        "summary": "", "flight": "", "hotel": "",
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
