import json

from langchain_core.tools import tool

from utils.formatting import format_rupees


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _flight_legs_text(outbound_price: float, return_price: float) -> str:
    if outbound_price and return_price:
        return "both ways"
    if outbound_price:
        return "outbound only, no return flight found"
    if return_price:
        return "return only, no outbound flight found"
    return "no flights found"


@tool
def estimate_budget(
    outbound_flight_price: float,
    return_flight_price: float,
    hotel_stay_price: float,
    rooms: int,
    nights: int,
    days: int,
    travellers: int = 1,
    daily_food_travel: float = 1500.0,
    hotel_price_note: str = "",
) -> str:
    """Calculate total trip budget.
    Flight prices are per person for one way. hotel_stay_price is for one room for all
    nights. daily_food_travel is per person per day. Every number comes from the flight
    and hotel tools, never from the LLM."""
    travellers = max(int(travellers), 1)
    rooms = max(int(rooms), 1)
    nights = max(int(nights), 1)
    days = max(int(days), 1)

    flight_per_person = outbound_flight_price + return_flight_price
    flight_total = flight_per_person * travellers
    hotel_total = hotel_stay_price * rooms
    food_total = daily_food_travel * travellers * days
    grand_total = flight_total + hotel_total + food_total

    hotel_details = f"{_plural(rooms, 'room')} x {_plural(nights, 'night')}"
    if hotel_price_note:
        hotel_details += f", {hotel_price_note}"

    return json.dumps(
        {
            "breakdown": {
                "flight": flight_total,
                "hotel_total": hotel_total,
                "food_and_local_travel": food_total,
            },
            "details": {
                "outbound_flight_per_person": outbound_flight_price,
                "return_flight_per_person": return_flight_price,
                "travellers": travellers,
                "rooms": rooms,
                "nights": nights,
                "days": days,
            },
            "grand_total": grand_total,
            "formatted": {
                "flight": (f"{format_rupees(flight_total)} ({travellers} x "
                           f"{format_rupees(flight_per_person)}, "
                           f"{_flight_legs_text(outbound_flight_price, return_flight_price)})"),
                "hotel": f"{format_rupees(hotel_total)} ({hotel_details})",
                "food_and_travel": (f"{format_rupees(food_total)} ({travellers} x "
                                    f"{_plural(days, 'day')} x {format_rupees(daily_food_travel)})"),
                "total": format_rupees(grand_total),
            },
        },
        indent=2,
    )
