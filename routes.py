"""
api/routes.py
FastAPI REST API for the dashboard UI.
All endpoints the frontend needs to display pipeline status.
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import asyncio

from db.database import (
    get_all_podcasts, get_stats_summary, get_daily_count, init_db
)
from core.pipeline import run_pipeline, run_batch

app = FastAPI(
    title="Podcast Pipeline API",
    description="Controls and monitors the AI podcast automation pipeline",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await init_db()
    print("[API] Database ready")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Stats & Dashboard ────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    """Summary stats for the dashboard header cards."""
    return await get_stats_summary()


@app.get("/api/podcasts")
async def list_podcasts(limit: int = 50, offset: int = 0):
    """Paginated list of all podcast records."""
    podcasts = await get_all_podcasts(limit=limit, offset=offset)
    return {"podcasts": podcasts, "total": len(podcasts)}


@app.get("/api/podcasts/{podcast_id}")
async def get_podcast(podcast_id: int):
    """Single podcast record."""
    podcasts = await get_all_podcasts(limit=1000)
    match = next((p for p in podcasts if p["id"] == podcast_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Podcast not found")
    return match


@app.get("/api/daily-limit")
async def daily_limit_status():
    """How many podcasts have been generated today vs the limit."""
    import os
    limit = int(os.getenv("DAILY_LIMIT", "3"))
    used = await get_daily_count()
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "at_limit": used >= limit
    }


# ── Manual Triggers ───────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    category: Optional[str] = None
    count: int = 1


_running_jobs: dict[str, bool] = {}


@app.post("/api/run")
async def trigger_run(req: RunRequest, background_tasks: BackgroundTasks):
    """
    Manually trigger a pipeline run (or batch).
    Runs in background so API returns immediately.
    """
    if _running_jobs.get("pipeline"):
        return {"status": "already_running",
                "message": "A pipeline run is already in progress."}

    async def _run():
        _running_jobs["pipeline"] = True
        try:
            if req.count > 1:
                await run_batch(n=min(req.count, 3), category=req.category)
            else:
                await run_pipeline(category=req.category)
        finally:
            _running_jobs["pipeline"] = False

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "message": f"Pipeline started for {req.count} episode(s)",
        "category": req.category
    }


@app.get("/api/run/status")
async def run_status():
    """Is a pipeline run currently in progress?"""
    return {"running": _running_jobs.get("pipeline", False)}


# ── Scheduler Info ────────────────────────────────────────────────────────────

@app.get("/api/schedule")
async def schedule_info():
    """Return current schedule config."""
    import os
    return {
        "cron": os.getenv("SCHEDULE_CRON", "0 9 * * *"),
        "daily_limit": int(os.getenv("DAILY_LIMIT", "3")),
        "categories": [
            c.strip() for c in os.getenv(
                "TOPIC_CATEGORIES",
                "AI and machine learning,software engineering"
            ).split(",")
        ]
    }
