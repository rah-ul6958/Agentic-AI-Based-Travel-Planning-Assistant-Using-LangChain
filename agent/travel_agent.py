import json
import logging
import os
import re

from langchain_groq import ChatGroq

from config.settings import BUDGET_PROFILES, load_environment
from tools.all_tools import ALL_TOOLS

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
}

FALLBACK_FLIGHTS = {
    ("delhi", "goa"): "IndiGo FL0026 | Rs.5,200 | Departs 06:00 arrives 08:30 | Duration 2h 30m",
    ("delhi", "jaipur"): "SpiceJet FL0031 | Rs.1,600 | Departs 13:00 arrives 14:05 | Duration 1h 5m",
    ("delhi", "mumbai"): "IndiGo FL0033 | Rs.3,800 | Departs 07:00 arrives 09:00 | Duration 2h 0m",
    ("delhi", "bangalore"): "Air India FL0036 | Rs.4,500 | Departs 06:45 arrives 09:15 | Duration 2h 30m",
    ("delhi", "hyderabad"): "IndiGo FL0038 | Rs.4,200 | Departs 08:30 arrives 11:00 | Duration 2h 30m",
    ("delhi", "kolkata"): "SpiceJet FL0039 | Rs.3,600 | Departs 07:00 arrives 09:30 | Duration 2h 30m",
    ("delhi", "chennai"): "Air India FL0040 | Rs.4,800 | Departs 09:00 arrives 11:30 | Duration 2h 30m",
    ("mumbai", "goa"): "IndiGo FL0004 | Rs.2,100 | Departs 14:38 arrives 15:43 | Duration 1h 5m",
    ("bangalore", "goa"): "SpiceJet FL0002 | Rs.3,200 | Departs 07:15 arrives 08:20 | Duration 1h 5m",
    ("bangalore", "mumbai"): "Vistara FL0006 | Rs.3,500 | Departs 10:00 arrives 11:30 | Duration 1h 30m",
}


# ── LLM prompt ────────────────────────────────────────────────────────────────

