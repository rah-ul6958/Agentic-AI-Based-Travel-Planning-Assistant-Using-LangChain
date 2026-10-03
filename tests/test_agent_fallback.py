"""The app must still plan trips when LangGraph cannot be imported."""
from agent import travel_agent
from agent.travel_agent import AGENT_UNAVAILABLE, plan_trip, revise_trip


def test_plan_works_without_langgraph(monkeypatch):
    monkeypatch.setattr(travel_agent, "_load_graph", lambda: None)
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    result = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")

    assert result["success"] and len(result["parsed"]["days"]) == 3
    assert result["parsed"]["budget"]["TOTAL"].startswith("Rs.")
    assert AGENT_UNAVAILABLE in result["notice"]


def test_follow_up_explains_when_langgraph_is_missing(monkeypatch):
    monkeypatch.setattr(travel_agent, "_load_graph", lambda: None)
    monkeypatch.setattr(travel_agent, "llm_available", lambda: False)
    first = plan_trip("Delhi", "Goa", 3, "Medium", start_date="2026-11-02")

    monkeypatch.setattr(travel_agent, "llm_available", lambda: True)
    answer = revise_trip(first, "find a cheaper hotel")
    assert answer["success"] is False and answer["raw"] == AGENT_UNAVAILABLE
