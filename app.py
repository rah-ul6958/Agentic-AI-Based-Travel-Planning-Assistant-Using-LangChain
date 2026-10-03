import logging
import math
import threading
import time
from datetime import date, datetime, timedelta

import streamlit as st

from components.itinerary import render_result
from config.settings import (
    DESTINATION_INFO,
    MAX_TRAVELLERS,
    MAX_TRIP_DAYS,
    POPULAR_ROUTES,
    ROOT_DIR,
    SUPPORTED_CITIES,
    get_setting,
    groq_model,
    llm_available,
    load_environment,
    plan_limit,
)
from services.live_travel_service import live_data_enabled
from services.weather_service import fetch_weather, forecast_available, normalize_weather_payload
from utils.formatting import escape_html as esc
from utils.formatting import format_short_date
from utils.rate_limit import check_rate_limit

load_environment()

# Logs go to the console (and to "Manage app > Logs" on Streamlit Cloud).
# Code that logs API failures never includes API keys or request URLs.
logging.basicConfig(
    level=get_setting("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("voyance")

st.set_page_config(
    page_title="Voyance · AI Travel Planner",
    page_icon="🌏",
    layout="wide",
    initial_sidebar_state="auto",
)

BUDGET_LEVELS = ["Low", "Medium", "High"]
PROGRESS_STEPS = [
    ("✈️", "Searching flights"),
    ("🏨", "Finding hotels"),
    ("🌤️", "Fetching weather"),
    ("📍", "Discovering places"),
    ("💰", "Calculating budget"),
    ("🧭", "Composing itinerary"),
]


def load_css() -> str:  # not cached, so edits to theme.css apply on the next rerun
    return (ROOT_DIR / "styles" / "theme.css").read_text(encoding="utf-8")


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_live_weather(city: str, days: int = 5, start_date: str = "") -> dict:
    try:
        payload = fetch_weather(city, days, start_date)
        return normalize_weather_payload(city, payload, min(days, 7)) if payload else {}
    except Exception as exc:
        logger.warning("Sidebar weather request failed: %s", type(exc).__name__)
        return {}


def render_weather_live(city: str, days: int, start_date: str) -> None:
    forecast = []
    if forecast_available(start_date):
        forecast = fetch_live_weather(city, days, start_date).get("forecast", [])
        if not forecast:
            return
    pills = "".join(
        '<div class="weather-pill">'
        f'<div class="day-label">{esc(format_short_date(item["date"]))}</div>'
        f'<div class="pill-icon" title="{esc(item["condition"])}">{item.get("icon", "🌡️")}</div>'
        f'<div class="pill-temp">{item["max_temp_c"]:.0f}°<span>/{item["min_temp_c"]:.0f}°</span></div>'
        '</div>'
        for item in forecast[:days]
    )
    body = (f'<div class="weather-strip">{pills}</div>' if forecast
            else '<div class="sidebar-note">Forecast not available yet for these dates.</div>')
    st.markdown(
        f'<div class="sidebar-heading">🌤️ Trip forecast · {esc(city)}</div>'
        f'{body}',
        unsafe_allow_html=True,
    )


def render_progress(active_step: int, placeholder) -> None:
    items = ""
    for i, (icon, label) in enumerate(PROGRESS_STEPS):
        state = "done" if i < active_step else "active" if i == active_step else "pending"
        mark = "✓" if state == "done" else icon
        items += f'<div class="progress-step {state}"><span class="step-mark">{mark}</span>{label}</div>'
    placeholder.markdown(
        f'<div class="card progress-card"><div class="card-title">Agent is working</div>{items}</div>',
        unsafe_allow_html=True,
    )


def run_planner(source: str, destination: str, days: int, budget: str, start_date: str,
                return_date: str, travellers: int, placeholder) -> dict:
    """Run the agent in a worker thread while animating the progress card."""
    from agent.travel_agent import plan_trip

    holder: dict = {}

    def worker() -> None:
        try:
            holder["result"] = plan_trip(source, destination, days, budget, None, start_date,
                                         return_date, travellers)
        except Exception as exc:  # defensive: plan_trip already catches its own errors
            holder["result"] = {"success": False, "raw": str(exc), "parsed": {}}

    thread = threading.Thread(target=worker, daemon=True)
    started = time.monotonic()
    thread.start()
    last_step = -1
    while thread.is_alive():
        step = min(int((time.monotonic() - started) / 0.45), len(PROGRESS_STEPS) - 1)
        if step != last_step:
            render_progress(step, placeholder)
            last_step = step
        thread.join(timeout=0.15)
    render_progress(len(PROGRESS_STEPS), placeholder)
    return holder.get("result") or {"success": False, "raw": "Planning returned no result.", "parsed": {}}


# ── Widget callbacks (run before the next script pass, so state updates are safe) ──

def set_route(src: str, dst: str) -> None:
    st.session_state.source = src
    st.session_state.destination = dst


def run_follow_up(request: str, max_plans: int, window_minutes: int) -> None:
    """Send a follow-up request to the agent and record the conversation."""
    from agent.travel_agent import revise_trip

    chat = st.session_state.setdefault("chat", [])
    chat.append({"role": "user", "content": request})
    allowed, wait_seconds, recent_plans = check_rate_limit(
        st.session_state.get("plan_history", []), max_plans, window_minutes * 60)
    if not allowed:
        chat.append({"role": "assistant",
                     "content": f"You have reached the limit of {max_plans} requests in {window_minutes} "
                                f"minutes. Please wait about {math.ceil(wait_seconds / 60)} min."})
        return
    st.session_state.plan_history = recent_plans + [time.time()]

    trip = st.session_state.current_trip
    with st.spinner("Updating your plan..."):
        result = revise_trip(trip["result"], request)
    if not result.get("success"):
        chat.append({"role": "assistant", "content": result.get("raw") or "That change could not be made."})
        return
    trip["result"] = result
    lines = result.get("changes", []) + result.get("agent_notes", [])
    chat.append({"role": "assistant", "content": "\n".join(f"- {line}" for line in lines)})


def render_chat() -> None:
    chat = st.session_state.get("chat", [])
    if not chat:
        return
    st.markdown('<div class="section-label">Your change requests</div>', unsafe_allow_html=True)
    for message in chat:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def swap_route() -> None:
    st.session_state.source, st.session_state.destination = (
        st.session_state.destination, st.session_state.source,
    )


def sync_return_date() -> None:
    """Departure date or days changed: return on the last day of the trip."""
    st.session_state.return_date = st.session_state.start_date + timedelta(days=st.session_state.days - 1)


def sync_days() -> None:
    """Return date changed: count the trip days from the two dates."""
    days = (st.session_state.return_date - st.session_state.start_date).days + 1
    st.session_state.days = max(1, min(days, MAX_TRIP_DAYS))


# ── Apply CSS + state ────────────────────────────────────────────────────────
st.markdown(f"<style>{load_css()}</style>", unsafe_allow_html=True)

st.session_state.setdefault("source", "Delhi")
st.session_state.setdefault("destination", "Goa")
st.session_state.setdefault("budget", "Medium")
st.session_state.setdefault("start_date", date.today() + timedelta(days=7))
st.session_state.setdefault("days", 3)
st.session_state.setdefault("return_date", st.session_state.start_date + timedelta(days=st.session_state.days - 1))
st.session_state.setdefault("travellers", 1)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div class="brand">'
        '<div class="brand-name">✈️ Voyance</div>'
        '<div class="brand-sub">AI Travel Planner</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    source = st.selectbox("📍 From", SUPPORTED_CITIES, key="source")
    st.button("⇅ Swap cities", on_click=swap_route, type="tertiary", key="swap")
    destination = st.selectbox("🎯 To", SUPPORTED_CITIES, key="destination")

    st.markdown('<div class="sidebar-heading">⚡ Popular routes</div>', unsafe_allow_html=True)
    route_cols = st.columns(2)
    for idx, (src, dst) in enumerate(POPULAR_ROUTES):
        route_cols[idx % 2].button(
            f"{src} → {dst}", key=f"route_{idx}", width="stretch",
            on_click=set_route, args=(src, dst),
        )

    st.markdown('<div class="sidebar-heading">📅 Trip details</div>', unsafe_allow_html=True)
    start = st.date_input(
        "Departure date", key="start_date", on_change=sync_return_date,
        min_value=date.today(), max_value=date.today() + timedelta(days=330), format="DD/MM/YYYY",
    )
    end = st.date_input(
        "Return date", key="return_date", on_change=sync_days,
        min_value=start, max_value=start + timedelta(days=MAX_TRIP_DAYS - 1), format="DD/MM/YYYY",
    )
    start_date, return_date = str(start), str(end)
    days = st.slider("Days", min_value=1, max_value=MAX_TRIP_DAYS, key="days", on_change=sync_return_date)
    travellers = int(st.number_input("Travellers (adults)", min_value=1, max_value=MAX_TRAVELLERS,
                                     step=1, key="travellers"))
    budget = st.segmented_control("Budget", BUDGET_LEVELS, key="budget", width="stretch") or "Medium"

    render_weather_live(destination, min(days, 5), start_date)

    plan_btn = st.button("🚀 Plan My Trip", type="primary", width="stretch", key="plan")

    status = (f"🟢 AI mode · Groq {groq_model()}" if llm_available()
              else "🟡 Offline mode · add GROQ_API_KEY for AI plans")
    data_status = ("🟢 Live flights & hotels · SerpApi" if live_data_enabled()
                   else "🟡 Sample flights & hotels · add SERPAPI_API_KEY for live prices")
    st.markdown(
        '<div class="sidebar-footer">'
        f'<div class="status-line">{esc(status)}</div>'
        f'<div class="status-line">{esc(data_status)}</div>'
        '<strong>Powered by</strong><br>'
        'LangChain + Groq · SerpApi · Open-Meteo'
        '</div>',
        unsafe_allow_html=True,
    )

# ── Hero ──────────────────────────────────────────────────────────────────────
info = DESTINATION_INFO.get(destination.lower())
spotlight = (
    f'<div class="spotlight">{info["icon"]} <b>{esc(destination)}</b> · {esc(info["tagline"])}</div>'
    if info else ""
)
st.markdown(
    '<div class="hero-header">'
    '<h1 class="hero-title">Plan Your Next Trip with AI</h1>'
    '<p class="hero-sub">Flights · Hotels · Live Weather · Day-wise Itinerary · Budget</p>'
    f'{spotlight}'
    '</div>',
    unsafe_allow_html=True,
)

# ── Main action ───────────────────────────────────────────────────────────────
max_plans, window_minutes = plan_limit()
if plan_btn:
    allowed, wait_seconds, recent_plans = check_rate_limit(
        st.session_state.get("plan_history", []), max_plans, window_minutes * 60)
    if source == destination:
        st.error("Source and destination must be different cities.")
    elif not allowed:
        st.warning(f"You have planned {max_plans} trips in the last {window_minutes} minutes. "
                   f"Please wait about {math.ceil(wait_seconds / 60)} min before planning again. "
                   "This limit keeps the shared flight, hotel and AI quotas available for everyone.")
        logger.info("Trip plan blocked by the session rate limit")
    else:
        st.session_state.plan_history = recent_plans + [time.time()]
        progress_ph = st.empty()
        result = run_planner(source, destination, days, budget, start_date, return_date,
                             travellers, progress_ph)
        progress_ph.empty()

        if result.get("success"):
            st.session_state.chat = []  # a new plan starts a new conversation
            st.session_state.current_trip = {
                "meta": {
                    "from": source, "to": destination, "days": days, "budget": budget,
                    "start_date": start_date, "return_date": return_date,
                    "travellers": travellers,
                    "time": datetime.now().strftime("%H:%M"),
                },
                "result": result,
            }
            st.toast(f"Your {destination} trip is ready!", icon="✅")
        else:
            st.error("Something went wrong planning your trip.")
            with st.expander("Error details"):
                st.code(result.get("raw", "Unknown error"))

trip = st.session_state.get("current_trip")
if trip:
    follow_up = st.chat_input(
        "Ask for a change, e.g. 'make day 2 more relaxed' or 'find a cheaper hotel'"
        if llm_available() else "Add GROQ_API_KEY to ask for changes to your plan",
        key="follow_up", disabled=not llm_available(), max_chars=500,
    )
    if follow_up:
        run_follow_up(follow_up, max_plans, window_minutes)
        trip = st.session_state.current_trip

    if trip["result"].get("notice"):
        st.info(trip["result"]["notice"], icon="ℹ️")
    render_result(trip["result"], trip["meta"])
    render_chat()

elif not plan_btn:
    st.markdown(
        '<div class="empty-state">'
        '<div class="empty-icon">🌏</div>'
        '<div class="empty-text">Where to next?</div>'
        '<div class="empty-sub">Pick your cities in the sidebar, set the days and budget, '
        'and let the agent plan everything for you.</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    features = [
        ("✈️", "Real Flights", "Direct and 1-stop options from 57 flights"),
        ("🏨", "Smart Hotels", "Filtered by your budget and rating"),
        ("🌤️", "Live Weather", "Open-Meteo real-time forecast"),
        ("🧭", "Day Itinerary", "AI-crafted day-by-day plan"),
    ]
    cards = "".join(
        f'<div class="card feature-card"><div class="feature-icon">{icon}</div>'
        f'<div class="feature-title">{title}</div><div class="feature-desc">{desc}</div></div>'
        for icon, title, desc in features
    )
    st.markdown(f'<div class="feature-grid">{cards}</div>', unsafe_allow_html=True)
