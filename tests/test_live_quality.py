"""Phase 2 tests: parallel tools, freshness labels, price insights, booking options."""
import json
import threading
import time
from datetime import datetime, timedelta

import pytest
import requests

from agent import travel_agent
from agent.travel_agent import plan_trip
from components.itinerary import booking_options_html
from services.live_travel_service import fetch_booking_options
from tools.flight_tool import search_flights
from tools.hotel_tool import search_hotels
from utils.formatting import IST, freshness_label, price_insight_text

FLIGHTS = {
    "best_flights": [{
        "flights": [{
            "departure_airport": {"id": "DEL", "time": "2026-11-02 06:10"},
            "arrival_airport": {"id": "GOX", "time": "2026-11-02 08:45"},
            "duration": 155, "airline": "IndiGo", "flight_number": "6E 2031",
        }],
        "layovers": [], "total_duration": 155, "price": 5421, "booking_token": "TOKEN-6E2031",
    }],
    "price_insights": {"lowest_price": 5421, "price_level": "low",
                       "typical_price_range": [6000, 8500], "price_history": [[1, 2], [3, 4]]},
}
HOTELS = {"properties": [{
    "name": "Casa Calangute", "extracted_hotel_class": 3, "overall_rating": 4.1,
    "rate_per_night": {"extracted_lowest": 3200, "extracted_before_taxes_fees": 2900},
}]}
BOOKING = {"booking_options": [
    {"together": {"book_with": "IndiGo", "price": 5421, "option_title": "Saver",
                  "booking_request": {"url": "https://www.google.com/travel/clk/f",
                                      "post_data": "u=abc%26def&x=1"}}},
    {"together": {"book_with": "MakeMyTrip", "price": 5590,
                  "booking_request": {"url": "https://www.google.com/travel/clk/f", "post_data": "u=zzz"}}},
    {"together": {"price": 1}},  # no seller name: skipped
]}


class FakeResponse:
    def __init__(self, payload):
        self._payload, self.status_code, self.ok = payload, 200, True

    def json(self):
        return self._payload


def fake_api(monkeypatch, calls: list):
    """SerpApi answers come from the dicts above; any other URL (weather) is offline."""
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    def fake_get(url, params=None, timeout=None):
        if "serpapi" not in url:
            raise requests.ConnectionError("no network in tests")
        calls.append(dict(params))
        if params.get("booking_token"):
            return FakeResponse(BOOKING)
        return FakeResponse(FLIGHTS if params["engine"] == "google_flights" else HOTELS)

    monkeypatch.setattr(requests, "get", fake_get)


# ── Parallel tools ───────────────────────────────────────────────────────────

def test_searches_run_in_parallel_and_budget_runs_last(monkeypatch):
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    timeline = []
    lock = threading.Lock()

    def slow_tool(name, payload, thought_container=None):
        started = time.monotonic()
        if name != "estimate_budget":
            time.sleep(0.4)
        with lock:
            timeline.append((name, started, time.monotonic()))
        return "{}"

    monkeypatch.setattr(travel_agent, "_invoke_tool", slow_tool)
    started = time.monotonic()
    result = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")
    elapsed = time.monotonic() - started

    assert result["success"]
    assert len(timeline) == 6                      # 2 flight legs, hotels, weather, places, budget
    assert elapsed < 1.2                           # one after another would take 2.0 s
    budget_start = next(start for name, start, _ in timeline if name == "estimate_budget")
    assert budget_start >= max(end for name, _, end in timeline if name != "estimate_budget")


# ── Freshness ────────────────────────────────────────────────────────────────

def test_live_then_cached_freshness(monkeypatch):
    calls = []
    fake_api(monkeypatch, calls)
    first = json.loads(search_flights.invoke({"source": "Delhi", "destination": "Goa", "travel_date": "2026-11-02"}))
    second = json.loads(search_flights.invoke({"source": "Delhi", "destination": "Goa", "travel_date": "2026-11-02"}))
    hotels = json.loads(search_hotels.invoke({"city": "Goa", "check_in": "2026-11-02", "nights": 2}))

    assert first["from_cache"] is False and abs(first["fetched_at"] - time.time()) < 5
    assert second["from_cache"] is True and second["fetched_at"] == first["fetched_at"]
    assert hotels["data_source"] == "live" and hotels["from_cache"] is False
    assert len(calls) == 2  # the repeated flight search came from the cache


def test_freshness_labels():
    fetched = datetime(2026, 11, 2, 4, 30, tzinfo=IST).timestamp()
    assert freshness_label(None) == "Sample data"
    assert freshness_label({"data_source": "sample"}) == "Sample data"
    assert freshness_label({"data_source": "live", "fetched_at": fetched}) == "Live - fetched at 04:30 IST"
    cached = {"data_source": "live", "fetched_at": fetched, "from_cache": True}
    assert freshness_label(cached, now=fetched + 12 * 60 + 5) == "Cached - 12 min ago"
    assert freshness_label(cached, now=fetched + 20) == "Cached - less than 1 min ago"


