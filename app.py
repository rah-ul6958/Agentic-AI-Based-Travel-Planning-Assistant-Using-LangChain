import os
import time
from datetime import datetime

import streamlit as st

from components.itinerary import render_result
from config.settings import POPULAR_ROUTES, ROOT_DIR, SUPPORTED_CITY_COORDS, load_environment
from services.weather_service import fetch_weather, normalize_weather_payload, weather_icon

load_environment()

st.set_page_config(
    page_title="Voyance · AI Travel Planner",
    page_icon="🌏",
    layout="wide",
    initial_sidebar_state="expanded",   # FIX: was "collapsed" — users couldn't find controls
)


def load_css() -> str:
    return (ROOT_DIR / "styles" / "theme.css").read_text(encoding="utf-8")


@st.cache_data(ttl=1800)
def fetch_live_weather(city: str, days: int = 5) -> dict:
    try:
        payload = fetch_weather(city, days)
        return normalize_weather_payload(city, payload, min(days, 7)) if payload else {}
    except Exception:
        return {}


def render_weather_live(city: str, days: int) -> None:
    data = fetch_live_weather(city, days)
    forecast = data.get("forecast", [])
    if not forecast:
        return

    pills = ""
    for item in forecast[:days]:
        icon = item.get("icon") or weather_icon(2)
        pills += (
            '<div class="weather-pill">'
            f'<span class="day-label">{item["date"][5:]}</span>'
            f'{icon} {item["condition"]}<br>'
            f'{item["max_temp_c"]:.0f}°/{item["min_temp_c"]:.0f}°C'
            '</div>'
        )

    st.markdown(
        f'<div class="section-label">Live Weather · {city.title()}</div>'
        f'<div class="weather-strip">{pills}</div>',
        unsafe_allow_html=True,
    )


def render_progress(active_step: int, placeholder) -> None:
    steps = [
        ("✈️", "Searching flights"),
        ("🏨", "Finding hotels"),
        ("🌤️", "Fetching weather"),
        ("📍", "Discovering places"),
        ("₹",  "Calculating budget"),
        ("🧭", "Composing itinerary"),
    ]
    items = ""
    for i, (icon, label) in enumerate(steps):
        if i < active_step:
            style = "color:#4ade80;"
            prefix = "✓ "
        elif i == active_step:
            style = "color:#f5c842; font-weight:700;"
            prefix = "• "
        else:
            style = "color:#6f7484; opacity:0.6;"
            prefix = ""
        items += (
            f'<div style="display:flex;align-items:center;gap:0.55rem;'
            f'padding:0.38rem 0;font-size:0.9rem;{style}">'
            f'{icon} {prefix}{label}</div>'
        )
    placeholder.markdown(
        f'<div class="card" style="max-width:360px;margin:0 auto 1rem;">'
        f'<div class="card-title">Agent is working</div>{items}</div>'
        f'<div class="skeleton-card" style="max-width:520px;margin:0 auto;"></div>',
        unsafe_allow_html=True,
    )


# ── Apply CSS ─────────────────────────────────────────────────────────────────
st.markdown(f"<style>{load_css()}</style>", unsafe_allow_html=True)

# ── Session state init (do NOT bind to widget keys) ──────────────────────────
if "source" not in st.session_state:
    st.session_state.source = "Delhi"
