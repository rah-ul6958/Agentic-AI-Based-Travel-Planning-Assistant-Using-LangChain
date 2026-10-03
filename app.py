import threading
import time
from datetime import date, datetime, timedelta

import streamlit as st

from components.itinerary import render_result
from config.settings import (
    DESTINATION_INFO,
    POPULAR_ROUTES,
    ROOT_DIR,
    SUPPORTED_CITIES,
    groq_model,
    llm_available,
    load_environment,
)
from services.live_travel_service import live_data_enabled
from services.weather_service import fetch_weather, normalize_weather_payload
from utils.formatting import escape_html as esc
from utils.formatting import format_short_date

load_environment()

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
    except Exception:
        return {}


def render_weather_live(city: str, days: int, start_date: str) -> None:
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
    st.markdown(
        f'<div class="sidebar-heading">🌤️ Trip forecast · {esc(city)}</div>'
        f'<div class="weather-strip">{pills}</div>',
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
                placeholder) -> dict:
    """Run the agent in a worker thread while animating the progress card."""
    from agent.travel_agent import plan_trip

    holder: dict = {}

    def worker() -> None:
        try:
            holder["result"] = plan_trip(source, destination, days, budget, None, start_date)
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


def swap_route() -> None:
    st.session_state.source, st.session_state.destination = (
        st.session_state.destination, st.session_state.source,
    )


# ── Apply CSS + state ────────────────────────────────────────────────────────
st.markdown(f"<style>{load_css()}</style>", unsafe_allow_html=True)

st.session_state.setdefault("source", "Delhi")
st.session_state.setdefault("destination", "Goa")
st.session_state.setdefault("budget", "Medium")

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
        "Departure date", value=date.today() + timedelta(days=7),
        min_value=date.today(), max_value=date.today() + timedelta(days=330), format="DD/MM/YYYY",
    )
    start_date = str(start)
    days = st.slider("Days", min_value=1, max_value=7, value=3)
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
if plan_btn:
    if source == destination:
        st.error("Source and destination must be different cities.")
    else:
        progress_ph = st.empty()
        result = run_planner(source, destination, days, budget, start_date, progress_ph)
        progress_ph.empty()

        if result.get("success"):
            st.session_state.current_trip = {
                "meta": {
                    "from": source, "to": destination, "days": days, "budget": budget,
                    "start_date": start_date,
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
    if trip["result"].get("notice"):
        st.info(trip["result"]["notice"], icon="ℹ️")
    render_result(trip["result"], trip["meta"])

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
