from io import BytesIO

import streamlit as st

from services.storage_service import save_itinerary


def _safe(value: object) -> str:
    """Return string value — do NOT html-escape since we render inside unsafe HTML blocks."""
    return str(value) if value is not None else ""


def itinerary_text(result: dict) -> str:
    return result.get("raw", "")


def itinerary_pdf_bytes(result: dict) -> bytes:
    raw = itinerary_text(result)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        import html

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, title="Travel Itinerary")
        styles = getSampleStyleSheet()
        story = [Paragraph("Travel Itinerary", styles["Title"]), Spacer(1, 12)]
        for line in raw.splitlines():
            story.append(Paragraph(html.escape(line) or "&nbsp;", styles["BodyText"]))
            story.append(Spacer(1, 6))
        doc.build(story)
        return buffer.getvalue()
    except Exception:
        return raw.encode("utf-8")


def render_weather_timeline(weather_items: list) -> None:
    if not weather_items:
        return

    # Parse weather strings and add icons
    wmo_icons = {"clear": "☀️", "sunny": "☀️", "cloud": "⛅", "overcast": "☁️",
                 "rain": "🌧️", "drizzle": "🌦️", "snow": "❄️", "fog": "🌫️",
                 "thunder": "⛈️", "partly": "⛅", "variable": "🌡️"}

    cards = ""
    for item in weather_items:
        text = _safe(item)
        icon = "🌡️"
        text_lower = text.lower()
        for keyword, emoji in wmo_icons.items():
            if keyword in text_lower:
                icon = emoji
                break
        cards += (
            f'<div class="weather-card">'
            f'<span style="font-size:1.3rem">{icon}</span>'
            f'<div style="margin-top:0.3rem;font-size:0.83rem;line-height:1.45;">{text}</div>'
            f'</div>'
        )

    st.markdown(
        '<div class="section-label">🌤️ Weather Forecast</div>'
        f'<div class="weather-timeline">{cards}</div>',
        unsafe_allow_html=True,
    )


def render_budget(parsed: dict) -> None:
    budget = parsed.get("budget", {})
    if not budget:
        return

    icon_map = {
        "flight": "✈️", "hotel": "🏨", "food": "🍽️",
        "food&travel": "🍽️", "local": "🚗", "total": "💰",
    }

    items_html = ""
    total_html = ""

    for key, value in budget.items():
        is_total = "total" in key.lower()
        icon = "💵"
        for kw, em in icon_map.items():
            if kw in key.lower():
                icon = em
                break

        item = (
            f'<div class="budget-item {"budget-total" if is_total else ""}">'
            f'<div style="font-size:1.4rem;margin-bottom:0.3rem;">{icon}</div>'
            f'<div class="budget-label">{_safe(key)}</div>'
            f'<div class="budget-val">{_safe(value)}</div>'
            f'</div>'
        )
        if is_total:
            total_html = item
        else:
            items_html += item

    st.markdown('<div class="section-label">💰 Budget Breakdown</div>', unsafe_allow_html=True)
    if total_html:
        st.markdown(f'<div class="total-trip-card">{total_html}</div>', unsafe_allow_html=True)
    if items_html:
        st.markdown(f'<div class="budget-grid">{items_html}</div>', unsafe_allow_html=True)


def render_days(days: list, raw: str) -> None:
    if not days or (len(days) == 1 and days[0] == raw):
        return

    st.markdown('<div class="section-label">📅 Day-by-Day Itinerary</div>', unsafe_allow_html=True)
    for index, day_text in enumerate(days, start=1):
        # Split on " - " or " — " to get title and content
        sep_match = re.search(r"\s[—\-]\s", day_text)
        if sep_match:
            day_title = day_text[:sep_match.start()].strip()
            day_content = day_text[sep_match.end():].strip()
        else:
            day_title = f"Day {index}"
            day_content = day_text

        # Truncate expander label sensibly
        preview = day_content[:60].rstrip() + ("…" if len(day_content) > 60 else "")

        with st.expander(f"📍 {day_title}  ·  {preview}", expanded=(index == 1)):
            st.markdown(
                f'<div class="timeline-day">'
                f'<div class="day-indicator">{index}</div>'
                f'<div class="day-card">'
                f'<div class="day-num">{_safe(day_title)}</div>'
                f'<div class="day-content">{_safe(day_content)}</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )


def render_result(result: dict, trip_meta: dict | None = None) -> None:
    import re  # local import to avoid module-level issues
    # patch re into render_days via closure
    render_days.__globals__["re"] = re

    parsed = result.get("parsed", {})
    raw = result.get("raw", "")

    if not parsed or not parsed.get("days"):
        st.markdown(
            f'<div class="card"><div class="card-body">{_safe(raw)}</div></div>',
            unsafe_allow_html=True,
        )
        return

    # ── Trip summary banner ──
    summary = _safe(parsed.get("summary", "Your Trip"))
    st.markdown(
        f'<div class="trip-summary-card">'
        f'<div class="summary-kicker">✈️ Trip Summary</div>'
        f'<h2>{summary}</h2>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Flight + Hotel cards ──
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            f'<div class="travel-card">'
            f'<div class="card-title">✈️ Flight Details</div>'
            f'<div class="card-body">{_safe(parsed.get("flight", "See itinerary below"))}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="travel-card">'
            f'<div class="card-title">🏨 Hotel Details</div>'
            f'<div class="card-body">{_safe(parsed.get("hotel", "See itinerary below"))}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Weather ──
    render_weather_timeline(parsed.get("weather", []))

    # ── Day itinerary ──
    render_days(parsed.get("days", []), raw)

    # ── Budget ──
    render_budget(parsed)

    # ── Travel tips ──
    tips = [t for t in parsed.get("tips", []) if len(t.strip()) > 8]
    if tips:
        tips_html = "".join(
            f'<div class="tip-item">'
            f'<div class="tip-dot"></div>'
            f'<span>{_safe(tip)}</span>'
            f'</div>'
            for tip in tips[:5]
        )
        st.markdown('<div class="section-label">💡 Travel Tips</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="card">{tips_html}</div>', unsafe_allow_html=True)

    # ── Export buttons ──
    st.markdown('<div class="section-label">📥 Export & Save</div>', unsafe_allow_html=True)
    action_cols = st.columns(3)
    with action_cols[0]:
        st.download_button(
            "📄 Download PDF",
            data=itinerary_pdf_bytes(result),
            file_name="my_trip_itinerary.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    with action_cols[1]:
        st.download_button(
            "📋 Download Text",
            data=raw,
            file_name="my_trip_itinerary.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with action_cols[2]:
        if st.button("💾 Save Locally", use_container_width=True):
            payload = {**(trip_meta or {}), "result": result}
            path = save_itinerary(payload)
            st.success(f"✅ Saved: {path.name}")