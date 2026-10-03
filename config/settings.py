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

# max_price = hotel price per room per night, min_stars = hotel star class,
# daily_food_travel = food and local travel per person per day
BUDGET_PROFILES = {
    "Low":    {"max_price": 2500,  "min_stars": 2, "daily_food_travel": 800},
    "Medium": {"max_price": 7000,  "min_stars": 3, "daily_food_travel": 1500},
    "High":   {"max_price": 25000, "min_stars": 4, "daily_food_travel": 3000},
}

MAX_TRIP_DAYS = 7
MAX_TRAVELLERS = 6
GUESTS_PER_ROOM = 2


DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


def _streamlit_secrets() -> dict:
    """Top-level values from Streamlit secrets (the "Secrets" box on Streamlit Cloud,
    or .streamlit/secrets.toml). Returns {} when there are none, e.g. locally."""
    try:
        import streamlit as st

        return {name: value for name, value in st.secrets.items()
                if isinstance(value, (str, int, float, bool))}
    except Exception:  # no secrets file: Streamlit raises StreamlitSecretNotFoundError
        return {}


def load_environment() -> None:
    """Locally, settings come from .env. On Streamlit Cloud they come from st.secrets,
    which we copy into the environment so every setting is read the same way.
    A value that is already set in the environment always wins."""
    load_dotenv(ROOT_DIR / ".env")
    for name, value in _streamlit_secrets().items():
        os.environ.setdefault(name, str(value))


def get_setting(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


def get_int_setting(name: str, default: int) -> int:
    try:
        return int(get_setting(name, str(default)))
    except ValueError:
        return default


def groq_model() -> str:
    return get_setting("GROQ_MODEL", DEFAULT_GROQ_MODEL)


def llm_available() -> bool:
    key = get_setting("GROQ_API_KEY")
    return bool(key) and key != "your_groq_key_here"


def plan_limit() -> tuple[int, int]:
    """(max trip plans, window in minutes) allowed per browser session."""
    return get_int_setting("PLAN_LIMIT", 5), get_int_setting("PLAN_WINDOW_MINUTES", 10)
