"""Phase 4 tests: the LangGraph agent, its tool call limit, and follow-up requests.

A fake LLM returns scripted replies, so these tests decide exactly which tools the
"agent" asks for and never spend Groq or SerpApi quota."""
import json

import pytest
import requests
from langchain_core.messages import AIMessage

graph = pytest.importorskip("agent.graph", reason="langgraph cannot be imported in this environment",
                            exc_type=ImportError)

from agent import travel_agent  # noqa: E402
from agent.travel_agent import plan_trip, revise_trip  # noqa: E402
from tools.flight_tool import search_flights  # noqa: E402

ITINERARY = """TRIP_SUMMARY: anything
FLIGHT_SELECTED: Fake Air 999 | Rs.1 per person
HOTEL_SELECTED: Made Up Palace | Rs.1/night
WEATHER_FORECAST: Day1:2026-11-02 Snow -40C/-50C
DAY_ITINERARY:
Day 1 - Arrival: Morning: Check in. Afternoon: Walk around. Evening: Dinner.
Day 2 - Explore: Morning: Fort. Afternoon: Market. Evening: Beach.
Day 3 - Departure: Morning: Breakfast. Afternoon: Shopping. Evening: Fly home.
BUDGET_BREAKDOWN: Flight:Rs.1 | Hotel:Rs.1 | TOTAL:Rs.1
TRAVEL_TIPS: Carry sunscreen for the beach days; Book the fort tickets online"""

RELAXED_ITINERARY = ITINERARY.replace("Day 2 - Explore: Morning: Fort. Afternoon: Market. Evening: Beach.",
                                      "Day 2 - Slow Day: Morning: Sleep in. Afternoon: Spa. Evening: Sunset.")


class FakeLLM:
    """Stands in for ChatGroq. bind_tools() gives the agent model, which returns the
    scripted replies in order; the plain model returns the itinerary text."""

    def __init__(self, script: dict, with_tools: bool = False):
        self.script, self.with_tools = script, with_tools

    def bind_tools(self, tools):
        self.script["tool_names"] = [t.name for t in tools]
        return FakeLLM(self.script, with_tools=True)

    def invoke(self, messages):
        if self.with_tools:
            self.script["agent_calls"] += 1
            if self.script.get("agent_error"):
                raise RuntimeError("Groq is down")
            replies = self.script["agent"]
            return replies.pop(0) if replies else AIMessage(content="Nothing else to change.")
        self.script["writer_prompts"].append(messages)
        return AIMessage(content=self.script["itinerary"])


def use_fake_llm(monkeypatch, agent_replies=(), itinerary=ITINERARY, **extra) -> dict:
    script = {"agent": list(agent_replies), "itinerary": itinerary, "agent_calls": 0,
              "writer_prompts": [], **extra}
    monkeypatch.setattr(travel_agent, "llm_available", lambda: True)
    monkeypatch.setattr(travel_agent, "make_llm", lambda **kwargs: FakeLLM(script))
    return script


