import json

import requests

from agent import travel_agent
from agent.travel_agent import plan_trip
from services import live_travel_service
from tools.flight_tool import search_flights
from tools.hotel_tool import search_hotels

FLIGHTS_RESPONSE = {
    "best_flights": [{
        "flights": [{
            "departure_airport": {"name": "Indira Gandhi International", "id": "DEL", "time": "2026-10-05 06:10"},
            "arrival_airport": {"name": "Manohar International", "id": "GOX", "time": "2026-10-05 08:45"},
            "duration": 155, "airline": "IndiGo", "flight_number": "6E 2031",
        }],
        "layovers": [], "total_duration": 155, "price": 5421, "type": "One way",
    }],
    "other_flights": [{
        "flights": [
            {"departure_airport": {"id": "DEL", "time": "2026-10-05 09:00"},
             "arrival_airport": {"id": "BOM", "time": "2026-10-05 11:10"},
             "duration": 130, "airline": "Air India", "flight_number": "AI 805"},
            {"departure_airport": {"id": "BOM", "time": "2026-10-05 13:00"},
             "arrival_airport": {"id": "GOI", "time": "2026-10-05 14:10"},
             "duration": 70, "airline": "Air India", "flight_number": "AI 663"},
        ],
        "layovers": [{"duration": 110, "name": "Mumbai", "id": "BOM"}],
        "total_duration": 310, "price": 4890,
    }, {"flights": [], "price": 100}],  # malformed offer is skipped
}

HOTELS_RESPONSE = {
    "properties": [
        {"type": "hotel", "name": "Taj Fort Aguada", "rate_per_night": {"extracted_lowest": 18500},
         "extracted_hotel_class": 5, "overall_rating": 4.6, "amenities": ["Pool", "Spa"],
         "link": "https://example.com/taj"},
        {"type": "hotel", "name": "Casa Calangute", "rate_per_night": {"extracted_lowest": 3200},
         "extracted_hotel_class": 3, "overall_rating": 4.1, "amenities": ["Free Wi-Fi"]},
        {"type": "vacation rental", "name": "No Price Villa"},
    ]
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.ok = payload, status, status < 400

    def json(self):
        return self._payload


def enable_live(monkeypatch, responses: dict, calls: list | None = None):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    def fake_get(url, params=None, timeout=None):
        if calls is not None:
            calls.append(params)
        return FakeResponse(responses[params["engine"]])

    monkeypatch.setattr(live_travel_service.requests, "get", fake_get)


def test_live_flights_are_normalized(monkeypatch):
    calls = []
    enable_live(monkeypatch, {"google_flights": FLIGHTS_RESPONSE}, calls)
    data = json.loads(search_flights.invoke({"source": "Delhi", "destination": "Goa", "travel_date": "2026-10-05"}))

    assert data["data_source"] == "live" and data["all_options_count"] == 2
    assert calls[0]["departure_id"] == "DEL" and calls[0]["arrival_id"] == "GOI,GOX"
    assert calls[0]["outbound_date"] == "2026-10-05" and calls[0]["currency"] == "INR"

    cheapest = data["cheapest_flight"]
    assert cheapest["price"] == 4890 and cheapest["stops"] == 1 and cheapest["via"] == "BOM"
    assert cheapest["flight_id"] == "AI 805 + AI 663"
    fastest = data["fastest_flight"]
    assert fastest["airline"] == "IndiGo" and fastest["departure_display"] == "06:10"
    assert fastest["duration_hrs"] == 2.6


def test_live_hotels_respect_budget(monkeypatch):
    calls = []
    enable_live(monkeypatch, {"google_hotels": HOTELS_RESPONSE}, calls)
    data = json.loads(search_hotels.invoke(
        {"city": "Goa", "max_price": 7000, "min_rating": 3, "check_in": "2026-10-05", "nights": 3}))

    assert data["data_source"] == "live"
    assert calls[0]["check_out_date"] == "2026-10-08"
    assert data["recommended"]["name"] == "Casa Calangute"  # Taj is over budget
    assert all(h["name"] != "No Price Villa" for h in data["all_options"])


def test_falls_back_to_sample_data_on_api_error(monkeypatch):
    enable_live(monkeypatch, {"google_flights": {"error": "Invalid API key."}})
    data = json.loads(search_flights.invoke({"source": "Mumbai", "destination": "Goa"}))
    assert data["found"] and data["data_source"] == "sample"
    assert "Invalid API key" in data["live_error"]


def test_network_failure_falls_back(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    def boom(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(live_travel_service.requests, "get", boom)
    data = json.loads(search_hotels.invoke({"city": "Goa"}))
    assert data["found"] and data["data_source"] == "sample"


def test_plan_trip_uses_live_prices(monkeypatch):
    enable_live(monkeypatch, {"google_flights": FLIGHTS_RESPONSE, "google_hotels": HOTELS_RESPONSE})
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    result = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-10-05")

    assert result["data_sources"] == {"flights": "live", "hotels": "live"}
    assert "AI 805" in result["parsed"]["flight"] and "Date 2026-10-05" in result["parsed"]["flight"]
    assert "Casa Calangute" in result["parsed"]["hotel"]
    # 4,890 flight + 3 x 3,200 hotel + 3 x 1,500 food
    assert result["parsed"]["budget"]["TOTAL"] == "Rs.18,990"
    assert result["links"]["flight"].startswith("https://www.google.com/travel/flights")
