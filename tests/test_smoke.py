import json

import pytest

from agent import travel_agent
from agent.travel_agent import parse_itinerary, plan_trip
from components.itinerary import parse_weather_item, split_day
from tools.flight_tool import search_flights
from tools.hotel_tool import search_hotels
from tools.places_tool import search_places
from utils.formatting import escape_html, format_duration


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


def test_parse_itinerary_handles_markdown_and_multiline_output():
    raw = """Here is your itinerary:
**TRIP_SUMMARY:** Jaipur for 2 days - Low budget
**DAY_ITINERARY:**
- **Day 1 - Royal Forts:** Morning: Amber Fort.
  Afternoon: City Palace. Evening: Johari Bazaar.
- Day 2 - Old City: Morning: Hawa Mahal. Afternoon: Jantar Mantar. Evening: Nahargarh Fort.
**TRAVEL_TIPS:**
1. Start fort visits early for cooler weather
2. Keep cash for local markets and stalls"""
    parsed = parse_itinerary(raw)
    assert parsed["summary"] == "Jaipur for 2 days - Low budget"
    assert len(parsed["days"]) == 2
    assert "City Palace" in parsed["days"][0]
    assert parsed["tips"][0] == "Start fort visits early for cooler weather"


def test_tools_match_current_data_schema():
    flights = search_flights.invoke({"source": "Mumbai", "destination": "Goa"})
    hotels = search_hotels.invoke({"city": "Goa", "max_price": 6000, "min_rating": 3})
    assert "cheapest_flight" in flights
    assert "recommended" in hotels


def test_connecting_flights_when_no_direct_route():
    data = json.loads(search_flights.invoke({"source": "Kolkata", "destination": "Goa"}))
    assert data["found"] and data["connecting"]
    flight = data["cheapest_flight"]
    assert flight["stops"] == 1 and flight["via"]
    assert flight["price"] == sum(leg["price"] for leg in flight["legs"])
    assert flight["layover_hrs"] >= 1


@pytest.mark.parametrize("city", ["Kerala", "Manali", "Chennai"])
def test_every_supported_destination_has_data(city):
    assert json.loads(search_hotels.invoke({"city": city}))["found"]
    assert json.loads(search_places.invoke({"city": city}))["found"]


def test_plan_trip_offline_fallback(monkeypatch):
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    result = plan_trip("Delhi", "Goa", 3, "Medium")
    assert result["success"] and result["mode"] == "offline"
    parsed = result["parsed"]
    assert len(parsed["days"]) == 3
    assert parsed["budget"]["TOTAL"].startswith("Rs.")
    assert "Non-stop" in parsed["flight"]


def test_display_helpers():
    title, theme, slots = split_day("Day 2 - Heritage: Morning: Fort. Afternoon: Museum. Evening: Dinner.", 2)
    assert (title, theme) == ("Day 2", "Heritage")
    assert [s for s, _ in slots] == ["Morning", "Afternoon", "Evening"]

    weather = parse_weather_item("Day1:2025-01-04 Clear sky 31C/24C")
    assert weather["condition"] == "Clear sky" and weather["temps"] == "31° / 24°C"

    assert escape_html("<b>$5</b>") == "&lt;b&gt;&#36;5&lt;/b&gt;"
    assert format_duration(1.5) == "1h 30m"


def test_app_popular_route_and_offline_plan(monkeypatch):
    import streamlit
    from streamlit.testing.v1 import AppTest

    if tuple(int(p) for p in streamlit.__version__.split(".")[:2]) < (1, 50):
        pytest.skip("AppTest in Streamlit < 1.50 mishandles segmented_control values")

    monkeypatch.setenv("GROQ_API_KEY", "")
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception

    at.button(key="route_1").click().run()  # Delhi -> Jaipur
    assert at.selectbox(key="source").value == "Delhi"
    assert at.selectbox(key="destination").value == "Jaipur"

    at.button(key="swap").click().run()
    assert at.selectbox(key="source").value == "Jaipur"

    at.button(key="plan").click().run()
    assert not at.exception
    assert at.session_state.current_trip["result"]["success"]
    assert at.expander, "day-by-day itinerary should render"
