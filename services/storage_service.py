import json
import logging
import re
from datetime import datetime
from pathlib import Path

import requests

from config import settings
from config.settings import get_setting

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    pass


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "trip"


def supabase_enabled() -> bool:
    return bool(get_setting("SUPABASE_URL") and get_setting("SUPABASE_KEY"))


def _save_to_file(payload: dict) -> Path:
    folder = settings.SAVED_TRIPS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    source = safe_slug(payload.get("from", "source"))
    destination = safe_slug(payload.get("to", "destination"))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{timestamp}-{source}-to-{destination}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _save_to_supabase(payload: dict) -> None:
    """Insert one row with Supabase's REST API (PostgREST).
    The table and its insert-only policy are described in README.md."""
    url = f"{get_setting('SUPABASE_URL').rstrip('/')}/rest/v1/{get_setting('SUPABASE_TABLE', 'saved_trips')}"
    key = get_setting("SUPABASE_KEY")
    row = {
        "source": payload.get("from", ""),
        "destination": payload.get("to", ""),
        "start_date": payload.get("start_date") or None,
        "payload": payload,
    }
    response = requests.post(
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Do not read the row back: that would need a SELECT policy, which would
            # let anyone holding the key read every saved trip.
            "Prefer": "return=minimal",
        },
        json=row,
        timeout=10,
    )
    if response.status_code != 201:
        raise StorageError(f"Supabase returned HTTP {response.status_code}")


def save_itinerary(payload: dict) -> str:
    """Save a trip and return a short message for the user.
    Uses Supabase when SUPABASE_URL and SUPABASE_KEY are set, otherwise a local
    JSON file. If Supabase fails, the trip is still saved locally."""
    if supabase_enabled():
        try:
            _save_to_supabase(payload)
            return "Trip saved to the cloud database"
        except (requests.RequestException, StorageError) as exc:
            # Error type/status only: request errors can include the project URL and headers
            logger.warning("Supabase save failed (%s); saving to a local file instead",
                           exc if isinstance(exc, StorageError) else type(exc).__name__)
            path = _save_to_file(payload)
            return f"Cloud database unavailable, saved to data/saved_itineraries/{path.name}"

    path = _save_to_file(payload)
    return f"Saved to data/saved_itineraries/{path.name}"
