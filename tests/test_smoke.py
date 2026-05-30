from agent.travel_agent import parse_itinerary
from tools.flight_tool import search_flights
from tools.hotel_tool import search_hotels


def test_parse_itinerary_sections():
    raw = """TRIP_SUMMARY: Goa for 3 days - Medium budget
FLIGHT_SELECTED: Sample flight
HOTEL_SELECTED: Sample hotel
WEATHER_FORECAST: Day1:Clear 30°/24°
DAY_ITINERARY:
Day 1 - Beach Day: Morning: Beach. Afternoon: Fort. Evening: Market.
BUDGET_BREAKDOWN: Flight:Rs.1,000 | Hotel:Rs.2,000 | TOTAL:Rs.3,000
TRAVEL_TIPS: Pack light. Carry ID."""
    parsed = parse_itinerary(raw)
    assert parsed["summary"].startswith("Goa")
    assert parsed["days"]
    assert parsed["budget"]["TOTAL"] == "Rs.3,000"


def test_tools_match_current_data_schema():
    flights = search_flights.invoke({"source": "Mumbai", "destination": "Goa"})
    hotels = search_hotels.invoke({"city": "Goa", "max_price": 6000, "min_rating": 3})
    assert "cheapest_flight" in flights
    assert "recommended" in hotels
