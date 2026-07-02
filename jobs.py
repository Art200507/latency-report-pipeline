"""
scheduler/jobs.py
APScheduler setup. Runs the pipeline on a cron schedule.
Default: daily at 9am. Override via SCHEDULE_CRON env var.
"""
import os
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from core.pipeline import run_pipeline

# Default: 9:00 AM daily. Format: minute hour day month day_of_week
SCHEDULE_CRON = os.getenv("SCHEDULE_CRON", "0 9 * * *")


async def scheduled_job():
    print("[Scheduler] ⏰ Triggered scheduled podcast generation")
    result = await run_pipeline()
    print(f"[Scheduler] Run complete: {result}")


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # Parse cron string into APScheduler trigger
    parts = SCHEDULE_CRON.split()
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
    else:
        # fallback: 9am daily
        minute, hour, day, month, day_of_week = "0", "9", "*", "*", "*"

    trigger = CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone="America/New_York"
    )

    scheduler.add_job(
        scheduled_job,
        trigger=trigger,
        id="daily_podcast",
        name="Daily Podcast Generation",
        replace_existing=True,
        misfire_grace_time=3600,   # run up to 1hr late if server was down
    )

    print(f"[Scheduler] Scheduled job: {SCHEDULE_CRON} (America/New_York)")
    return scheduler
