import json
import re
from datetime import datetime
from pathlib import Path

from config.settings import SAVED_TRIPS_DIR


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "trip"


def save_itinerary(payload: dict) -> Path:
    SAVED_TRIPS_DIR.mkdir(parents=True, exist_ok=True)
    source = safe_slug(payload.get("from", "source"))
    destination = safe_slug(payload.get("to", "destination"))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SAVED_TRIPS_DIR / f"{timestamp}-{source}-to-{destination}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
