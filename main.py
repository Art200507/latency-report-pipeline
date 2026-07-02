"""
main.py
Entry point. Boots:
  - SQLite DB
  - APScheduler (background cron)
  - FastAPI server (serves dashboard API)

Usage:
  python main.py              # run server + scheduler
  python main.py --run-now    # run pipeline once immediately then exit
  python main.py --run-now --category "AI and machine learning"
"""
import asyncio
import argparse
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))


def parse_args():
    parser = argparse.ArgumentParser(description="AI Podcast Pipeline")
    parser.add_argument("--run-now", action="store_true",
                        help="Run pipeline once immediately and exit")
    parser.add_argument("--category", type=str, default=None,
                        help="Force a specific topic category")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of podcasts to generate (max 3)")
    parser.add_argument("--port", type=int,
                        default=int(os.getenv("API_PORT", "8000")))
    return parser.parse_args()


async def run_once(category=None, count=1):
    """Run pipeline immediately and print result."""
    from db.database import init_db
    from core.pipeline import run_pipeline, run_batch
    await init_db()
    if count > 1:
        results = await run_batch(n=count, category=category)
        for r in results:
            print(f"\n[Result] {r}")
    else:
        result = await run_pipeline(category=category)
        print(f"\n[Result] {result}")


def run_server(port: int):
    """Start FastAPI + APScheduler."""
    import uvicorn
    from contextlib import asynccontextmanager
    from api.routes import app, lifespan
    from scheduler.jobs import create_scheduler

    scheduler = create_scheduler()
    original_lifespan = lifespan

    # Wrap the existing lifespan to also start/stop the scheduler
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def combined_lifespan(app):
        async with original_lifespan(app):
            scheduler.start()
            print("[Main] Scheduler started")
            try:
                yield
            finally:
                scheduler.shutdown()
                print("[Main] Scheduler stopped")

    app.router.lifespan_context = combined_lifespan

    print(f"[Main] Starting server on http://0.0.0.0:{port}")
    print(f"[Main] API docs at http://localhost:{port}/docs")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    args = parse_args()
    if args.run_now:
        asyncio.run(run_once(category=args.category, count=args.count))
    else:
        run_server(port=args.port)
