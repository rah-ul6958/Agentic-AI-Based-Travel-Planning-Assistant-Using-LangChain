# Voyance - Agentic AI Travel Planning Assistant

Voyance is a Streamlit travel planner that uses LangChain tools, Groq LLMs, Open-Meteo, and local travel datasets to produce flight, hotel, weather, day-by-day itinerary, budget, and travel-tip cards for Indian destinations.

## Features

- Agent pipeline: five LangChain tools (flights, hotels, weather, places, budget) feed a Groq LLM that composes the itinerary
- **Real-time flights and hotels** (Google Flights + Google Hotels via SerpApi) for your travel date, with booking links
- Sample-data fallback with direct **and 1-stop connecting flights** when no key is set or the API fails
- Budget-aware hotel selection and a deterministic budget calculator (numbers never come from the LLM)
- Live weather via Open-Meteo (cached), with a graceful fallback
- **Offline mode**: without a Groq key (or if the API fails) a data-driven itinerary is built from the same tool results
- Dark, responsive UI: popular routes, city swap, expandable day timeline, budget cards, tips
- Export as PDF or text, or save the trip as JSON locally

Supported cities: Bangalore, Chennai, Delhi, Goa, Hyderabad, Jaipur, Kerala, Kolkata, Manali, Mumbai.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env
```

Add your Groq key (free at https://console.groq.com) to `.env`:

```bash
GROQ_API_KEY=your_groq_key_here
GROQ_MODEL=openai/gpt-oss-120b   # optional; any chat model available on your Groq account
SERPAPI_API_KEY=your_serpapi_key  # optional; enables live flight & hotel prices
```

Get a SerpApi key at https://serpapi.com (free plan includes a monthly search quota; each trip plan uses 2 searches, cached for 30 minutes). Without it, the app uses the bundled sample data.

## Run

```bash
streamlit run app.py
```

Helpers: `.\scripts\start.ps1` (Windows) or `bash scripts/start.sh` (macOS/Linux).

## Project Structure

```text
travel_agent/
├── app.py                  # Streamlit UI (sidebar, progress, result page)
├── agent/travel_agent.py   # Tool orchestration, LLM prompt, offline fallback, output parser
├── tools/                  # LangChain @tool functions over the local datasets
├── services/               # SerpApi live flights/hotels, Open-Meteo weather, local storage
├── components/itinerary.py # Result rendering and PDF/text export
├── config/settings.py      # Cities, budget profiles, model config
├── data/                   # flights.json, hotels.json, places.json
├── styles/theme.css        # UI theme
├── .streamlit/config.toml  # Streamlit dark theme
├── utils/                  # Formatting and HTML-escaping helpers
└── tests/                  # Parser, tools, fallback and end-to-end UI tests
```

## Tests

```bash
python -m pytest tests
```

## Notes

- `.env` is ignored by Git. Do not commit real API keys.
- Saved itineraries are written to `data/saved_itineraries/` (ignored by Git).
- The JSON files in `data/` are sample datasets used when live data is unavailable. Places are always from the local dataset.
