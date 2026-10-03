"""Phase 3 tests: shared cache, rate limit, Supabase storage, secrets, logging, CI."""
import json
import logging
import os
import re
from pathlib import Path

import pytest
import requests

from config import settings
from services import live_travel_service, storage_service
from services.live_travel_service import LiveDataError, fetch_live_flights
from utils.rate_limit import check_rate_limit

ROOT = Path(__file__).resolve().parents[1]
FLIGHTS = {"best_flights": [{
    "flights": [{"departure_airport": {"id": "DEL", "time": "2026-11-02 06:10"},
                 "arrival_airport": {"id": "GOI", "time": "2026-11-02 08:45"},
                 "duration": 155, "airline": "IndiGo", "flight_number": "6E 1"}],
    "layovers": [], "total_duration": 155, "price": 5000,
}]}


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.ok = payload, status, status < 400

    def json(self):
        return self._payload


# ── Shared cache (st.cache_data) ─────────────────────────────────────────────

def test_live_fetch_uses_streamlit_cache_and_never_caches_errors(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    answers = [{"error": "Server busy"}, FLIGHTS]
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse(answers[min(len(calls), len(answers)) - 1])

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(LiveDataError):
        fetch_live_flights("Delhi", "Goa", "2026-11-02")      # error: not cached
    first = fetch_live_flights("Delhi", "Goa", "2026-11-02")   # retried for real
    second = fetch_live_flights("Delhi", "Goa", "2026-11-02")  # served from st.cache_data

    assert len(calls) == 2
    assert first["from_cache"] is False and second["from_cache"] is True
    assert second["fetched_at"] == first["fetched_at"]
    assert hasattr(live_travel_service._cached_request, "clear")  # it is an st.cache_data function
    assert live_travel_service.CACHE_TTL_SECONDS == 30 * 60


def test_api_key_is_not_part_of_the_cache_key(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", lambda url, params=None, timeout=None:
                        calls.append(params) or FakeResponse(FLIGHTS))
    monkeypatch.setenv("SERPAPI_API_KEY", "key-one")
    fetch_live_flights("Delhi", "Goa", "2026-11-02")
    monkeypatch.setenv("SERPAPI_API_KEY", "key-two")
    assert fetch_live_flights("Delhi", "Goa", "2026-11-02")["from_cache"] is True
    assert len(calls) == 1


# ── Rate limit ───────────────────────────────────────────────────────────────

def test_rate_limit_allows_up_to_the_limit():
    now = 10_000.0
    allowed, wait, recent = check_rate_limit([now - 700, now - 300, now - 10], 3, 600, now=now)
    assert allowed and wait == 0 and recent == [now - 300, now - 10]  # 700 s ago has expired


def test_rate_limit_blocks_and_says_how_long_to_wait():
    now = 10_000.0
    allowed, wait, recent = check_rate_limit([now - 500, now - 200, now - 30], 3, 600, now=now)
    assert not allowed and len(recent) == 3
    assert wait == 101  # the oldest plan leaves the 10-minute window in 100 s


def test_app_blocks_plans_over_the_session_limit(monkeypatch):
    import streamlit
    from streamlit.testing.v1 import AppTest

    if tuple(int(p) for p in streamlit.__version__.split(".")[:2]) < (1, 50):
        pytest.skip("AppTest in Streamlit < 1.50 mishandles segmented_control values")

    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("PLAN_LIMIT", "2")
    at = AppTest.from_file("app.py", default_timeout=60).run()
    for _ in range(2):
        at.button(key="plan").click().run()
        assert not at.warning
    first_trip = at.session_state.current_trip

    at.button(key="plan").click().run()
    assert any("You have planned 2 trips" in w.value for w in at.warning)
    assert len(at.session_state.plan_history) == 2
    assert at.session_state.current_trip is first_trip or \
        at.session_state.current_trip["meta"] == first_trip["meta"]  # no new plan was made


# ── Supabase storage ─────────────────────────────────────────────────────────

def test_supabase_is_used_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SAVED_TRIPS_DIR", tmp_path)
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co/")
    monkeypatch.setenv("SUPABASE_KEY", "anon-key")
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers, json=json)
        return FakeResponse(None, status=201)

    monkeypatch.setattr(requests, "post", fake_post)
    message = storage_service.save_itinerary({"from": "Delhi", "to": "Goa", "start_date": "2026-11-02"})

    assert message == "Trip saved to the cloud database"
    assert sent["url"] == "https://demo.supabase.co/rest/v1/saved_trips"
    assert sent["headers"]["apikey"] == "anon-key"
    assert sent["headers"]["Authorization"] == "Bearer anon-key"
    assert sent["headers"]["Prefer"] == "return=minimal"
    assert sent["json"]["destination"] == "Goa" and sent["json"]["payload"]["from"] == "Delhi"
    assert list(tmp_path.iterdir()) == []  # nothing written locally