def tool_call(name: str, call_id: str = "call_1", **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def count_tools(monkeypatch) -> list:
    """Record every tool the planner runs (the tool still runs normally)."""
    calls = []
    real = travel_agent._invoke_tool

    def counting(name, payload, thought_container=None):
        calls.append(name)
        return real(name, payload, thought_container)

    monkeypatch.setattr(travel_agent, "_invoke_tool", counting)
    return calls


# ── Mocked SerpApi that reacts to the request ────────────────────────────────

EMPTY = {"search_metadata": {"status": "Success"},
         "error": "Google hasn't returned any results for this query."}


def hotel(name, stars, price):
    return {"name": name, "extracted_hotel_class": stars, "overall_rating": 4.2,
            "rate_per_night": {"extracted_lowest": price, "extracted_before_taxes_fees": price - 300}}


class FakeResponse:
    status_code, ok = 200, True

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def fake_serpapi(monkeypatch, hotels: list, cheap_hotels: list | None = None) -> list:
    """Flights: none for any search touching KUU (Manali), otherwise one flight.
    Hotels: `hotels`, or `cheap_hotels` when the request sends max_price."""
    calls = []
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    def fake_get(url, params=None, timeout=None):
        if "serpapi" not in url:
            raise requests.ConnectionError("no network in tests")
        calls.append(dict(params))
        if params["engine"] == "google_hotels":
            chosen = cheap_hotels if "max_price" in params and cheap_hotels is not None else hotels
            return FakeResponse({"properties": chosen})
        if "KUU" in (params["departure_id"], params["arrival_id"]):
            return FakeResponse(EMPTY)
        return FakeResponse({"best_flights": [{
            "flights": [{"departure_airport": {"id": params["departure_id"], "time": f"{params['outbound_date']} 07:00"},
                         "arrival_airport": {"id": params["arrival_id"], "time": f"{params['outbound_date']} 09:00"},
                         "duration": 120, "airline": "IndiGo", "flight_number": "6E 100"}],
            "layovers": [], "total_duration": 120, "price": 5000,
        }]})

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


# ── Graph shape ──────────────────────────────────────────────────────────────

def test_graph_has_the_expected_steps():
    nodes = set(graph.build_graph().get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"gather", "agent", "tools", "budget", "write"}


# ── New plans ────────────────────────────────────────────────────────────────

def test_no_problems_means_no_extra_llm_call(monkeypatch):
    script = use_fake_llm(monkeypatch)
    result = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")
    assert result["success"] and result["mode"] == "ai"
    assert script["agent_calls"] == 0          # gather went straight to budget
    assert len(script["writer_prompts"]) == 1
    assert result["agent_notes"] == []


def test_budget_and_facts_never_come_from_the_llm(monkeypatch):
    use_fake_llm(monkeypatch)  # the fake itinerary contains made-up prices and weather
    result = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")
    parsed = result["parsed"]
    assert parsed["budget"]["TOTAL"] != "Rs.1" and "Fake Air" not in parsed["flight"]
    assert "Made Up Palace" not in parsed["hotel"]
    assert not any("Snow" in item for item in parsed["weather"])
    assert parsed["days"][1].startswith("Day 2 - Explore")  # the day plan does come from the LLM


def test_missing_flight_tries_a_nearby_airport(monkeypatch):
    calls = fake_serpapi(monkeypatch, hotels=[hotel("Snow Peak", 4, 3900)])
    script = use_fake_llm(monkeypatch, agent_replies=[
        tool_call("find_nearby_airports", city="Manali"),
        tool_call("search_flights", "call_2", source="Delhi", destination="Manali", to_airport="IXC"),
        AIMessage(content="The return leg has no flights nearby either; train or road is needed."),
    ])
    result = plan_trip("Delhi", "Manali", 3, "Medium", start_date="2026-11-02")
    parsed = result["parsed"]

    assert "find_nearby_airports" in script["tool_names"] and "estimate_budget" not in script["tool_names"]
    assert "Arrives at Chandigarh (IXC), about 300 km by road to Manali" in parsed["flight"]
    assert "Train or road travel is needed" in parsed["return_flight"]   # still no return flight
    assert any("Looked up airports near Manali" in note for note in result["agent_notes"])
    assert any("Delhi to Manali (to IXC): found 1 options" in note for note in result["agent_notes"])
    assert len(calls) == 4                     # 3 standard searches + 1 nearby-airport search
    assert result["parsed"]["budget"]["Flight"].startswith("Rs.5,000")  # outbound only


def test_live_no_results_is_reported_not_replaced_by_sample_data(monkeypatch):
    fake_serpapi(monkeypatch, hotels=[])
    data = json.loads(search_flights.invoke({"source": "Delhi", "destination": "Manali",
                                              "travel_date": "2026-11-02"}))
    assert data["found"] is False and data["data_source"] == "live"
    assert [a["code"] for a in data["nearby_airports"]["Manali"]] == ["KUU", "IXC", "DEL"]


def test_hotel_over_budget_searches_again_with_lower_price(monkeypatch):
    calls = fake_serpapi(monkeypatch,
                         hotels=[hotel("Sea Palace", 4, 6000), hotel("Beach Resort", 3, 4800)],
                         cheap_hotels=[hotel("Budget Inn", 2, 2100)])
    use_fake_llm(monkeypatch, agent_replies=[
        tool_call("search_hotels", city="Goa", max_price=2500, strict_max_price=True),
    ])
    result = plan_trip("Delhi", "Goa", 3, "Low", start_date="2026-11-02")

    hotel_calls = [c for c in calls if c["engine"] == "google_hotels"]
    assert len(hotel_calls) == 2 and hotel_calls[1]["max_price"] == 2500
    assert result["parsed"]["hotel"].startswith("Budget Inn")
    assert result["parsed"]["budget"]["Hotel"].startswith("Rs.4,200 (1 room x 2 nights")
    assert any("chose Budget Inn at Rs.2,100 per night" in note for note in result["agent_notes"])


def test_tool_call_limit_stops_a_looping_agent(monkeypatch):
    fake_serpapi(monkeypatch, hotels=[hotel("Sea Palace", 4, 6000)])
    looping = [AIMessage(content="", tool_calls=[
        {"name": "search_places", "args": {"city": "Goa"}, "id": f"call_{i}_{j}"} for j in range(3)
    ]) for i in range(10)]
    script = use_fake_llm(monkeypatch, agent_replies=looping)
    monkeypatch.setenv("AGENT_MAX_TOOL_CALLS", "4")
    result = plan_trip("Delhi", "Goa", 3, "Low", start_date="2026-11-02")

    assert result["success"]
    assert sum("Looked up places" in note for note in result["agent_notes"]) == 4
    assert result["agent_notes"][-1] == "Stopped after 4 extra searches (the limit for one request)."
    assert script["agent_calls"] == 2  # 3 calls, then 1 more call and the limit is reached


def test_agent_failure_still_finishes_the_plan(monkeypatch):
    fake_serpapi(monkeypatch, hotels=[hotel("Sea Palace", 4, 6000)])
    use_fake_llm(monkeypatch, agent_error=True)
    result = plan_trip("Delhi", "Goa", 3, "Low", start_date="2026-11-02")
    assert result["success"] and result["mode"] == "ai"
    assert "The agent could not run, so no extra searches were made." in result["agent_notes"]


def test_offline_plan_skips_the_agent(monkeypatch):
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    monkeypatch.setattr(travel_agent, "make_llm", lambda **kw: pytest.fail("no LLM when offline"))
    fake_serpapi(monkeypatch, hotels=[hotel("Sea Palace", 4, 6000)])  # over budget for Low
    result = plan_trip("Delhi", "Goa", 3, "Low", start_date="2026-11-02")
    assert result["success"] and result["mode"] == "offline" and result["agent_notes"] == []


# ── Follow-up requests ───────────────────────────────────────────────────────

def test_follow_up_cheaper_hotel_only_reruns_the_hotel_search(monkeypatch):
    calls = fake_serpapi(monkeypatch,
                         hotels=[hotel("Taj Exotica", 5, 6500), hotel("Casa Calangute", 3, 3200)],
                         cheap_hotels=[hotel("Casa Calangute", 3, 3200)])
    use_fake_llm(monkeypatch)
    first = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")
    assert first["parsed"]["hotel"].startswith("Taj Exotica")

    tools_run = count_tools(monkeypatch)
    before = len(calls)
    use_fake_llm(monkeypatch, agent_replies=[
        tool_call("search_hotels", city="Goa", max_price=4000, strict_max_price=True),
    ])
    second = revise_trip(first, "find a cheaper hotel")

    assert second["success"] and second["parsed"]["hotel"].startswith("Casa Calangute")
    assert tools_run == ["search_hotels", "estimate_budget"]   # flights, weather, places reused
    assert len(calls) == before + 1                             # one SerpApi search
    assert "Hotel: Taj Exotica -> Casa Calangute" in second["changes"]
    assert any(line.startswith("Estimated total: ") for line in second["changes"])


def test_follow_up_about_the_day_plan_runs_no_tools(monkeypatch):
    use_fake_llm(monkeypatch)
    first = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")

    tools_run = count_tools(monkeypatch)
    script = use_fake_llm(monkeypatch, agent_replies=[AIMessage(content="No searches needed.")],
                          itinerary=RELAXED_ITINERARY)
    second = revise_trip(first, "make day 2 more relaxed")

    assert tools_run == ["estimate_budget"]   # only the code budget, no searches
    prompt = script["writer_prompts"][0]
    assert "CHANGE REQUEST FROM THE TRAVELLER: make day 2 more relaxed" in prompt
    assert "Day 2 - Explore" in prompt         # the writer sees the current plan
    assert second["parsed"]["days"][1].startswith("Day 2 - Slow Day")
    assert second["parsed"]["budget"] == first["parsed"]["budget"]
    assert second["changes"] == ["Day-by-day plan updated"]


def test_follow_up_needs_the_llm(monkeypatch):
    use_fake_llm(monkeypatch)
    first = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    answer = revise_trip(first, "find a cheaper hotel")
    assert answer["success"] is False and "GROQ_API_KEY" in answer["raw"]


def test_app_follow_up_chat(monkeypatch):
    import streamlit
    from streamlit.testing.v1 import AppTest

    if tuple(int(p) for p in streamlit.__version__.split(".")[:2]) < (1, 50):
        pytest.skip("AppTest in Streamlit < 1.50 mishandles segmented_control values")

    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-the-ui")  # the fake LLM below answers
    script = use_fake_llm(monkeypatch, itinerary=ITINERARY)
    at = AppTest.from_file("app.py", default_timeout=60).run()
    at.button(key="plan").click().run()
    assert not at.exception

    script["agent"].append(AIMessage(content="No searches needed."))
    script["itinerary"] = RELAXED_ITINERARY
    at.chat_input(key="follow_up").set_value("make day 2 more relaxed").run()
    assert not at.exception
    chat = at.session_state.chat
    assert [m["role"] for m in chat] == ["user", "assistant"]
    assert "Day-by-day plan updated" in chat[1]["content"]
    assert at.session_state.current_trip["result"]["parsed"]["days"][1].startswith("Day 2 - Slow Day")


def test_notes_and_notice_are_honest_when_nothing_fits_the_budget(monkeypatch):
    fake_serpapi(monkeypatch, hotels=[hotel("Sea Palace", 4, 6000)],
                 cheap_hotels=[hotel("Still Pricey", 3, 3100)])  # Google found nothing under 2,500
    use_fake_llm(monkeypatch, agent_replies=[
        tool_call("search_hotels", city="Goa", max_price=2500, strict_max_price=True),
    ])
    result = plan_trip("Delhi", "Goa", 3, "Low", start_date="2026-11-02")

    assert ("Searched hotels in Goa under Rs.2,500 per night: none found, the cheapest is "
            "Still Pricey at Rs.3,100 per night.") in result["agent_notes"]
    assert "No hotel matched the Low budget (up to Rs.2,500 per room per night" in result["notice"]


def test_failed_cheaper_search_keeps_the_current_hotel(monkeypatch):
    """Found in a real run: a search under Rs.800 that only found the same hotel
    must not replace the result or claim the hotel is outside the budget."""
    fake_serpapi(monkeypatch, hotels=[hotel("Royal Heritage", 5, 1232)],
                 cheap_hotels=[hotel("Royal Heritage", 5, 1232)])
    use_fake_llm(monkeypatch)
    first = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")
    assert "No hotel matched" not in first["notice"]

    use_fake_llm(monkeypatch, agent_replies=[
        tool_call("search_hotels", city="Goa", max_price=800, strict_max_price=True),
    ])
    second = revise_trip(first, "find a cheaper hotel")
    assert second["parsed"]["hotel"] == first["parsed"]["hotel"]
    assert "No hotel matched" not in second["notice"]
    assert second["parsed"]["budget"] == first["parsed"]["budget"]
    assert ("Searched hotels in Goa under Rs.800 per night: none found, the cheapest is "
            "Royal Heritage at Rs.1,232 per night.") in second["agent_notes"]

