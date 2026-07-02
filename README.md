# AI Podcast Pipeline

Fully automated podcast generation and publishing — zero cost.

```
Groq / Gemini (free) → picks topic + finds sources
NotebookLM (free)    → generates two-host podcast MP3
Groq / Gemini (free) → writes title + description
Podbean (free)       → publishes to Spotify & Apple Podcasts automatically
APScheduler          → runs daily, no manual work needed
FastAPI + React      → dashboard at http://localhost:8000
```

---

## Quick Start

```bash
# 1. Clone / download project, then:
./setup.sh

# 2. Fill in .env
#    GROQ_API_KEY          → https://console.groq.com (free)
#    PODBEAN_CLIENT_ID     → developers.podbean.com → Register App
#    PODBEAN_CLIENT_SECRET → same app registration page

# 3. Authenticate NotebookLM once (opens browser)
source .venv/bin/activate
python3 -m notebooklm login

# 4. Start the server
python3 main.py
# Dashboard: http://localhost:8000
# API docs:  http://localhost:8000/docs

# 5. Test immediately
python3 main.py --run-now
```

---

## Distribution Setup (Podbean → Spotify + Apple)

1. **Register a Podbean API app** at [developers.podbean.com](https://developers.podbean.com)
   - Click "Register a New App" → fill in name/description
   - Copy **Client ID** and **Client Secret** into `.env`

2. **Create a podcast show** at [podbean.com](https://podbean.com) (one-time, free plan)

3. **Connect Spotify + Apple Podcasts** from your Podbean dashboard → **Distribution** (one-time)

4. Every episode published via the API auto-appears on both platforms within hours.

---

## Environment Variables (`.env`)

| Variable | Required | Where to get it |
|---|---|---|
| `GROQ_API_KEY` | ✅ | [console.groq.com](https://console.groq.com) → API Keys (free) |
| `PODBEAN_CLIENT_ID` | ✅ | [developers.podbean.com](https://developers.podbean.com) → Register App |
| `PODBEAN_CLIENT_SECRET` | ✅ | Same app registration page |
| `GEMINI_API_KEY` | optional | Fallback LLM if Groq key not set |
| `SCHEDULE_CRON` | optional | Cron string. Default: `0 9 * * *` (9am daily) |
| `DAILY_LIMIT` | optional | Max episodes/day. Default: `3` (NotebookLM free tier) |
| `TOPIC_CATEGORIES` | optional | Comma-separated seed categories |
| `API_PORT` | optional | Server port. Default: `8000` |

---

## CLI Flags

```bash
python3 main.py                        # start server + scheduler
python3 main.py --run-now              # run pipeline once and exit
python3 main.py --run-now --category "AI and machine learning"
python3 main.py --run-now --count 2   # generate 2 episodes
python3 main.py --port 9000           # custom port
```

---

## Dashboard Features

- **Header stats**: Total Episodes, Published, Failed, Today's Count
- **Daily Limit bar**: visual progress toward the 3/day free tier cap
- **Episode table**: Topic, Category, Status (color-coded), Created, Published, Duration, Spotify/Apple links
- **7-day bar chart**: generated vs failed per day
- **API request log**: last 20 requests with service, endpoint, status, latency
- **Run Now button**: triggers pipeline, shows live loading state (polls every 3s)
- **Auto-refresh**: every 30 seconds

---

## API Endpoints

```
GET  /health           # server health check
GET  /api/stats        # summary stats + recent days + recent requests
GET  /api/podcasts     # paginated list of all episodes
GET  /api/daily-limit  # today's usage vs limit
POST /api/run          # manually trigger pipeline {count, category}
GET  /api/run/status   # is a run currently in progress?
GET  /api/schedule     # current cron + categories config
GET  /docs             # interactive Swagger UI
```

---

## Project Structure

```
podcast_pipeline/
├── main.py                    # entry point
├── env.example                # config template → copy to .env
├── requirements.txt
├── setup.sh                   # one-time setup script
├── core/
│   ├── pipeline.py            # main orchestrator
│   ├── topic_generator.py     # Groq/Gemini: topic + sources + metadata
│   ├── notebooklm_client.py   # NotebookLM audio generation
│   └── rss_uploader.py        # Podbean upload + distribution
├── db/
│   └── database.py            # SQLite async (tracking + stats)
├── scheduler/
│   └── jobs.py                # APScheduler cron runner
├── api/
│   └── routes.py              # FastAPI REST endpoints + static serving
├── frontend/                  # React + Tailwind source (Vite)
│   └── src/App.jsx            # single-page dashboard
├── static/                    # built frontend (auto-generated)
├── output/                    # downloaded MP3s (auto-created)
└── data/                      # SQLite DB (auto-created)
```

---

## Cost

| Service | Cost |
|---|---|
| Groq (Llama 3.3 70B) | Free (14,400 req/day) |
| NotebookLM | Free (3 podcasts/day) |
| Podbean | Free plan |
| **Total** | **$0** |

---

## Frontend Development

```bash
cd frontend
npm run dev    # hot-reload dev server at http://localhost:5173
               # proxies /api/* → http://localhost:8000

npm run build  # rebuild → ../static/ (FastAPI serves it automatically)
```
