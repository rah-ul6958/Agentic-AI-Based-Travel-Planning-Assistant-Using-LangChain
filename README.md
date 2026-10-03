# Voyance - Agentic AI Travel Planning Assistant

Voyance is a Streamlit travel planner that uses LangChain tools, Groq LLMs, SerpApi (Google Flights and Google Hotels), Open-Meteo, and local travel datasets to produce round-trip flights, hotel, weather, day-by-day itinerary, budget, and travel-tip cards for Indian destinations.

**Live demo:** _coming soon - add your Streamlit Community Cloud link here_

[![Tests](https://github.com/rah-ul6958/Agentic-AI-Based-Travel-Planning-Assistant-Using-LangChain/actions/workflows/tests.yml/badge.svg)](https://github.com/rah-ul6958/Agentic-AI-Based-Travel-Planning-Assistant-Using-LangChain/actions/workflows/tests.yml)

## Features

- **LangGraph agent**: the standard searches run in parallel, then a Groq LLM decides what else to do - try nearby airports when there is no flight, search again for a cheaper hotel when the chosen one is over budget - within a fixed limit of extra tool calls
- **Follow-up chat**: after a plan is shown, ask for changes such as "make day 2 more relaxed" or "find a cheaper hotel"; the agent re-runs only the tools the request needs
- **Real-time round-trip flights and hotels** (Google Flights + Google Hotels via SerpApi) for your dates and number of travellers
- Each flight and hotel card shows where its data came from: "Live - fetched at HH:MM IST", "Cached - X min ago" or "Sample data"
- Google price insights ("Prices are lower than usual for this route") and an on-demand "See booking options" seller list
- Deterministic budget: return flights x travellers, hotel rooms x nights (taxes labelled), food per person per day - **numbers never come from the LLM**
- Live weather via Open-Meteo; trips too far ahead show "Forecast not available yet" instead of made-up weather
- **Works with no API keys at all**: sample flights/hotels and an offline itinerary built from the same tool data
- Export as PDF or text; save trips to Supabase (optional) or local JSON files

Supported cities: Bangalore, Chennai, Delhi, Goa, Hyderabad, Jaipur, Kerala, Kolkata, Manali, Mumbai.

## Run locally

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env
streamlit run app.py
```

Windows helper: `.\scripts\start.ps1` - macOS/Linux helper: `bash scripts/start.sh`.

## Configuration

All settings are read from `.env` locally and from **Streamlit secrets** when deployed. Every key is optional - without keys the app runs on sample data with an offline itinerary.

| Setting | Needed for | Where to get it |
|---|---|---|
| `GROQ_API_KEY` | AI-written itineraries | https://console.groq.com (free tier) |
| `GROQ_MODEL` | Choosing the Groq model (default `openai/gpt-oss-120b`) | Any chat model on your Groq account |
| `SERPAPI_API_KEY` | Live flight and hotel prices | https://serpapi.com (free plan has a monthly search quota) |
| `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_TABLE` | Saving trips in a cloud database | https://supabase.com (see below) |
| `PLAN_LIMIT`, `PLAN_WINDOW_MINUTES` | Trip plans allowed per browser session (default 5 per 10 minutes) | - |
| `AGENT_MAX_TOOL_CALLS` | Most extra tool calls the agent may make per plan or follow-up (default 4, `0` = off) | - |
| `LOG_LEVEL` | Log detail: `DEBUG`, `INFO` (default), `WARNING`, `ERROR` | - |

Never commit `.env` or `.streamlit/secrets.toml` - both are in `.gitignore`.

### API quota per trip plan

| Action | SerpApi searches |
|---|---|
| Plan a trip | 3 (outbound flights, return flights, hotels) |
| Agent fixing a problem (no flight, hotel over budget) | up to 4 more (`AGENT_MAX_TOOL_CALLS`) |
| Follow-up request in the chat | 0 to 4, only for the tools the request needs |
| Click "See outbound/return booking options" | 1 per click |
| Repeat the same search within 30 minutes | 0 (cached and shared by all users of the server) |

Groq calls: 1 per plan when nothing needs fixing (the itinerary), plus 1 per agent step when there is a problem; a follow-up uses at least 2 (agent + itinerary). Open-Meteo is free and needs no key.

## How the agent works

```text
START -> gather -> (agent <-> tools) -> budget -> write -> END
```

- **gather** runs the five standard searches at the same time (new plans only).
- **agent**: the LLM reads the results, the problems the code found and any follow-up request, and decides which tools to call - or that nothing is needed.
- **tools** runs those calls, keeps a result only if it is better than the current one, and counts every call against `AGENT_MAX_TOOL_CALLS`.
- **budget** recalculates the budget in code; **write** has the LLM write the day plan (offline fallback when it is unavailable).

If nothing is wrong and there is no follow-up request, `gather` goes straight to `budget`, so a normal plan costs no extra LLM call. The code is in `agent/graph.py`.

## Deploy to Streamlit Community Cloud

1. Push this repository to GitHub (the `.env` file stays on your computer).
2. Go to https://share.streamlit.io, click **Create app**, and pick this repository, the branch, and `app.py` as the main file.
3. Open **Advanced settings**, choose **Python 3.13**, and paste your secrets in TOML format (see `.streamlit/secrets.toml.example`):

   ```toml
   GROQ_API_KEY = "your_groq_key"
   SERPAPI_API_KEY = "your_serpapi_key"
   # Optional
   SUPABASE_URL = "https://your-project.supabase.co"
   SUPABASE_KEY = "your_supabase_anon_or_publishable_key"
   ```

4. Click **Deploy**. Logs (including API failures, which never include keys) are under **Manage app > Logs**.
5. Put the app URL in the "Live demo" line at the top of this README.

To change secrets later: **App settings > Secrets**. The app restarts with the new values.

### Optional: save trips in Supabase

The cloud server's disk is wiped on restart, so local trip files do not last there. To keep saved trips, create a Supabase project and run this in its **SQL Editor**:

```sql
create table public.saved_trips (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  source text,
  destination text,
  start_date date,
  payload jsonb not null
);

alter table public.saved_trips enable row level security;

-- The app may only ADD trips. There is no select policy on purpose, so the key
-- in the app cannot be used to read other people's saved trips.
grant insert on public.saved_trips to anon;
create policy "app can insert trips" on public.saved_trips
  for insert to anon with check (true);
```

Then set `SUPABASE_URL` (Project Settings > API > Project URL) and `SUPABASE_KEY` (the **anon / publishable** key, not the service role key). If Supabase is not configured or fails, trips are saved to `data/saved_itineraries/` instead.

## Data accuracy

- **Live prices come from Google Flights and Google Hotels via SerpApi** and are a snapshot at the time shown on each card. Prices and availability change quickly - **the final price is always confirmed on the airline, hotel or booking site.**
- Flight prices are searched per person (1 adult) and multiplied by the number of travellers; seat availability for the whole group is confirmed when booking.
- Hotel prices are per room for up to 2 guests. They include taxes and fees when Google reports a separate pre-tax price; otherwise the card says "excl. taxes" or "taxes may be extra".
- Weather is a forecast from Open-Meteo, available about 16 days ahead.
- When live data is unavailable, cards are clearly labelled **Sample data**. Sample flights, hotels and places in `data/` are for demonstration only.
- The AI writes only the day-by-day plan and tips. Flights, hotel, weather and every number in the budget come from code and APIs.

## Tests and CI

```bash
python -m pytest tests
```

The tests never use real API keys: SerpApi is mocked and the itinerary runs offline. GitHub Actions (`.github/workflows/tests.yml`) runs the same tests on every push and pull request.

## Project structure

```text
travel_agent/
├── app.py                  # Streamlit UI (sidebar, progress, result page, rate limit)
├── agent/graph.py          # LangGraph agent: gather -> agent <-> tools -> budget -> write
├── agent/travel_agent.py   # Planning steps, LLM prompts, offline fallback, output parser
├── tools/                  # LangChain @tool functions (flights, hotels, nearby airports, weather, places, budget)
├── services/               # SerpApi live data, Open-Meteo weather, trip storage (Supabase or files)
├── components/itinerary.py # Result cards, booking options, PDF/text export
├── config/settings.py      # Cities, budget profiles, settings from .env / Streamlit secrets
├── data/                   # Sample flights.json, hotels.json, places.json
├── utils/                  # Formatting, trip maths (nights, rooms), rate limit
├── styles/theme.css        # UI theme
├── .streamlit/             # Theme config and secrets example
├── .github/workflows/      # CI: run pytest on every push
└── tests/                  # Unit, tool, agent and end-to-end UI tests
```