def test_plan_trip_reports_freshness_per_card(monkeypatch):
    calls = []
    fake_api(monkeypatch, calls)
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    result = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")
    freshness = result["freshness"]
    assert set(freshness) == {"flights", "return_flights", "hotels"}
    assert all(item["data_source"] == "live" for item in freshness.values())
    # Outbound and return are different searches, so both are fresh on the first plan
    assert not any(item["from_cache"] for item in freshness.values())

    again = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")
    assert all(item["from_cache"] for item in again["freshness"].values())
    assert len(calls) == 3  # the second plan was served entirely from the cache


def test_sample_data_freshness_and_no_booking(monkeypatch):
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    result = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")
    assert {freshness_label(item) for item in result["freshness"].values()} == {"Sample data"}
    assert result["booking"] == {}
    assert result["price_insights"] == {"flights": {}, "return_flights": {}}


# ── Price insights ───────────────────────────────────────────────────────────

def test_price_insights_are_passed_through(monkeypatch):
    fake_api(monkeypatch, [])
    data = json.loads(search_flights.invoke({"source": "Delhi", "destination": "Goa", "travel_date": "2026-11-02"}))
    assert data["price_insights"] == {"lowest_price": 5421, "price_level": "low",
                                      "typical_price_range": [6000, 8500]}  # price_history dropped


@pytest.mark.parametrize("insights, text", [
    ({"price_level": "low", "typical_price_range": [6000, 8500]},
     "Prices are lower than usual for this route (usually Rs.6,000-Rs.8,500 per person)"),
    ({"price_level": "typical"}, "Prices are typical for this route"),
    ({"price_level": "high"}, "Prices are higher than usual for this route"),
    ({"price_level": "unusual"}, "Google price level: unusual"),
    ({}, ""),
    (None, ""),
])
def test_price_insight_text(insights, text):
    assert price_insight_text(insights) == text


# ── Booking options ──────────────────────────────────────────────────────────

def test_booking_options_are_fetched_only_on_demand(monkeypatch):
    calls = []
    fake_api(monkeypatch, calls)
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    result = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")

    assert not any("booking_token" in call for call in calls)  # planning never fetches sellers
    booking = result["booking"]["flights"]
    assert booking["token"] == "TOKEN-6E2031"
    assert booking["search"] == {"departure_id": "DEL", "arrival_id": "GOI,GOX", "outbound_date": "2026-11-02"}

    before = len(calls)
    found = fetch_booking_options(booking["token"], **booking["search"])
    assert len(calls) == before + 1
    assert calls[-1]["booking_token"] == "TOKEN-6E2031" and calls[-1]["departure_id"] == "DEL"
    assert [o["seller"] for o in found["options"]] == ["IndiGo", "MakeMyTrip"]
    assert found["options"][0]["post_data"] == "u=abc%26def&x=1"


def test_booking_options_html_uses_post_forms():
    html = booking_options_html([
        {"seller": "IndiGo", "price": 5421, "option_title": "Saver",
         "url": "https://www.google.com/travel/clk/f", "post_data": "u=abc%26def&x=1"},
        {"seller": "<b>Odd</b>", "price": None, "url": "", "post_data": ""},
    ])
    assert html.count('method="post"') == 1 and 'target="_blank"' in html
    assert '<input type="hidden" name="u" value="abc&amp;def">' in html  # decoded, then escaped
    assert '<input type="hidden" name="x" value="1">' in html
    assert "Rs.5,421" in html and "Price on site" in html
    assert "<b>Odd</b>" not in html  # seller names are escaped


def test_app_booking_button_spends_one_search_only_when_clicked(monkeypatch):
    import streamlit
    from streamlit.testing.v1 import AppTest

    if tuple(int(p) for p in streamlit.__version__.split(".")[:2]) < (1, 50):
        pytest.skip("AppTest in Streamlit < 1.50 mishandles segmented_control values")

    calls = []
    fake_api(monkeypatch, calls)
    monkeypatch.setenv("GROQ_API_KEY", "")
    at = AppTest.from_file("app.py", default_timeout=60).run()
    at.button(key="plan").click().run()
    assert not at.exception
    after_plan = len(calls)
    assert after_plan == 3  # outbound flights + return flights + hotels
    assert not any("booking_token" in call for call in calls)

    at.button(key="booking_flights").click().run()
    assert not at.exception
    assert len(calls) == after_plan + 1
    assert "TOKEN-6E2031" in at.session_state.booking_options
