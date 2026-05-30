import json

from langchain.tools import tool

from tools.data_access import load_json_dataset


@tool
def search_places(city: str, place_type: str = "all") -> str:
    """Find top tourist attractions and places of interest in a city.
    place_type can be: beach, heritage, nature, adventure, market, landmark,
    culture, wildlife, experience, or 'all' for everything."""
    try:
        places = load_json_dataset("places.json")

        results = [p for p in places if p["city"].strip().lower() == city.strip().lower()]

        if not results:
            available_cities = sorted({p["city"] for p in places})
            return json.dumps({
                "found": False,
                "message": f"No places found in {city}.",
                "available_cities": available_cities,
            }, indent=2)

        if place_type.lower() != "all":
            filtered = [p for p in results if p.get("type", "").lower() == place_type.lower()]
            if filtered:
                results = filtered

        results.sort(key=lambda p: float(p.get("rating", 0)), reverse=True)

        return json.dumps({
            "found": True,
            "city": city,
            "total_found": len(results),
            "top_places": results[:8],
        }, indent=2)

    except Exception as exc:
        return json.dumps({"error": f"Places search failed: {exc}"})