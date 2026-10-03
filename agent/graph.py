"""The planning agent, built as a LangGraph graph.

    START -> gather -> (agent <-> tools) -> budget -> write -> END

gather  Runs the five standard searches at the same time (new plans only).
agent   The LLM looks at the results, the problems the code found and any follow-up
        request, and decides which tools to call next - or that nothing is needed.
tools   Runs the tools the LLM asked for, keeps the useful results, and counts every
        call against a per-request limit so the agent cannot loop or burn quota.
budget  Recalculates the budget in code from the final flights and hotel.
write   The LLM writes the day-by-day plan (offline fallback if it is unavailable).

When there are no problems and no follow-up request, gather goes straight to budget,
so a normal plan costs no extra LLM call. Follow-up requests start at the agent and
reuse every earlier result, so only the tools that need to change are run again.
"""
import json
import logging
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent import travel_agent as core
from config.settings import BUDGET_PROFILES, get_int_setting
from utils.formatting import format_rupees

logger = logging.getLogger(__name__)

# The tools the LLM may call. The budget tool is not here: it always runs in code.
AGENT_TOOL_NAMES = ["search_flights", "search_hotels", "find_nearby_airports", "get_weather", "search_places"]

AGENT_PROMPT = """You are the planning agent of a travel app. The app has already run the standard
searches for this trip. Your job is to fix problems and handle the traveller's change request
by calling tools. You do not write the itinerary; another step does that after you finish.

Rules:
- Call only the tools that are needed. If nothing needs to change, reply with one short sentence and no tool calls.
- No outbound or return flight: call find_nearby_airports for the city that has no flights, then call
  search_flights again with the SAME source and destination city names and from_airport or to_airport
  set to a nearby airport code. If nearby airports also have nothing, stop: train or road travel is needed.
- Hotel over budget: call search_hotels with max_price at or below the budget limit and strict_max_price=true.
- Follow-up request: call only the tools the request affects (for example only search_hotels for
  "find a cheaper hotel"). Requests about the day plan itself (for example "make day 2 more relaxed") need no tools.
- Always use the trip's own city names for source, destination and city. Dates and travellers are filled in for you.
- Do not repeat a search that already failed with the same settings.
- You may make at most {max_calls} tool calls in total for this request. Never invent prices."""


class PlannerState(TypedDict, total=False):
    trip: dict                 # cities, dates, days, nights, travellers, budget level
    request: str               # follow-up request ("" for a new plan)
    previous: dict             # the previous itinerary, for follow-ups
    tool_results: dict         # latest raw JSON result for each part of the trip
    messages: Annotated[list, add_messages]  # the agent's conversation with the LLM
    tool_calls_used: int
    notes: list                # what the agent did, shown to the user
    result: dict               # the final result for the UI


