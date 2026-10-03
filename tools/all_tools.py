from tools.airport_tool import find_nearby_airports
from tools.budget_tool import estimate_budget
from tools.flight_tool import search_flights
from tools.hotel_tool import search_hotels
from tools.places_tool import search_places
from tools.weather_tool import get_weather


ALL_TOOLS = [
    search_flights,
    search_hotels,
    search_places,
    get_weather,
    estimate_budget,
    find_nearby_airports,
]
