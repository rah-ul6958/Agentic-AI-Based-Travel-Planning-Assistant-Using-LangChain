import re
from io import BytesIO

import streamlit as st

from services.storage_service import save_itinerary
from utils.formatting import escape_html as esc
from utils.formatting import format_short_date

SLOT_ICONS = {"morning": "🌅", "afternoon": "☀️", "evening": "🌇", "night": "🌙"}
SLOT_RE = re.compile(r"\b(Morning|Afternoon|Evening|Night)\s*:\s*", re.IGNORECASE)
DAY_TITLE_RE = re.compile(r"^(day\s*\d+)\s*[-–—:]?\s*(.*)$", re.IGNORECASE | re.DOTALL)
WEATHER_RE = re.compile(
    r"^(?:day\s*(?P<day>\d+)\s*:?\s*)?(?P<date>\d{4}-\d{2}-\d{2})?\s*(?P<cond>.*?)\s*"
    r"(?P<max>-?\d+(?:\.\d+)?)\s*°?\s*C?\s*/\s*(?P<min>-?\d+(?:\.\d+)?)\s*°?\s*C?\s*$",
    re.IGNORECASE,
)
WEATHER_ICONS = [
    ("thunder", "⛈️"), ("snow", "❄️"), ("drizzle", "🌦️"), ("shower", "🌦️"), ("rain", "🌧️"),
    ("fog", "🌫️"), ("overcast", "☁️"), ("partly", "⛅"), ("cloud", "⛅"),
    ("mainly clear", "🌤️"), ("clear", "☀️"), ("sunny", "☀️"),
]
BUDGET_ICONS = [("total", "💰"), ("flight", "✈️"), ("hotel", "🏨"), ("food", "🍽️"), ("travel", "🚗")]


def _section(label: str) -> None:
    st.markdown(f'<div class="section-label">{esc(label)}</div>', unsafe_allow_html=True)


def _pick_icon(text: str, table: list[tuple[str, str]], default: str) -> str:
    lower = text.lower()
    return next((icon for keyword, icon in table if keyword in lower), default)


# ── Parsing helpers for display ──────────────────────────────────────────────

def split_day(day_text: str, index: int) -> tuple[str, str, list[tuple[str, str]]]:
    """Split 'Day 1 - Theme: Morning: ... Afternoon: ...' into (title, theme, slots)."""
    match = DAY_TITLE_RE.match(day_text.strip())
    title, rest = (match.group(1).title(), match.group(2)) if match else (f"Day {index}", day_text)

    parts = SLOT_RE.split(rest)
    theme = parts[0].strip(" :-–—.")
    slots = [
        (parts[i].title(), parts[i + 1].strip(" .;") + ".")
        for i in range(1, len(parts) - 1, 2)
        if parts[i + 1].strip(" .;")
    ]
    if not slots:
        theme, slots = "", [("", rest.strip())]
    return title, theme, slots


def parse_weather_item(text: str) -> dict:
    match = WEATHER_RE.match(text.strip())
    if not match:
        return {"label": "", "condition": text, "temps": ""}
    date = match.group("date")
    day = match.group("day")
    label = format_short_date(date) if date else (f"Day {day}" if day else "")
    return {
        "label": label,
        "condition": match.group("cond").strip(" :-") or "—",
        "temps": f'{float(match.group("max")):.0f}° / {float(match.group("min")):.0f}°C',
    }


# ── Section renderers ────────────────────────────────────────────────────────

def _info_card(title: str, value: str, link: str = "", link_text: str = "") -> str:
    parts = [p.strip() for p in value.split("|") if p.strip()] or ["Not available"]
    chips = "".join(f'<span class="chip">{esc(p)}</span>' for p in parts[1:])
    link_html = (f'<a class="card-link" href="{esc(link)}" target="_blank" rel="noopener">{esc(link_text)} ↗</a>'
                 if link.startswith("https://") else "")
    return (
        f'<div class="travel-card">'
        f'<div class="card-title">{esc(title)}</div>'
        f'<div class="card-headline">{esc(parts[0])}</div>'
        f'<div class="chip-row">{chips}</div>'
        f'{link_html}'
        f'</div>'
    )