ITINERARY_PROMPT = """You are an expert Indian travel planner creating a complete, personalised itinerary.

Use the tool results provided below as your primary data source. Do NOT invent flight numbers, prices, or hotel names — use what is in the tool data.

Return your itinerary using EXACTLY this format (keep the header names verbatim):

TRIP_SUMMARY: {destination} for {days} days - {budget_level} budget
FLIGHT_SELECTED: [Airline + flight_id] | Rs.[price] | Departs [HH:MM] arrives [HH:MM] | Duration [Xh Ym]
HOTEL_SELECTED: [Hotel name] | [stars] star | Rs.[price_per_night]/night | [type] | Amenities: [amenities list]
WEATHER_FORECAST: Day1:[date] [condition] [max]C/[min]C | Day2:[date] [condition] [max]C/[min]C | ...
DAY_ITINERARY:
Day 1 - [Theme]: Morning: [specific place from data + what to do there]. Afternoon: [specific place + activity]. Evening: [activity or place].
Day 2 - [Theme]: Morning: [place + activity]. Afternoon: [place + activity]. Evening: [activity].
[Continue for all {days} days using real place names from the places data]
BUDGET_BREAKDOWN: Flight:Rs.[X] | Hotel:Rs.[X×nights nights] | Food&Travel:Rs.[X] | TOTAL:Rs.[X]
TRAVEL_TIPS: [tip 1]; [tip 2]; [tip 3]; [tip 4]

Rules:
- FLIGHT: Pick the cheapest_flight from the flights tool result. If no direct route, say "Best connecting option via major hub"
- HOTEL: Pick the recommended hotel from the hotels tool result. Use its exact name, stars, price, amenities
- WEATHER: Use real forecast dates and temperatures from the weather tool result
- PLACES: Use actual place names from the places tool result for the day itinerary
- BUDGET: Calculate accurately: flight_price + (hotel_price × nights) + (daily_food × nights)
- Low budget daily food = Rs.800, Medium = Rs.1,500, High = Rs.3,000
- Write day themes that match the destination character (beach, heritage, mountains etc.)
- Be specific and practical, not generic

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


def _invoke_tool(name: str, payload: dict, thought_container=None) -> str:
    logger.info("Calling tool: %s", name)
    if thought_container:
        try:
            thought_container.markdown(f"🔍 Running `{name}`...")
        except Exception:
            pass
    tool_map = {t.name: t for t in ALL_TOOLS}
    return tool_map[name].invoke(payload)


def _extract_costs(flights_raw: str, hotels_raw: str) -> tuple[float, float]:
    flight_cost = 0.0
    hotel_cost = 0.0
    try:
        data = json.loads(flights_raw)
        f = data.get("cheapest_flight") or data.get("fastest_flight") or {}
        flight_cost = float(f.get("price", 0) or 0)
    except Exception:
        logger.warning("Could not parse flight cost")
    try:
        data = json.loads(hotels_raw)
        h = data.get("recommended") or data.get("cheapest") or {}
        hotel_cost = float(h.get("price_per_night", 0) or 0)
    except Exception:
        logger.warning("Could not parse hotel cost")
    return flight_cost, hotel_cost


def _build_fallback(source, destination, days, budget_level, tool_results):
    """Deterministic fallback itinerary when LLM call fails."""
    dest_key = destination.lower()
    fb = DESTINATION_FALLBACKS.get(dest_key, {})
    profile = BUDGET_PROFILES.get(budget_level, BUDGET_PROFILES["Medium"])

    flight = FALLBACK_FLIGHTS.get(
        (source.lower(), dest_key),
        f"Best available flight from {source} to {destination}"
    )
    hotel = "Recommended central hotel | 4 star | Rs.3,500/night | Hotel | Amenities: wifi, breakfast"
    weather_str = " | ".join(
        f"Day{i+1}: Partly cloudy {32-i}C/24C" for i in range(days)
    )
    places = fb.get("places", [f"{destination} city centre", "local market", "heritage site",
                                "scenic viewpoint", "food street", "cultural landmark"])
    themes = fb.get("themes", ["Arrival & Orientation", "Local Highlights", "Culture & Food"])
    tips = fb.get("tips", ["Keep digital copies of all bookings",
                           "Start sightseeing early to avoid crowds",
                           "Confirm local transport fares before boarding"])

    # Override with real tool data where available
    try:
        wd = json.loads(tool_results.get("weather", "{}")).get("forecast", [])
        if wd:
            weather_str = " | ".join(
                f"Day{i+1}:{w['date']} {w['condition']} {w['max_temp_c']}C/{w['min_temp_c']}C"
                for i, w in enumerate(wd[:days])
            )
    except Exception:
        pass

    try:
        fd = json.loads(tool_results.get("flights", "{}"))
        cf = fd.get("cheapest_flight") or fd.get("fastest_flight")
        if cf:
            flight = (f"{cf.get('airline','')} {cf.get('flight_id','')} | "
                      f"Rs.{float(cf.get('price',0)):,.0f} | "
                      f"Departs {cf.get('departure_display','TBD')} arrives {cf.get('arrival_display','TBD')} | "
                      f"Duration {cf.get('duration_hrs','?')}h")
    except Exception:
        pass

    try:
        hd = json.loads(tool_results.get("hotels", "{}"))
        rh = hd.get("recommended") or hd.get("cheapest")
        if rh:
            amenities = ", ".join(rh.get("amenities", [])) or "wifi, breakfast"
            hotel = (f"{rh.get('name','')} | {rh.get('stars', rh.get('rating', 4))} star | "
                     f"Rs.{float(rh.get('price_per_night',0)):,.0f}/night | "
                     f"{rh.get('type','Hotel')} | Amenities: {amenities}")
    except Exception:
        pass

    try:
        pd = json.loads(tool_results.get("places", "{}")).get("top_places", [])
        if pd:
            places = [p.get("name", "") for p in pd if p.get("name")] or places
    except Exception:
        pass

    # Budget
    fc_match = re.search(r"Rs\.([0-9,]+)", flight)
    hc_match = re.search(r"Rs\.([0-9,]+)/night", hotel)
    fc = float(fc_match.group(1).replace(",", "")) if fc_match else 5000
    hc = float(hc_match.group(1).replace(",", "")) if hc_match else 3500
    food = profile["daily_food_travel"] * days
    total = fc + hc * days + food
    budget_str = (f"Flight:Rs.{fc:,.0f} | Hotel:Rs.{hc*days:,.0f}({days}nights) | "
                  f"Food&Travel:Rs.{food:,.0f} | TOTAL:Rs.{total:,.0f}")

    # Try real budget tool data
    try:
        bd = json.loads(tool_results.get("budget", "{}")).get("formatted", {})
        if bd and not str(bd.get("flight", "")).endswith("0"):
            budget_str = (f"Flight:{bd.get('flight','')} | Hotel:{bd.get('hotel','')} | "
                          f"Food&Travel:{bd.get('food_and_travel','')} | TOTAL:{bd.get('total','')}")
    except Exception:
        pass

    day_lines = []
    for i in range(1, days + 1):
        p1 = places[(i - 1) % len(places)]
        p2 = places[i % len(places)]
        p3 = places[(i + 1) % len(places)]
        theme = themes[(i - 1) % len(themes)]
        day_lines.append(
            f"Day {i} - {theme}: Morning: Visit {p1} and explore the area. "
            f"Afternoon: Head to {p2} with time for local food. "
            f"Evening: Wind down at {p3} for dinner or a walk."
        )

    return "\n".join([
        f"TRIP_SUMMARY: {destination.title()} for {days} days - {budget_level} budget",
        f"FLIGHT_SELECTED: {flight}",
        f"HOTEL_SELECTED: {hotel}",
        f"WEATHER_FORECAST: {weather_str}",
        "DAY_ITINERARY:",
        "\n".join(day_lines),
        f"BUDGET_BREAKDOWN: {budget_str}",
        f"TRAVEL_TIPS: {'; '.join(tips)}",
    ])


# ── Main planning function ────────────────────────────────────────────────────

def plan_trip(source: str, destination: str, days: int,
              budget_level: str, thought_container=None) -> dict:
    """Run all tools then ask LLM to compose final itinerary. Returns structured result."""
    try:
        source = source.strip()
        destination = destination.strip()
        days = max(1, min(int(days), 7))
        profile = BUDGET_PROFILES.get(budget_level, BUDGET_PROFILES["Medium"])

        # ── Run all 5 tools ──
        flights = _invoke_tool("search_flights",
                               {"source": source, "destination": destination},
                               thought_container)
        hotels = _invoke_tool("search_hotels",
                              {"city": destination,
                               "max_price": profile["max_price"],
                               "min_rating": profile["min_rating"]},
                              thought_container)
        weather = _invoke_tool("get_weather",
                               {"city": destination, "days": days},
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
        prompt = ITINERARY_PROMPT.format(
            source=source,
            destination=destination,
            days=days,
            budget_level=budget_level,
            tool_results=json.dumps(tool_results, indent=2),
        )

        try:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise TravelPlanningError("GROQ_API_KEY not set")

            llm = ChatGroq(
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                temperature=0.15,
                api_key=api_key,
                max_retries=2,
                timeout=45,          # raised from 8s — LLM needs time for long output
                max_tokens=2048,
            )
            raw = llm.invoke(prompt).content

        except Exception as exc:
            logger.warning("LLM call failed (%s); using deterministic fallback", exc)
            raw = _build_fallback(source, destination, days, budget_level, tool_results)

        parsed = parse_itinerary(raw)
        return {"success": True, "raw": raw, "parsed": parsed}

    except Exception as exc:
        logger.exception("Trip planning failed")
        return {"success": False, "raw": str(exc), "parsed": {}}


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_itinerary(text: str) -> dict:
    """Parse structured agent output into a dict for the UI."""
    result = {
        "summary": "", "flight": "", "hotel": "",
        "weather": [], "days": [], "budget": {}, "tips": [],
    }

    # Strip LLM preamble like "Here is your itinerary:" or "Final Answer:"
    cleaned = re.sub(r"(?i)(here\s+is\s+.*?itinerary[:\s]*|final answer:\s*)", "", text or "").strip()
    lines = cleaned.splitlines()
    current_section = None
    day_lines = []

    for raw_line in lines:
        line = raw_line.strip().lstrip("- *#")
        if not line:
            continue

        if line.upper().startswith("TRIP_SUMMARY:"):
            result["summary"] = line.split(":", 1)[1].strip()
            current_section = None
        elif line.upper().startswith("FLIGHT_SELECTED:"):
            result["flight"] = line.split(":", 1)[1].strip()
            current_section = None
        elif line.upper().startswith("HOTEL_SELECTED:"):
            result["hotel"] = line.split(":", 1)[1].strip()
            current_section = None
        elif line.upper().startswith("WEATHER_FORECAST:"):
            raw_weather = line.split(":", 1)[1].strip()
            result["weather"].extend(
                item.strip() for item in raw_weather.split("|") if item.strip()
            )
            current_section = None
        elif line.upper().startswith("DAY_ITINERARY:"):
            current_section = "days"
        elif line.upper().startswith("BUDGET_BREAKDOWN:"):
            current_section = "budget"
            raw_budget = line.split(":", 1)[1].strip()
            for item in raw_budget.split("|"):
                if ":" in item:
                    k, v = item.split(":", 1)
                    result["budget"][k.strip()] = v.strip()
        elif line.upper().startswith("TRAVEL_TIPS:"):
            current_section = "tips"
            raw_tips = line.split(":", 1)[1].strip()
            if raw_tips:
                result["tips"].extend(
                    t.strip(" .") for t in re.split(r";|\n|(?<=\.)(?=\s[A-Z])", raw_tips) if t.strip()
                )
        elif current_section == "days" and re.match(r"^day\s*\d+", line, re.IGNORECASE):
            day_lines.append(line)
        elif current_section == "tips" and line:
            result["tips"].append(line)

    result["days"] = day_lines if day_lines else [cleaned]
    result["tips"] = [t for t in result["tips"] if len(t) > 8][:6]
    return result