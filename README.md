# Voyance - Agentic AI Travel Planning Assistant

Voyance is a Streamlit travel planner that uses LangChain, Groq, Open-Meteo, and local travel datasets to produce flight, hotel, weather, itinerary, budget, and travel-tip cards for Indian destinations.

## Features

- Agent-assisted travel planning with deterministic tool calls
- Local JSON datasets for flights, hotels, and places
- Live weather via Open-Meteo with cached requests
- Premium dark Streamlit UI with responsive sidebar behavior
- Expandable itinerary timeline, budget cards, travel tips, PDF download, text copy, and local save
- Production folders for config, services, components, utilities, tests, docs, styles, and scripts

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Add your Groq key to `.env`:

```bash
GROQ_API_KEY=your_groq_key_here
```

## Run

```bash
streamlit run app.py
```

Windows helper:

```powershell
.\scripts\start.ps1
```

macOS/Linux helper:

```bash
bash scripts/start.sh
```

## Project Structure

```text
travel_agent/
├── app.py
├── requirements.txt
├── .env.example
├── README.md
├── agent/
├── tools/
├── services/
├── data/
├── utils/
├── components/
├── assets/
├── tests/
├── docs/
├── styles/
├── scripts/
└── config/
```

## Validation

```bash
python -m compileall app.py agent tools services utils components config tests
python -m pytest tests
streamlit run app.py
```

## Notes

- `.env` is ignored by Git. Do not commit real API keys.
- Saved itineraries are written to `data/saved_itineraries/` and ignored by Git.
- Some local routes do not have direct flight records in the sample dataset; the agent now handles that gracefully.