def max_tool_calls() -> int:
    return max(get_int_setting("AGENT_MAX_TOOL_CALLS", 4), 0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_problems(trip: dict, tool_results: dict) -> list[str]:
    """Problems the code can see in the search results (no LLM needed)."""
    problems = []
    if not core._selected_flight(tool_results.get("flights", "")):
        problems.append(f"No outbound flight found from {trip['source']} to {trip['destination']} "
                        f"on {trip['start_date']}.")
    if not core._selected_flight(tool_results.get("return_flights", "")):
        problems.append(f"No return flight found from {trip['destination']} to {trip['source']} "
                        f"on {trip['return_date']}.")
    hotel = core._selected_hotel(tool_results.get("hotels", ""))
    limit = BUDGET_PROFILES[trip["budget_level"]]["max_price"]
    if not hotel:
        problems.append(f"No hotel found in {trip['destination']}.")
    elif hotel.get("price_per_night", 0) > limit:
        problems.append(f"The chosen hotel {hotel.get('name')} costs {format_rupees(hotel['price_per_night'])} "
                        f"per room per night, above the {trip['budget_level']} budget limit of "
                        f"{format_rupees(limit)}.")
    return problems


def _situation(state: PlannerState) -> str:
    """A short summary of the trip for the agent (short, to save LLM tokens)."""
    trip, results = state["trip"], state["tool_results"]
    limit = BUDGET_PROFILES[trip["budget_level"]]["max_price"]
    hotel = core._selected_hotel(results.get("hotels", ""))
    lines = [
        f"Trip: {trip['source']} to {trip['destination']}, {trip['start_date']} to {trip['return_date']} "
        f"({trip['days']} days, {trip['nights']} hotel nights), {trip['travellers']} traveller(s), "
        f"{trip['budget_level']} budget (hotel limit {format_rupees(limit)} per room per night).",
        "Current results:",
        "- Outbound flight: " + core.describe_flight(core._selected_flight(results.get("flights", "")),
                                                     trip["source"], trip["destination"]),
        "- Return flight: " + core.describe_flight(core._selected_flight(results.get("return_flights", "")),
                                                   trip["destination"], trip["source"]),
        "- Hotel: " + core.describe_hotel(hotel, trip["destination"]),
    ]
    problems = find_problems(trip, results)
    lines.append("Problems: " + (" ".join(problems) if problems else "none."))
    request = state.get("request")
    lines.append(f'Change request from the traveller: "{request}"' if request
                 else "This is a new plan: fix the problems above, if any.")
    lines.append(f"Tool calls left: {max_tool_calls() - state.get('tool_calls_used', 0)}")
    return "\n".join(lines)


def _complete_args(name: str, args: dict, trip: dict) -> dict:
    """Fill in the trip's dates and travellers so the LLM cannot change them by mistake."""
    args = dict(args or {})
    if name == "search_flights":
        returning = (args.get("source", "").strip().lower(), args.get("destination", "").strip().lower()) == \
            (trip["destination"].lower(), trip["source"].lower())
        args["travel_date"] = trip["return_date"] if returning else trip["start_date"]
        args["travellers"] = trip["travellers"]
    elif name == "search_hotels":
        profile = BUDGET_PROFILES[trip["budget_level"]]
        args["city"] = args.get("city") or trip["destination"]
        args.setdefault("max_price", profile["max_price"])
        args.setdefault("min_stars", profile["min_stars"])
        args.update(check_in=trip["start_date"], nights=trip["nights"], travellers=trip["travellers"])
    elif name == "get_weather":
        args.update(city=args.get("city") or trip["destination"], days=trip["days"],
                    start_date=trip["start_date"])
    elif name == "search_places":
        args["city"] = args.get("city") or trip["destination"]
    return args


def _slot_for(name: str, args: dict, trip: dict) -> str | None:
    """Which part of the trip a tool result belongs to (None = not part of this trip)."""
    source, destination = trip["source"].lower(), trip["destination"].lower()
    if name == "search_flights":
        route = (args.get("source", "").strip().lower(), args.get("destination", "").strip().lower())
        return {(source, destination): "flights", (destination, source): "return_flights"}.get(route)
    city = str(args.get("city", "")).strip().lower()
    slots = {"search_hotels": "hotels", "get_weather": "weather", "search_places": "places"}
    return slots.get(name) if city == destination else None


def _found(raw: str) -> bool:
    data = core._load(raw)
    return bool(data) and data.get("found") is not False and not data.get("error")


def _is_improvement(slot: str, old_raw: str, new_raw: str) -> bool:
    """Should a new tool result replace the current one for this part of the trip?"""
    if not _found(new_raw):
        return False
    if slot != "hotels" or not _found(old_raw):
        return True
    new = core._load(new_raw)
    if not new.get("relaxed_filters"):
        return True  # a hotel that fits the search's price cap
    # Nothing fitted the cap: only switch if the fallback hotel is actually cheaper
    old_price = core._selected_hotel(old_raw).get("price_per_night", 0)
    return core._selected_hotel(new_raw).get("price_per_night", 0) < old_price


def _summary_for_llm(name: str, raw: str) -> str:
    """Short tool result for the agent (full JSON would waste LLM tokens)."""
    data = core._load(raw)
    if data.get("error"):
        return f"Error: {data['error']}"
    if name == "search_flights":
        if data.get("found") is False:
            nearby = {city: [a["code"] for a in airports] for city, airports in data.get("nearby_airports", {}).items()}
            return f"No flights found. {data.get('message', '')} Nearby airports: {nearby}"
        return (f"Found {data.get('all_options_count', 0)} flights. Cheapest: "
                f"{core.describe_flight(data.get('cheapest_flight', {}))}")
    if name == "search_hotels":
        if data.get("found") is False:
            return f"No hotels found. {data.get('message', '')}"
        still_over = " (nothing matched the budget, so this is the cheapest)" if data.get("relaxed_filters") else ""
        return f"Recommended: {core.describe_hotel(data.get('recommended', {}))}{still_over}"
    if name == "get_weather":
        return data.get("message") or f"Forecast for {len(data.get('forecast', []))} days."
    if name == "search_places":
        return "Places: " + ", ".join(p.get("name", "") for p in data.get("top_places", []))
    return json.dumps(data, ensure_ascii=False)[:800]


def _describe_step(name: str, args: dict, raw: str, slot: str | None) -> str:
    """One line for the user about what the agent did. Numbers come from tool data."""
    data = core._load(raw)
    if name == "find_nearby_airports":
        codes = ", ".join(a["code"] for a in data.get("nearby", [])) or "none listed"
        return f"Looked up airports near {args.get('city')}: {codes}."
    if name == "search_flights":
        airports = " and ".join(filter(None, [
            f"from {args['from_airport']}" if args.get("from_airport") else "",
            f"to {args['to_airport']}" if args.get("to_airport") else "",
        ]))
        route = f"{args.get('source')} to {args.get('destination')}" + (f" ({airports})" if airports else "")
        if not _found(raw):
            text = f"Searched flights {route}: no flights found."
        else:
            cheapest = data.get("cheapest_flight", {})
            text = (f"Searched flights {route}: found {data.get('all_options_count', 0)} options, "
                    f"cheapest {format_rupees(cheapest.get('price', 0))} per person.")
    elif name == "search_hotels":
        if not _found(raw):
            text = f"Searched hotels in {args.get('city')} under {format_rupees(args.get('max_price', 0))}: none found."
        else:
            hotel = data.get("recommended", {})
            price = format_rupees(hotel.get("price_per_night", 0))
            if data.get("relaxed_filters"):
                # Nothing was under the limit, so the tool fell back to the cheapest hotel
                text = (f"Searched hotels in {args.get('city')} under {format_rupees(args.get('max_price', 0))} "
                        f"per night: none found, the cheapest is {hotel.get('name')} at {price} per night.")
            else:
                text = (f"Searched hotels in {args.get('city')} under {format_rupees(args.get('max_price', 0))} "
                        f"per night: chose {hotel.get('name')} at {price} per night.")
    elif name == "get_weather":
        text = f"Refreshed the weather for {args.get('city')}."
    else:
        text = f"Looked up places in {args.get('city')}."
    if slot is None:
        text += " (Not used: it does not match this trip.)"
    return text


# ── Nodes ─────────────────────────────────────────────────────────────────────

def gather(state: PlannerState, config) -> dict:
    thought_container = (config.get("configurable") or {}).get("thought_container")
    return {"tool_results": core.run_searches(state["trip"], thought_container)}


def agent(state: PlannerState) -> dict:
    new_messages = []
    if not state.get("messages"):
        new_messages = [SystemMessage(AGENT_PROMPT.format(max_calls=max_tool_calls())),
                        HumanMessage(_situation(state))]
    try:
        tools = [core.TOOL_MAP[name] for name in AGENT_TOOL_NAMES]
        model = core.make_llm(max_tokens=1024).bind_tools(tools)
        reply = model.invoke(list(state.get("messages", [])) + new_messages)
    except Exception as exc:
        # The plan still finishes with the results we already have
        logger.warning("Agent step failed (%s); finishing without more searches", type(exc).__name__)
        reply = AIMessage(content="")
        notes = list(state.get("notes", [])) + ["The agent could not run, so no extra searches were made."]
        return {"messages": new_messages + [reply], "notes": notes}
    return {"messages": new_messages + [reply]}


def tools(state: PlannerState) -> dict:
    trip = state["trip"]
    results = dict(state["tool_results"])
    used = state.get("tool_calls_used", 0)
    notes = list(state.get("notes", []))
    replies = []

    for call in state["messages"][-1].tool_calls:
        if used >= max_tool_calls():
            replies.append(ToolMessage("Not run: the tool call limit for this request was reached.",
                                       tool_call_id=call["id"]))
            continue
        used += 1  # every attempt counts, even a bad one, so the agent cannot loop forever
        name = call["name"]
        if name not in AGENT_TOOL_NAMES:
            replies.append(ToolMessage(f"Unknown tool: {name}", tool_call_id=call["id"]))
            continue
        args = _complete_args(name, call.get("args", {}), trip)
        try:
            raw = core._invoke_tool(name, args)
        except Exception as exc:  # for example arguments of the wrong type
            replies.append(ToolMessage(f"Tool error: {type(exc).__name__}", tool_call_id=call["id"]))
            continue

        slot = _slot_for(name, args, trip)
        # Keep a new result only when it found something better than what we have
        if slot and _is_improvement(slot, results.get(slot, ""), raw):
            results[slot] = raw
        notes.append(_describe_step(name, args, raw, slot if name != "find_nearby_airports" else "info"))
        replies.append(ToolMessage(_summary_for_llm(name, raw), tool_call_id=call["id"]))

    if used >= max_tool_calls():
        notes.append(f"Stopped after {max_tool_calls()} extra searches (the limit for one request).")
    return {"tool_results": results, "tool_calls_used": used, "notes": notes, "messages": replies}


def budget(state: PlannerState) -> dict:
    results = dict(state["tool_results"])
    results["budget"] = core.compute_budget(state["trip"], results)
    return {"tool_results": results}


def write(state: PlannerState) -> dict:
    parsed, mode, notice = core.write_itinerary(state["trip"], state["tool_results"],
                                                state.get("request", ""), state.get("previous"))
    result = core.build_result(state["trip"], state["tool_results"], parsed, mode, notice,
                               state.get("notes", []))
    return {"result": result}


# ── Routing (the arrows of the graph) ─────────────────────────────────────────

def route_start(state: PlannerState) -> str:
    # Follow-ups already have results, so they skip the standard searches
    return "agent" if state.get("tool_results") else "gather"


def route_after_gather(state: PlannerState) -> str:
    if core.llm_available() and max_tool_calls() > 0 and find_problems(state["trip"], state["tool_results"]):
        return "agent"
    return "budget"


def route_after_agent(state: PlannerState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None) and state.get("tool_calls_used", 0) < max_tool_calls():
        return "tools"
    return "budget"


def route_after_tools(state: PlannerState) -> str:
    return "agent" if state.get("tool_calls_used", 0) < max_tool_calls() else "budget"


def build_graph():
    graph = StateGraph(PlannerState)
    graph.add_node("gather", gather)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("budget", budget)
    graph.add_node("write", write)

    graph.add_conditional_edges(START, route_start, {"gather": "gather", "agent": "agent"})
    graph.add_conditional_edges("gather", route_after_gather, {"agent": "agent", "budget": "budget"})
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "budget": "budget"})
    graph.add_conditional_edges("tools", route_after_tools, {"agent": "agent", "budget": "budget"})
    graph.add_edge("budget", "write")
    graph.add_edge("write", END)
    return graph.compile()


_planner = None


def run_graph(trip: dict, request: str = "", previous: dict | None = None,
              tool_results: dict | None = None, thought_container=None) -> dict:
    global _planner
    if _planner is None:
        _planner = build_graph()
    state = {"trip": trip, "request": request, "previous": previous or {},
             "tool_results": dict(tool_results or {}), "tool_calls_used": 0, "notes": []}
    # recursion_limit is a second safety net on top of the tool call limit
    final = _planner.invoke(state, config={"recursion_limit": 30,
                                           "configurable": {"thought_container": thought_container}})
    return final["result"]
