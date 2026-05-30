from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
SAVED_TRIPS_DIR = ROOT_DIR / "data" / "saved_itineraries"

SUPPORTED_CITY_COORDS = {
    "goa":       (15.2993,  74.1240),
    "delhi":     (28.6139,  77.2090),
    "mumbai":    (19.0760,  72.8777),
    "bangalore": (12.9716,  77.5946),
    "jaipur":    (26.9124,  75.7873),
    "kerala":    (10.8505,  76.2711),
    "manali":    (32.2396,  77.1887),
    "chennai":   (13.0827,  80.2707),
    "hyderabad": (17.3850,  78.4867),
    "kolkata":   (22.5726,  88.3639),
}

POPULAR_ROUTES = [
    ("Delhi",     "Goa"),
    ("Delhi",     "Jaipur"),
    ("Mumbai",    "Goa"),
    ("Delhi",     "Mumbai"),
    ("Bangalore", "Goa"),
    ("Delhi",     "Kolkata"),
]

BUDGET_PROFILES = {
    "Low":    {"max_price": 2500,  "min_rating": 2.0, "daily_food_travel": 800},
    "Medium": {"max_price": 7000,  "min_rating": 3.0, "daily_food_travel": 1500},
    "High":   {"max_price": 25000, "min_rating": 4.0, "daily_food_travel": 3000},
}


def load_environment() -> None:
    load_dotenv(ROOT_DIR / ".env")