if "destination" not in st.session_state:
    st.session_state.destination = "Goa"

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div style="padding:1.5rem 0 0.75rem;border-bottom:1px solid rgba(255,255,255,0.08);">'
        '<span style="font-family:\'Playfair Display\',serif;font-size:1.8rem;font-weight:700;'
        'background:linear-gradient(135deg,#f5c842,#f59642);'
        '-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">'
        '✈️ Voyance</span>'
        '<div style="font-size:0.65rem;color:#aaa58f;letter-spacing:1.2px;margin-top:0.3rem;">'
        'AI TRAVEL PLANNER</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="font-family:\'Playfair Display\',serif;font-size:1rem;'
        'color:#e8e4d9;font-weight:600;margin:1.2rem 0 1rem;">Plan Your Journey</div>',
        unsafe_allow_html=True,
    )

    # FIX: Don't use session state as widget value — use separate read var
    st.markdown('<label>📍 From</label>', unsafe_allow_html=True)
    source = st.text_input(
        "FROM", value=st.session_state.source,
        placeholder="e.g. Delhi", label_visibility="collapsed",
        key="source_input"
    )

    st.markdown('<label style="margin-top:0.7rem;display:block;">🎯 To</label>', unsafe_allow_html=True)
    destination = st.text_input(
        "TO", value=st.session_state.destination,
        placeholder="e.g. Goa", label_visibility="collapsed",
        key="dest_input"
    )

    st.markdown(
        '<div style="font-size:0.68rem;color:#aaa58f;letter-spacing:1.1px;'
        'text-transform:uppercase;font-weight:700;margin:1rem 0 0.65rem;">'
        '⚡ Popular Routes</div>',
        unsafe_allow_html=True,
    )
    route_cols = st.columns(2)
    for idx, (src, dst) in enumerate(POPULAR_ROUTES):
        if route_cols[idx % 2].button(f"{src} → {dst}", key=f"route_{idx}", use_container_width=True):
            st.session_state.source = src
            st.session_state.destination = dst
            st.rerun()

    st.markdown('<div style="height:0.5rem;border-bottom:1px solid rgba(255,255,255,0.06);"></div>',
                unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:0.68rem;color:#aaa58f;letter-spacing:1.1px;'
        'text-transform:uppercase;font-weight:700;margin:1rem 0 0.8rem;">'
        '📅 Trip Details</div>',
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<label>Days</label>', unsafe_allow_html=True)
        days = st.slider("DURATION", min_value=1, max_value=7, value=3, label_visibility="collapsed")
    with col2:
        st.markdown('<label>Budget</label>', unsafe_allow_html=True)
        budget = st.selectbox("BUDGET", ["Low", "Medium", "High"], index=1, label_visibility="collapsed")

    # Live weather preview for destination
    dest_for_weather = destination.strip() if destination.strip() else st.session_state.destination
    if dest_for_weather and dest_for_weather.lower() in SUPPORTED_CITY_COORDS:
        render_weather_live(dest_for_weather, min(days, 5))

    st.markdown('<div style="height:1rem;"></div>', unsafe_allow_html=True)
    plan_btn = st.button("🚀 Plan My Trip", use_container_width=True)

    st.markdown(
        '<div style="font-size:0.68rem;color:#626879;line-height:1.8;margin-top:1.5rem;'
        'border-top:1px solid rgba(255,255,255,0.06);padding-top:1rem;">'
        '<strong style="color:#aaa58f;">Powered by:</strong><br>'
        'LangChain + Groq (Llama 3.3 70B)<br>Open-Meteo Weather API<br>'
        'Local JSON Travel Data<br><br>'
        '<span style="font-size:0.6rem;">Supports: Delhi · Goa · Mumbai · Jaipur<br>'
        'Bangalore · Kerala · Manali · Hyderabad<br>Chennai · Kolkata</span></div>',
        unsafe_allow_html=True,
    )

# ── Hero ──────────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="hero-header">'
    '<h1 class="hero-title">Plan Any Trip with AI</h1>'
    '<p class="hero-sub">Flights · Hotels · Real-time Weather · Day-wise Itinerary · Budget</p>'
    '</div>',
    unsafe_allow_html=True,
)

# ── Destination spotlight ─────────────────────────────────────────────────────
DEST_INFO = {
    "goa":       {"tagline": "Beaches, heritage, and nightlife",        "icon": "🏖️"},
    "delhi":     {"tagline": "Monuments, culture, and street food",      "icon": "🕌"},
    "mumbai":    {"tagline": "Sea views, food trails, and city energy",  "icon": "🌆"},
    "jaipur":    {"tagline": "Palaces, forts, and craft markets",        "icon": "🏯"},
    "kerala":    {"tagline": "Backwaters, hills, and slow travel",       "icon": "🌴"},
    "manali":    {"tagline": "Himalayan adventure and mountain air",     "icon": "🏔️"},
    "bangalore": {"tagline": "Gardens, cafes, and weekend escapes",      "icon": "🌿"},
    "hyderabad": {"tagline": "Charminar, biryani, and Nizam heritage",  "icon": "🕍"},
    "chennai":   {"tagline": "Temples, beaches, and Tamil culture",      "icon": "🛕"},
    "kolkata":   {"tagline": "Colonial grandeur, art, and fish curry",   "icon": "🎭"},
}
display_dest = destination.strip() if destination.strip() else st.session_state.destination
if display_dest and display_dest.lower() in DEST_INFO:
    info = DEST_INFO[display_dest.lower()]
    st.markdown(
        f'<div style="text-align:center;padding:0.25rem 0 1.2rem;">'
        f'<span style="font-size:2rem;">{info["icon"]}</span>'
        f'<div style="font-family:\'Playfair Display\',serif;font-size:1rem;'
        f'color:#aaa58f;margin-top:0.2rem;">'
        f'{display_dest.title()} · {info["tagline"]}</div></div>',
        unsafe_allow_html=True,
    )

