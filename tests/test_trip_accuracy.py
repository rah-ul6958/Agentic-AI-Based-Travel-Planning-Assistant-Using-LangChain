"""Phase 1 accuracy tests: round trip, travellers, nights, hotel taxes, star class, weather."""
import json
from datetime import date, timedelta

import pytest
import requests

from agent import travel_agent
from agent.travel_agent import plan_trip
from services import live_travel_service, weather_service
from tools.budget_tool import estimate_budget
from tools.hotel_tool import search_hotels
from tools.weather_tool import get_weather
from utils.trip_math import (
    check_out_date,
    default_return_date,
    guests_per_room,
    hotel_nights,
    rooms_needed,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload, self.status_code, self.ok = payload, 200, True

    def json(self):
        return self._payload


def fake_serpapi(monkeypatch, payload, calls):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse(payload)

    monkeypatch.setattr(live_travel_service.requests, "get", fake_get)


def no_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("this test must not call the network")

    monkeypatch.setattr(requests, "get", fail)


# ── Round trip and travellers ────────────────────────────────────────────────

def test_round_trip_budget_multiplies_by_travellers():
    budget = json.loads(estimate_budget.invoke({
        "outbound_flight_price": 4000, "return_flight_price": 5000,
        "hotel_stay_price": 6000, "rooms": 1, "nights": 2, "days": 3,
        "travellers": 2, "daily_food_travel": 1500,
    }))
    assert budget["breakdown"]["flight"] == 18000          # 2 x (4,000 + 5,000)
    assert budget["breakdown"]["hotel_total"] == 6000      # 1 room for the whole stay
    assert budget["breakdown"]["food_and_local_travel"] == 9000  # 2 x 3 days x 1,500
    assert budget["grand_total"] == 33000
    assert "both ways" in budget["formatted"]["flight"]


def test_budget_hotel_uses_rooms_and_labels_missing_return():
    budget = json.loads(estimate_budget.invoke({
        "outbound_flight_price": 3000, "return_flight_price": 0,
        "hotel_stay_price": 5000, "rooms": 2, "nights": 2, "days": 3,
        "travellers": 3, "hotel_price_note": "excl. taxes",
    }))
    assert budget["breakdown"]["hotel_total"] == 10000
    assert "2 rooms x 2 nights, excl. taxes" in budget["formatted"]["hotel"]
    assert "no return flight found" in budget["formatted"]["flight"]


@pytest.mark.parametrize("travellers, rooms, per_room", [(1, 1, 1), (2, 1, 2), (3, 2, 2), (6, 3, 2)])
def test_rooms_for_travellers(travellers, rooms, per_room):
    assert rooms_needed(travellers) == rooms
    assert guests_per_room(travellers) == per_room


def test_plan_trip_round_trip_with_sample_data(monkeypatch):
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    no_network(monkeypatch)
    far_away = str(date.today() + timedelta(days=60))  # beyond the forecast, so no weather call
    result = plan_trip("Delhi", "Goa", 3, "Medium", start_date=far_away, travellers=2)

    parsed = result["parsed"]
    assert result["return_date"] == default_return_date(far_away, 3)
    assert parsed["return_flight"], "the return leg must be found in the sample data"
    assert result["nights"] == 2 and result["rooms"] == 1

    # Expected flight total = 2 travellers x (cheapest outbound + cheapest return), per person prices
    from tools.flight_tool import search_flights
    outbound = json.loads(search_flights.invoke({"source": "Delhi", "destination": "Goa"}))
    inbound = json.loads(search_flights.invoke({"source": "Goa", "destination": "Delhi"}))
    per_person = outbound["cheapest_flight"]["price"] + inbound["cheapest_flight"]["price"]

    budget = parsed["budget"]
    assert budget["Flight"] == f"Rs.{2 * per_person:,.0f} (2 x Rs.{per_person:,.0f}, both ways)"
    assert budget["Food&Travel"].startswith("Rs.9,000")  # 2 x 3 days x 1,500
    assert "1 room x 2 nights" in budget["Hotel"]
    assert "RETURN_FLIGHT_SELECTED" in result["raw"]


# ── Nights ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("days, nights", [(1, 1), (2, 1), (3, 2), (7, 6)])
def test_hotel_nights_is_days_minus_one(days, nights):
    assert hotel_nights(days) == nights


def test_dates_helpers():
    assert default_return_date("2026-10-10", 3) == "2026-10-12"
    assert default_return_date("2026-10-10", 1) == "2026-10-10"
    assert check_out_date("2026-10-10", 2) == "2026-10-12"


def test_live_hotel_search_uses_nights_rooms_and_total_with_taxes(monkeypatch):
    calls = []
    fake_serpapi(monkeypatch, {"properties": [{
        "name": "Sea Breeze", "extracted_hotel_class": 4, "overall_rating": 4.3,
        "rate_per_night": {"extracted_lowest": 4720, "extracted_before_taxes_fees": 4000},
        "total_rate": {"extracted_lowest": 9500, "extracted_before_taxes_fees": 8000},
    }]}, calls)
    data = json.loads(search_hotels.invoke({
        "city": "Goa", "max_price": 7000, "min_stars": 3,
        "check_in": "2026-11-01", "nights": 2, "travellers": 3,
    }))
    assert calls[0]["check_out_date"] == "2026-11-03"   # same nights as the budget
    assert calls[0]["adults"] == 2                       # guests per room
    assert data["rooms"] == 2
    hotel = data["recommended"]
    assert hotel["stay_price"] == 9500                   # total_rate for the entire trip
    assert hotel["price_per_night"] == 4720
    assert hotel["price_note"] == "incl. taxes"


# ── Hotel taxes and star class ───────────────────────────────────────────────

def test_hotel_price_without_taxes_is_labelled(monkeypatch):
    fake_serpapi(monkeypatch, {"properties": [{
        "name": "Budget Inn", "extracted_hotel_class": 3,
        "rate_per_night": {"extracted_before_taxes_fees": 2000},
    }]}, [])
    hotel = json.loads(search_hotels.invoke({"city": "Goa", "check_in": "2026-11-01", "nights": 3}))["recommended"]
    assert hotel["price_note"] == "excl. taxes"
    assert hotel["stay_price"] == 6000  # no total_rate, so nightly price x nights


def test_star_class_and_guest_rating_stay_separate(monkeypatch):
    fake_serpapi(monkeypatch, {"properties": [
        {"name": "No Class Guesthouse", "overall_rating": 4.8,
         "rate_per_night": {"extracted_lowest": 3000, "extracted_before_taxes_fees": 2700}},
        {"name": "Two Star Lodge", "extracted_hotel_class": 2, "overall_rating": 4.9,
         "rate_per_night": {"extracted_lowest": 1500, "extracted_before_taxes_fees": 1400}},
    ]}, [])
    data = json.loads(search_hotels.invoke({
        "city": "Goa", "max_price": 7000, "min_stars": 4, "check_in": "2026-11-01", "nights": 2,
    }))
    names = [h["name"] for h in data["all_options"]]
    assert names == ["No Class Guesthouse"]  # unknown class: filtered by price only
    hotel = data["recommended"]
    assert hotel["stars"] is None and hotel["guest_rating"] == 4.8  # not rounded into stars


# ── Weather ──────────────────────────────────────────────────────────────────

def test_weather_for_far_off_dates_is_not_invented(monkeypatch):
    no_network(monkeypatch)
    far_away = str(date.today() + timedelta(days=60))
    data = json.loads(get_weather.invoke({"city": "Goa", "days": 3, "start_date": far_away}))
    assert data["forecast"] == [] and data["available"] is False
    assert data["message"].startswith("Forecast not available yet")


def test_plan_trip_far_off_dates_shows_weather_message(monkeypatch):
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    no_network(monkeypatch)
    result = plan_trip("Delhi", "Goa", 3, "Low", start_date=str(date.today() + timedelta(days=90)))
    assert result["parsed"]["weather"] == []
    assert result["weather_message"].startswith("Forecast not available yet")


def test_weather_covers_only_days_within_forecast_range(monkeypatch):
    payload = {"daily": {
        "time": ["2026-10-17", "2026-10-18"], "weathercode": [0, 61],
        "temperature_2m_max": [31, 30], "temperature_2m_min": [24, 23], "precipitation_sum": [0, 4],
    }}
    monkeypatch.setattr("tools.weather_tool.fetch_weather", lambda *args: payload)
    data = json.loads(get_weather.invoke({"city": "Goa", "days": 4, "start_date": "2026-10-17"}))
    assert len(data["forecast"]) == 2
    assert "first 2 of 4 days" in data["message"]


def test_forecast_available_horizon():
    assert weather_service.forecast_available(str(date.today()))
    assert weather_service.forecast_available(str(weather_service.last_forecast_date()))
    assert not weather_service.forecast_available(
        str(weather_service.last_forecast_date() + timedelta(days=1)))


# ── Sidebar date sync ────────────────────────────────────────────────────────

def test_app_return_date_follows_days_and_travellers_input(monkeypatch):
    import streamlit
    from streamlit.testing.v1 import AppTest

    if tuple(int(p) for p in streamlit.__version__.split(".")[:2]) < (1, 50):
        pytest.skip("AppTest in Streamlit < 1.50 mishandles segmented_control values")

    monkeypatch.setenv("GROQ_API_KEY", "")
    at = AppTest.from_file("app.py", default_timeout=60).run()
    start = at.session_state.start_date

    at.slider(key="days").set_value(5).run()
    assert at.session_state.return_date == start + timedelta(days=4)

    at.date_input(key="return_date").set_value(start + timedelta(days=1)).run()
    assert at.session_state.days == 2

    at.number_input(key="travellers").set_value(3).run()
    at.button(key="plan").click().run()
    assert not at.exception
    trip = at.session_state.current_trip
    assert trip["meta"]["travellers"] == 3
    assert trip["result"]["rooms"] == 2 and trip["result"]["nights"] == 1
