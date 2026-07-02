"""
scripts/run_pipeline.py
Standalone pipeline runner — no FastAPI server needed.
Used by GitHub Actions and for manual CLI runs.

Usage:
    python scripts/run_pipeline.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from db.database import init_db
from core.pipeline import run_pipeline


async def main():
    await init_db()
    result = await run_pipeline()
    print(f"\n[Runner] Done: {result}")
    if result["status"] not in ("published", "skipped"):
        sys.exit(1)


asyncio.run(main())
