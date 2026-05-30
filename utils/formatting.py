import html
from datetime import datetime


def escape_html(value: object) -> str:
    return html.escape(str(value), quote=True)


def format_rupees(value: float | int | str) -> str:
    try:
        return f"Rs.{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


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