def render_weather_timeline(weather_items: list) -> None:
    if not weather_items:
        return
    cards = ""
    for item in weather_items:
        info = parse_weather_item(str(item))
        icon = _pick_icon(info["condition"], WEATHER_ICONS, "🌡️")
        cards += (
            '<div class="weather-card">'
            f'<div class="weather-day">{esc(info["label"])}</div>'
            f'<div class="weather-icon">{icon}</div>'
            f'<div class="weather-cond">{esc(info["condition"])}</div>'
            f'<div class="weather-temp">{esc(info["temps"])}</div>'
            '</div>'
        )
    _section("🌤️ Weather Forecast")
    st.markdown(f'<div class="weather-timeline">{cards}</div>', unsafe_allow_html=True)


def render_days(days: list) -> None:
    if not days:
        return
    _section("📅 Day-by-Day Itinerary")
    for index, day_text in enumerate(days, start=1):
        title, theme, slots = split_day(day_text, index)
        label = f"**{title}**" + (f" · {theme}" if theme else "")
        with st.expander(label, expanded=(index == 1)):
            rows = "".join(
                '<div class="slot-row">'
                f'<div class="slot-icon">{SLOT_ICONS.get(slot.lower(), "📍")}</div>'
                '<div>'
                + (f'<div class="slot-name">{esc(slot)}</div>' if slot else "")
                + f'<div class="slot-text">{esc(text)}</div></div></div>'
                for slot, text in slots
            )
            st.markdown(f'<div class="day-card">{rows}</div>', unsafe_allow_html=True)


def render_budget(budget: dict) -> None:
    if not budget:
        return

    def item(key: str, value: str, total: bool = False) -> str:
        amount, _, note = value.partition("(")
        note_html = f'<div class="budget-note">{esc(note.rstrip(")"))}</div>' if note else ""
        return (
            f'<div class="budget-item{" budget-total" if total else ""}">'
            f'<div class="budget-icon">{_pick_icon(key, BUDGET_ICONS, "💵")}</div>'
            f'<div class="budget-label">{esc(key.replace("&", " & "))}</div>'
            f'<div class="budget-val">{esc(amount.strip())}</div>{note_html}'
            f'</div>'
        )

    parts = "".join(item(k, v) for k, v in budget.items() if "total" not in k.lower())
    totals = "".join(item("Estimated Total", v, True) for k, v in budget.items() if "total" in k.lower())

    _section("💰 Budget Breakdown")
    st.markdown(f'<div class="budget-grid">{parts}{totals}</div>', unsafe_allow_html=True)


def render_tips(tips: list) -> None:
    tips = [t for t in tips if len(t.strip()) > 8][:6]
    if not tips:
        return
    rows = "".join(
        f'<div class="tip-item"><div class="tip-dot"></div><span>{esc(tip)}</span></div>'
        for tip in tips
    )
    _section("💡 Travel Tips")
    st.markdown(f'<div class="card">{rows}</div>', unsafe_allow_html=True)


# ── Exports ──────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def itinerary_pdf_bytes(parsed: dict, title: str) -> bytes | None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import ListFlowable, Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        return None

    def p(text: str, style: str = "BodyText") -> Paragraph:
        return Paragraph(esc(text).replace("&#36;", "$"), styles[style])

    def bullets(items: list[str]) -> ListFlowable:
        return ListFlowable([p(i) for i in items], bulletType="bullet", leftIndent=12)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title=title,
                            leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#b7791f")
    story = [p(title, "Title")]
    if parsed.get("summary"):
        story += [p(parsed["summary"], "Heading3"), Spacer(1, 6)]

    for heading, key in (("Flight", "flight"), ("Hotel", "hotel")):
        if parsed.get(key):
            story += [p(heading, "Heading2"), bullets([s.strip() for s in parsed[key].split("|") if s.strip()])]

    if parsed.get("weather"):
        story += [p("Weather Forecast", "Heading2"), bullets(parsed["weather"])]

    if parsed.get("days"):
        story.append(p("Day-by-Day Itinerary", "Heading2"))
        for index, day in enumerate(parsed["days"], start=1):
            day_title, theme, slots = split_day(day, index)
            story.append(p(f"{day_title}" + (f" - {theme}" if theme else ""), "Heading4"))
            story.append(bullets([f"{s}: {t}" if s else t for s, t in slots]))

    if parsed.get("budget"):
        story += [p("Budget", "Heading2"), bullets([f"{k}: {v}" for k, v in parsed["budget"].items()])]

    if parsed.get("tips"):
        story += [p("Travel Tips", "Heading2"), bullets(parsed["tips"])]

    doc.build(story)
    return buffer.getvalue()


