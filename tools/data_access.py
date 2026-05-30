import json
from functools import lru_cache

from config.settings import DATA_DIR


@lru_cache(maxsize=8)
def load_json_dataset(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    with path.open(encoding="utf-8") as file:
        return json.load(file)
