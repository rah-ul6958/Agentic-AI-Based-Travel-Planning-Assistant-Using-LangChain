import json

from langchain_core.tools import tool

from utils.formatting import format_rupees


@tool
def estimate_budget(
    flight_cost: float,
    hotel_cost_per_night: float,
    num_nights: int,
    daily_food_travel: float = 1500.0,
) -> str:
    """Calculate total trip budget."""
    nights = max(int(num_nights), 1)
    hotel_total = hotel_cost_per_night * nights
    food_total = daily_food_travel * nights
    grand_total = flight_cost + hotel_total + food_total

    return json.dumps(
        {
            "breakdown": {
                "flight": flight_cost,
                "hotel_total": hotel_total,
                "food_and_local_travel": food_total,
            },
            "grand_total": grand_total,
            "formatted": {
                "flight": format_rupees(flight_cost),
                "hotel": f"{format_rupees(hotel_total)} ({nights} nights x {format_rupees(hotel_cost_per_night)})",
                "food_and_travel": format_rupees(food_total),
                "total": format_rupees(grand_total),
            },
        },
        indent=2,
    )