def _file_stem(trip_meta: dict) -> str:
    stem = f'{trip_meta.get("from", "trip")}-to-{trip_meta.get("to", "")}'.lower()
    return re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "trip"


def render_exports(result: dict, trip_meta: dict) -> None:
    parsed = result.get("parsed", {})
    stem = _file_stem(trip_meta)
    title = f'{trip_meta.get("from", "")} to {trip_meta.get("to", "")} - Travel Itinerary'.strip(" -")

    _section("📥 Export & Save")
    col1, col2, col3 = st.columns(3)
    with col1:
        pdf = itinerary_pdf_bytes(parsed, title)
        st.download_button(
            "📄 Download PDF", data=pdf or b"", file_name=f"{stem}-itinerary.pdf",
            mime="application/pdf", width="stretch", disabled=pdf is None,
            help=None if pdf else "Install reportlab to enable PDF export",
        )
    with col2:
        st.download_button(
            "📋 Download Text", data=result.get("raw", ""), file_name=f"{stem}-itinerary.txt",
            mime="text/plain", width="stretch",
        )
    with col3:
        if st.button("💾 Save Locally", width="stretch", key="save_trip"):
            path = save_itinerary({**trip_meta, "result": result})
            st.toast(f"Saved to data/saved_itineraries/{path.name}", icon="✅")


# ── Entry point ──────────────────────────────────────────────────────────────

def render_result(result: dict, trip_meta: dict | None = None) -> None:
    trip_meta = trip_meta or {}
    parsed = result.get("parsed", {})
    raw = result.get("raw", "")

    if not parsed or not parsed.get("days"):
        st.markdown(f'<div class="card"><div class="card-body pre">{esc(raw)}</div></div>',
                    unsafe_allow_html=True)
        return

    # ── Trip summary banner ──
    sources = result.get("data_sources", {})
    live = [name for name, src in sources.items() if src == "live"]
    meta_chips = [
        f'{trip_meta["from"]} → {trip_meta["to"]}' if trip_meta.get("from") else "",
        f'🗓️ {format_short_date(trip_meta["start_date"])}' if trip_meta.get("start_date") else "",
        f'{trip_meta["days"]} days' if trip_meta.get("days") else "",
        f'{trip_meta["budget"]} budget' if trip_meta.get("budget") else "",
        "🤖 AI planned" if result.get("mode") == "ai" else "📊 Data-driven plan",
        ("🔴 Live " + " & ".join(live)) if live else ("🗂️ Sample data" if sources else ""),
    ]
    chips = "".join(f'<span class="chip">{esc(c)}</span>' for c in meta_chips if c)
    st.markdown(
        '<div class="trip-summary-card">'
        '<div class="summary-kicker">✈️ Trip Summary</div>'
        f'<h2>{esc(parsed.get("summary") or "Your Trip")}</h2>'
        f'<div class="chip-row center">{chips}</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Flight + Hotel cards ──
    col1, col2 = st.columns(2)
    links = result.get("links", {})
    col1.markdown(_info_card("✈️ Flight", parsed.get("flight", ""), links.get("flight", ""),
                             "Check live fares"), unsafe_allow_html=True)
    col2.markdown(_info_card("🏨 Hotel", parsed.get("hotel", ""), links.get("hotel", ""),
                             "View hotel"), unsafe_allow_html=True)

    render_weather_timeline(parsed.get("weather", []))
    render_days(parsed.get("days", []))
    render_budget(parsed.get("budget", {}))
    render_tips(parsed.get("tips", []))
    render_exports(result, trip_meta)