def test_supabase_failure_falls_back_to_local_file(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(settings, "SAVED_TRIPS_DIR", tmp_path)
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "secret-anon-key")
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse({"message": "denied"}, status=401))

    with caplog.at_level(logging.WARNING):
        message = storage_service.save_itinerary({"from": "Delhi", "to": "Goa"})

    assert message.startswith("Cloud database unavailable, saved to data/saved_itineraries/")
    saved = list(tmp_path.iterdir())
    assert len(saved) == 1 and json.loads(saved[0].read_text(encoding="utf-8"))["to"] == "Goa"
    assert "HTTP 401" in caplog.text and "secret-anon-key" not in caplog.text


def test_local_file_when_supabase_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SAVED_TRIPS_DIR", tmp_path)
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_KEY", "")
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("Supabase must not be called"))
    message = storage_service.save_itinerary({"from": "Delhi", "to": "Goa"})
    assert message.startswith("Saved to data/saved_itineraries/") and len(list(tmp_path.iterdir())) == 1


# ── Settings from st.secrets ─────────────────────────────────────────────────

def test_secrets_are_copied_but_environment_wins(monkeypatch):
    # Never read the developer's real .env in a test
    monkeypatch.setattr(settings, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_MODEL", "model-from-env")
    monkeypatch.setattr(settings, "_streamlit_secrets", lambda: {
        "SERPAPI_API_KEY": "key-from-secrets", "GROQ_MODEL": "model-from-secrets", "PLAN_LIMIT": 7,
    })
    monkeypatch.delenv("PLAN_LIMIT", raising=False)
    settings.load_environment()

    assert settings.get_setting("SERPAPI_API_KEY") == "key-from-secrets"
    assert settings.groq_model() == "model-from-env"
    assert settings.plan_limit()[0] == 7


def test_no_secrets_file_is_fine_locally():
    assert settings._streamlit_secrets() == {}


def test_bad_number_setting_uses_default(monkeypatch):
    monkeypatch.setenv("PLAN_LIMIT", "lots")
    monkeypatch.setenv("PLAN_WINDOW_MINUTES", "")
    assert settings.plan_limit() == (5, 10)


# ── Logging ──────────────────────────────────────────────────────────────────

def test_api_failures_are_logged_without_the_key(monkeypatch, caplog):
    monkeypatch.setenv("SERPAPI_API_KEY", "super-secret-key")

    def failing_get(url, params=None, timeout=None):
        raise requests.ConnectionError(f"failed: {url}?api_key={params['api_key']}")

    monkeypatch.setattr(requests, "get", failing_get)
    with caplog.at_level(logging.WARNING), pytest.raises(LiveDataError):
        fetch_live_flights("Delhi", "Goa", "2026-11-02")

    assert "google_flights search failed" in caplog.text and "ConnectionError" in caplog.text
    assert "super-secret-key" not in caplog.text


# ── CI and configuration files ───────────────────────────────────────────────

def test_ci_workflow_runs_pytest_without_real_keys():
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "python -m pytest tests" in workflow
    for name in ("GROQ_API_KEY", "SERPAPI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
        assert f'{name}: ""' in workflow


def test_env_example_lists_every_setting_the_code_reads():
    used = set()
    for path in ROOT.rglob("*.py"):
        if "venv" in path.parts or "tests" in path.parts:
            continue
        used |= set(re.findall(r'get_(?:int_)?setting\(\s*"([A-Z_]+)"', path.read_text(encoding="utf-8")))
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    missing = sorted(name for name in used if not re.search(rf"^{name}=", example, re.MULTILINE))
    assert used and not missing, f"add these to .env.example: {missing}"
