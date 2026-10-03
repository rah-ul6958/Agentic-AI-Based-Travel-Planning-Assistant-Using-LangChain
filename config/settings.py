import os
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
    "kerala":    (9.9312,   76.2673),
    "manali":    (32.2396,  77.1887),
    "chennai":   (13.0827,  80.2707),
    "hyderabad": (17.3850,  78.4867),
    "kolkata":   (22.5726,  88.3639),
}

SUPPORTED_CITIES = sorted(city.title() for city in SUPPORTED_CITY_COORDS)

POPULAR_ROUTES = [
    ("Delhi",     "Goa"),
    ("Delhi",     "Jaipur"),
    ("Mumbai",    "Goa"),
    ("Delhi",     "Manali"),
    ("Bangalore", "Kerala"),
    ("Delhi",     "Kolkata"),
]

DESTINATION_INFO = {
    "goa":       {"tagline": "Beaches, heritage, and nightlife",       "icon": "🏖️"},
    "delhi":     {"tagline": "Monuments, culture, and street food",     "icon": "🕌"},
    "mumbai":    {"tagline": "Sea views, food trails, and city energy", "icon": "🌆"},
    "jaipur":    {"tagline": "Palaces, forts, and craft markets",       "icon": "🏯"},
    "kerala":    {"tagline": "Backwaters, hills, and slow travel",      "icon": "🌴"},
    "manali":    {"tagline": "Himalayan adventure and mountain air",    "icon": "🏔️"},
    "bangalore": {"tagline": "Gardens, cafes, and weekend escapes",     "icon": "🌿"},
    "hyderabad": {"tagline": "Charminar, biryani, and Nizam heritage",  "icon": "🕍"},
    "chennai":   {"tagline": "Temples, beaches, and Tamil culture",     "icon": "🛕"},
    "kolkata":   {"tagline": "Colonial grandeur, art, and fish curry",  "icon": "🎭"},
}

BUDGET_PROFILES = {
    "Low":    {"max_price": 2500,  "min_rating": 2.0, "daily_food_travel": 800},
    "Medium": {"max_price": 7000,  "min_rating": 3.0, "daily_food_travel": 1500},
    "High":   {"max_price": 25000, "min_rating": 4.0, "daily_food_travel": 3000},
}


DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


def load_environment() -> None:
    load_dotenv(ROOT_DIR / ".env")


def groq_model() -> str:
    return os.getenv("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL


def llm_available() -> bool:
    key = os.getenv("GROQ_API_KEY", "").strip()
    return bool(key) and key != "your_groq_key_here"
