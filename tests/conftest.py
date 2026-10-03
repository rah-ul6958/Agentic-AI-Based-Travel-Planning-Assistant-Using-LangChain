import pytest

from services import live_travel_service


@pytest.fixture(autouse=True)
def no_live_api(monkeypatch):
    """Tests never spend real SerpApi quota; live tests opt in with a mocked HTTP layer."""
    monkeypatch.setenv("SERPAPI_API_KEY", "")
    live_travel_service._cache.clear()
