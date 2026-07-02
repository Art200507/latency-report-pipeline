"""
db/database.py
Async SQLite database for tracking all pipeline activity.
Tables: podcasts, topics, requests, daily_stats
"""
import aiosqlite
import asyncio
from datetime import datetime, date
from pathlib import Path
from typing import Optional
import json

DB_PATH = Path(__file__).parent.parent / "data" / "pipeline.db"


async def init_db():
    """Create all tables if they don't exist."""
    DB_PATH.parent.mkdir(exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS podcasts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                topic           TEXT    NOT NULL,
                category        TEXT,
                status          TEXT    NOT NULL DEFAULT 'pending',
                -- pending | generating | uploading | published | failed
                sources         TEXT,           -- JSON array of URLs used
                title           TEXT,
                description     TEXT,
                audio_path      TEXT,           -- local path to downloaded MP3
                rss_episode_id  TEXT,           -- RSS.com episode ID after upload
                spotify_url     TEXT,
                apple_url       TEXT,
                duration_sec    INTEGER,
                notebooklm_id   TEXT,           -- notebook ID from notebooklm-py
                error_msg       TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                published_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                stat_date       TEXT PRIMARY KEY,  -- YYYY-MM-DD
                generated       INTEGER DEFAULT 0,
                published       INTEGER DEFAULT 0,
                failed          INTEGER DEFAULT 0,
                requests_made   INTEGER DEFAULT 0  -- total API calls that day
            );

            CREATE TABLE IF NOT EXISTS api_requests (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                service     TEXT NOT NULL,   -- gemini | notebooklm | rsscom
                endpoint    TEXT,
                status_code INTEGER,
                success     INTEGER DEFAULT 1,
                podcast_id  INTEGER REFERENCES podcasts(id),
                latency_ms  INTEGER,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS topic_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topic       TEXT NOT NULL,
                used_at     TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(topic)
            );
        """)
        await db.commit()
    print(f"[DB] Initialized at {DB_PATH}")


async def create_podcast_record(topic: str, category: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO podcasts (topic, category, status) VALUES (?, ?, 'pending')",
            (topic, category)
        )
        await db.commit()
        return cursor.lastrowid


async def update_podcast(podcast_id: int, **fields):
    """Update any fields on a podcast record."""
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [podcast_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE podcasts SET {set_clause} WHERE id = ?", values
        )
        await db.commit()


async def log_request(service: str, endpoint: str, status_code: int,
                      success: bool, podcast_id: Optional[int] = None,
                      latency_ms: Optional[int] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO api_requests
               (service, endpoint, status_code, success, podcast_id, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (service, endpoint, status_code, int(success), podcast_id, latency_ms)
        )
        # bump daily stats
        today = date.today().isoformat()
        await db.execute(
            """INSERT INTO daily_stats (stat_date, requests_made)
               VALUES (?, 1)
               ON CONFLICT(stat_date) DO UPDATE SET
               requests_made = requests_made + 1""",
            (today,)
        )
        await db.commit()


async def bump_daily_stat(field: str, date_str: Optional[str] = None):
    """Increment a counter in daily_stats. field: generated|published|failed"""
    today = date_str or date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"""INSERT INTO daily_stats (stat_date, {field})
                VALUES (?, 1)
                ON CONFLICT(stat_date) DO UPDATE SET
                {field} = {field} + 1""",
            (today,)
        )
        await db.commit()


async def mark_topic_used(topic: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO topic_history (topic, used_at) VALUES (?, datetime('now'))",
            (topic,)
        )
        await db.commit()


async def get_used_topics(days: int = 30) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT topic FROM topic_history WHERE used_at >= datetime('now', ? || ' days')",
            (f"-{days}",)
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


async def get_daily_count(date_str: Optional[str] = None) -> int:
    """How many podcasts were generated today."""
    today = date_str or date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM podcasts WHERE date(created_at) = ? AND status != 'failed'",
            (today,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


# ── Dashboard queries ─────────────────────────────────────────────────────────

async def get_all_podcasts(limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM podcasts
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_stats_summary() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        total = (await (await db.execute("SELECT COUNT(*) as c FROM podcasts")).fetchone())["c"]
        published = (await (await db.execute(
            "SELECT COUNT(*) as c FROM podcasts WHERE status='published'")).fetchone())["c"]
        failed = (await (await db.execute(
            "SELECT COUNT(*) as c FROM podcasts WHERE status='failed'")).fetchone())["c"]
        today_count = await get_daily_count()

        cursor = await db.execute(
            "SELECT * FROM daily_stats ORDER BY stat_date DESC LIMIT 7"
        )
        recent_days = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT * FROM api_requests ORDER BY created_at DESC LIMIT 20"
        )
        recent_requests = [dict(r) for r in await cursor.fetchall()]

        return {
            "total_podcasts": total,
            "published": published,
            "failed": failed,
            "today_count": today_count,
            "recent_days": recent_days,
            "recent_requests": recent_requests,
        }
