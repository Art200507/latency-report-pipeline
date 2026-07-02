"""
core/pipeline.py
Main orchestrator. One run = one podcast episode.

Flow:
  1. Check daily limit
  2. Pick topic via Gemini
  3. Find source URLs via Gemini
  4. Generate podcast audio via NotebookLM
  5. Generate title + description via Gemini
  6. Upload to RSS.com (→ Spotify + Apple)
  7. Log everything to DB
"""
import os
import json
import asyncio
import traceback
from datetime import date
from typing import Optional

from db.database import (
    create_podcast_record, update_podcast,
    mark_topic_used, get_used_topics, get_daily_count,
    bump_daily_stat
)
from core.topic_generator import pick_topic, find_sources, generate_metadata
from core.notebooklm_client import generate_podcast, get_audio_duration
from core.rss_uploader import upload_episode


DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "3"))
TOPIC_CATEGORIES = [
    c.strip() for c in os.getenv(
        "TOPIC_CATEGORIES",
        "AI and machine learning,software engineering,data science,cybersecurity,startups and tech"
    ).split(",")
]


async def run_pipeline(category: Optional[str] = None) -> dict:
    """
    Execute one full podcast generation pipeline run.
    Returns a result dict with status and details.
    """
    result = {"status": "unknown", "podcast_id": None, "topic": None}

    # ── 0. Daily limit check ─────────────────────────────────────────────────
    today_count = await get_daily_count()
    if today_count >= DAILY_LIMIT:
        msg = f"Daily limit reached ({today_count}/{DAILY_LIMIT}). Skipping."
        print(f"[Pipeline] {msg}")
        return {"status": "skipped", "reason": msg}

    # ── 1. Pick a topic ──────────────────────────────────────────────────────
    import random
    chosen_category = category or random.choice(TOPIC_CATEGORIES)
    used_topics = await get_used_topics(days=30)
    print(f"[Pipeline] Picking topic from category: {chosen_category}")

    try:
        topic = await pick_topic(chosen_category, used_topics)
        print(f"[Pipeline] Topic: {topic}")
    except Exception as e:
        print(f"[Pipeline] Topic generation failed: {e}")
        return {"status": "failed", "reason": f"Topic pick failed: {e}"}

    # ── 2. Create DB record ──────────────────────────────────────────────────
    podcast_id = await create_podcast_record(topic, chosen_category)
    result["podcast_id"] = podcast_id
    result["topic"] = topic
    await mark_topic_used(topic)

    try:
        # ── 3. Find sources ──────────────────────────────────────────────────
        print(f"[Pipeline] Finding sources for: {topic}")
        sources = await find_sources(topic, podcast_id)
        if not sources:
            raise ValueError("No sources found for topic.")
        print(f"[Pipeline] Sources ({len(sources)}): {sources}")
        await update_podcast(podcast_id, sources=json.dumps(sources))

        # ── 4. Generate podcast via NotebookLM ───────────────────────────────
        print(f"[Pipeline] Generating podcast audio via NotebookLM...")
        audio_path = await generate_podcast(topic, sources, podcast_id)
        if not audio_path:
            raise ValueError("NotebookLM returned no audio file.")

        duration = await get_audio_duration(audio_path)
        await update_podcast(podcast_id,
                             audio_path=audio_path,
                             duration_sec=duration,
                             status="uploading")
        await bump_daily_stat("generated")

        # ── 5. Generate metadata ─────────────────────────────────────────────
        print(f"[Pipeline] Generating title + description...")
        meta = await generate_metadata(topic, podcast_id)
        title = meta["title"]
        description = meta["description"]
        await update_podcast(podcast_id, title=title, description=description)
        print(f"[Pipeline] Title: {title}")

        # ── 6. Upload to RSS.com ─────────────────────────────────────────────
        print(f"[Pipeline] Uploading to RSS.com...")
        upload_result = await upload_episode(
            audio_path=audio_path,
            title=title,
            description=description,
            podcast_id=podcast_id,
        )

        if upload_result:
            await update_podcast(
                podcast_id,
                status="published",
                rss_episode_id=upload_result.get("rss_episode_id"),
                spotify_url=upload_result.get("spotify_url"),
                apple_url=upload_result.get("apple_url"),
                published_at=date.today().isoformat(),
            )
            await bump_daily_stat("published")
            print(f"[Pipeline] ✅ Published! episode_id={upload_result.get('rss_episode_id')}")
            result["status"] = "published"
        else:
            # Audio generated but upload failed — still useful
            await update_podcast(podcast_id, status="upload_failed")
            result["status"] = "upload_failed"
            print(f"[Pipeline] ⚠️ Audio generated but RSS upload failed.")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        tb = traceback.format_exc()
        print(f"[Pipeline] ❌ Error: {error_msg}\n{tb}")
        await update_podcast(podcast_id, status="failed", error_msg=error_msg)
        await bump_daily_stat("failed")
        result["status"] = "failed"
        result["error"] = error_msg

    return result


async def run_batch(n: int = 1, category: Optional[str] = None) -> list[dict]:
    """Run the pipeline n times (respects daily limit)."""
    results = []
    for i in range(n):
        print(f"\n[Pipeline] ── Run {i+1}/{n} ──────────────────────")
        result = await run_pipeline(category)
        results.append(result)
        if result["status"] == "skipped":
            break
        # Small delay between runs to be polite to APIs
        if i < n - 1:
            await asyncio.sleep(10)
    return results