# ── Main action ───────────────────────────────────────────────────────────────
if plan_btn:
    clean_src = source.strip()
    clean_dst = destination.strip()

    if not clean_src or not clean_dst:
        st.error("Please enter both source and destination cities.")
    elif clean_src.lower() == clean_dst.lower():
        st.error("Source and destination must be different cities.")
    elif not os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY") == "your_groq_key_here":
        st.error("⚠️ GROQ_API_KEY is not set. Add it to your .env file and restart.")
        st.info("Get a free API key at → https://console.groq.com")
    else:
        st.markdown(
            f'<div style="text-align:center;padding:0.5rem 0;">'
            f'<span style="font-size:0.92rem;color:#aaa58f;">'
            f'Planning your {days}-day {budget.lower()}-budget trip from '
            f'<b style="color:#f5c842">{clean_src.title()}</b> to '
            f'<b style="color:#f5c842">{clean_dst.title()}</b>…</span></div>',
            unsafe_allow_html=True,
        )

        progress_ph = st.empty()
        render_progress(0, progress_ph)

        try:
            import threading
            from agent.travel_agent import plan_trip

            result_holder: dict = {}

            def run_agent():
                result_holder["result"] = plan_trip(clean_src, clean_dst, days, budget, None)

            thread = threading.Thread(target=run_agent)
            thread.start()
            step = 0
            while thread.is_alive():
                render_progress(min(step, 5), progress_ph)
                time.sleep(1.8)
                step += 1
            thread.join()

            render_progress(6, progress_ph)
            result = result_holder.get(
                "result",
                {"success": False, "raw": "Planning returned no result.", "parsed": {}},
            )
        except ImportError as exc:
            result = {"success": False, "raw": f"Import error: {exc}", "parsed": {}}
        except Exception as exc:
            result = {"success": False, "raw": str(exc), "parsed": {}}

        progress_ph.empty()

        if result.get("success"):
            trip_meta = {
                "from": clean_src.title(), "to": clean_dst.title(),
                "days": days, "budget": budget,
                "time": datetime.now().strftime("%H:%M"),
            }
            st.success(f"✅ Your {clean_dst.title()} trip is ready!")
            render_result(result, trip_meta)
            st.session_state.setdefault("trip_history", []).append(
                {**trip_meta, "result": result}
            )
        else:
            st.error("Something went wrong planning your trip.")
            with st.expander("Error details"):
                st.code(result.get("raw", "Unknown error"))

elif st.session_state.get("trip_history"):
    last = st.session_state.trip_history[-1]
    st.markdown(
        f'<div class="section-label">Last Planned Trip · {last["time"]}</div>',
        unsafe_allow_html=True,
    )
    render_result(last["result"], last)

else:
    # ── Empty state ──
    st.markdown(
        '<div class="empty-state">'
        '<div class="empty-icon">🌏</div>'
        '<div class="empty-text">Where to next?</div>'
        '<div class="empty-sub">Choose a route from the sidebar, set your budget, '
        'and let the AI plan everything for you.</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    feature_cols = st.columns(4)
    features = [
        ("✈️", "Real Flights",    "Matched from 45+ routes"),
        ("🏨", "Smart Hotels",   "Budget-filtered by rating"),
        ("🌤️", "Live Weather",   "Open-Meteo real-time API"),
        ("🧭", "Day Itinerary",  "AI-crafted day-by-day plan"),
    ]
    for col, (icon, title, desc) in zip(feature_cols, features):
        col.markdown(
            f'<div class="card" style="text-align:center;min-height:8.5rem;'
            f'display:flex;flex-direction:column;justify-content:center;">'
            f'<div style="font-size:2rem;margin-bottom:0.6rem;">{icon}</div>'
            f'<div style="font-weight:700;font-size:0.95rem;color:#e8e4d9;">{title}</div>'
            f'<div style="font-size:0.82rem;color:#8d928f;margin-top:0.35rem;'
            f'line-height:1.4;">{desc}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )