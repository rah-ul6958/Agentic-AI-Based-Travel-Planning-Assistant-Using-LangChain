"""Small helpers for trip dates, nights and rooms, shared by the agent, tools and UI."""
import math
from datetime import date, timedelta

from config.settings import GUESTS_PER_ROOM


def hotel_nights(days: int) -> int:
    """A 3-day trip needs 2 hotel nights. Always at least 1 night."""
    return max(int(days) - 1, 1)


def rooms_needed(travellers: int) -> int:
    """Two guests share a room, so 3 travellers need 2 rooms."""
    return math.ceil(max(int(travellers), 1) / GUESTS_PER_ROOM)


def guests_per_room(travellers: int) -> int:
    return min(max(int(travellers), 1), GUESTS_PER_ROOM)


def default_return_date(start_date: str, days: int) -> str:
    """Return on the last day of the trip: departure date + days - 1."""
    start = date.fromisoformat(start_date)
    return str(start + timedelta(days=max(int(days), 1) - 1))


def check_out_date(check_in: str, nights: int) -> str:
    return str(date.fromisoformat(check_in) + timedelta(days=max(int(nights), 1)))
