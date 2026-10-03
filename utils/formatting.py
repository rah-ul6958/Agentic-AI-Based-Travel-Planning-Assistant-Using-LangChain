import html
import time
from datetime import datetime, timedelta, timezone

# India has no daylight saving, so a fixed +05:30 offset is always correct.
IST = timezone(timedelta(hours=5, minutes=30), "IST")

PRICE_LEVEL_TEXT = {
    "low": "Prices are lower than usual for this route",
    "typical": "Prices are typical for this route",
    "high": "Prices are higher than usual for this route",
}


def escape_html(value: object) -> str:
    """Escape text for st.markdown(unsafe_allow_html=True).

    Also neutralises '$' so Streamlit does not treat it as LaTeX math."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True).replace("$", "&#36;")


def format_rupees(value: float | int | str) -> str:
    try:
        return f"Rs.{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def format_duration(hours: float | int | str) -> str:
    try:
        total_minutes = round(float(hours) * 60)
    except (TypeError, ValueError):
        return str(hours)
    h, m = divmod(total_minutes, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def parse_iso_duration_hours(start: str, end: str) -> float:
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        hours = (end_dt - start_dt).total_seconds() / 3600
        return round(max(hours, 0.5), 1)
    except (TypeError, ValueError):
        return 0.0


def format_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%H:%M")
    except (TypeError, ValueError):
        return str(value)


def format_short_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%a, %d %b")
    except (TypeError, ValueError):
        return str(value)


def freshness_label(info: dict | None, now: float | None = None) -> str:
    """Where a card's data came from: "Live - fetched at HH:MM IST",
    "Cached - X min ago" or "Sample data"."""
    if not info or info.get("data_source") != "live" or not info.get("fetched_at"):
        return "Sample data"
    if info.get("from_cache"):
        minutes = int(((now or time.time()) - info["fetched_at"]) // 60)
        return "Cached - less than 1 min ago" if minutes < 1 else f"Cached - {minutes} min ago"
    fetched = datetime.fromtimestamp(info["fetched_at"], IST).strftime("%H:%M")
    return f"Live - fetched at {fetched} IST"


def price_insight_text(insights: dict | None) -> str:
    """One line from Google Flights price insights, or "" when there are none."""
    level = str((insights or {}).get("price_level") or "").strip().lower()
    if not level:
        return ""
    # SerpApi's docs only show "low"; other values are shown as they come.
    text = PRICE_LEVEL_TEXT.get(level, f"Google price level: {level}")
    usual = insights.get("typical_price_range") or []
    if len(usual) == 2:
        text += f" (usually {format_rupees(usual[0])}-{format_rupees(usual[1])} per person)"
    return text
