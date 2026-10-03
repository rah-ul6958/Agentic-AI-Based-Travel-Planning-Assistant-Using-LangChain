import pytest

from services import live_travel_service


@pytest.fixture(autouse=True)
def no_live_api(monkeypatch):
    """Tests never spend real SerpApi quota; live tests opt in with a mocked HTTP layer."""
    monkeypatch.setenv("SERPAPI_API_KEY", "")
    # No test may use a real key from .env either: blank every key before each test.
    # (load_dotenv never overwrites a variable that is already set, even to "".)
    for name in ("GROQ_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
        monkeypatch.setenv(name, "")
    live_travel_service.clear_cache()
