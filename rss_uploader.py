"""
core/rss_uploader.py
Uploads the podcast MP3 to RSS.com via their public API.
RSS.com then auto-distributes to Spotify, Apple Podcasts, Amazon Music, etc.

API docs: https://api.rss.com/v4/docs
"""
import os
import time
import aiohttp
from pathlib import Path
from typing import Optional
from db.database import log_request

RSS_API_BASE = "https://api.rss.com/v4"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('RSSCOM_API_KEY')}",
        "Accept": "application/json",
    }


async def upload_episode(
    audio_path: str,
    title: str,
    description: str,
    podcast_id: int,
    season: int = 1,
) -> Optional[dict]:
    """
    Upload the MP3 and create an episode on RSS.com.
    Returns dict with episode_id, spotify_url, apple_url (once propagated).
    """
    show_id = os.getenv("RSSCOM_SHOW_ID")
    if not show_id or not os.getenv("RSSCOM_API_KEY"):
        print("[RSS.com] Missing RSSCOM_API_KEY or RSSCOM_SHOW_ID in .env")
        return None

    audio_file = Path(audio_path)
    if not audio_file.exists():
        print(f"[RSS.com] Audio file not found: {audio_path}")
        return None

    start = time.monotonic()

    async with aiohttp.ClientSession() as session:
        # ── Step 1: Upload the audio file ────────────────────────────────────
        print(f"[RSS.com] Uploading audio ({audio_file.stat().st_size // 1024}KB)...")
        upload_url = f"{RSS_API_BASE}/shows/{show_id}/episodes/audio"

        with open(audio_path, "rb") as f:
            form = aiohttp.FormData()
            form.add_field(
                "audio",
                f,
                filename=audio_file.name,
                content_type="audio/mpeg"
            )
            async with session.post(upload_url, headers=_headers(), data=form) as resp:
                latency = int((time.monotonic() - start) * 1000)
                upload_data = await resp.json()

                if resp.status not in (200, 201):
                    print(f"[RSS.com] Audio upload failed: {resp.status} {upload_data}")
                    await log_request("rsscom", "upload_audio", resp.status,
                                     False, podcast_id, latency)
                    return None

                audio_guid = upload_data.get("guid") or upload_data.get("id")
                await log_request("rsscom", "upload_audio", resp.status,
                                 True, podcast_id, latency)
                print(f"[RSS.com] Audio uploaded, guid={audio_guid}")

        # ── Step 2: Create the episode ────────────────────────────────────────
        episode_payload = {
            "title": title,
            "description": description,
            "audio_guid": audio_guid,
            "season_number": season,
            "episode_type": "full",
            "explicit": False,
            "publish_date": None,   # None = publish immediately
        }

        ep_url = f"{RSS_API_BASE}/shows/{show_id}/episodes"
        async with session.post(ep_url, headers={**_headers(),
                                "Content-Type": "application/json"},
                                json=episode_payload) as resp:
            latency = int((time.monotonic() - start) * 1000)
            ep_data = await resp.json()

            if resp.status not in (200, 201):
                print(f"[RSS.com] Episode create failed: {resp.status} {ep_data}")
                await log_request("rsscom", "create_episode", resp.status,
                                 False, podcast_id, latency)
                return None

            await log_request("rsscom", "create_episode", resp.status,
                             True, podcast_id, latency)

            episode_id = ep_data.get("id") or ep_data.get("guid")
            print(f"[RSS.com] Episode published! id={episode_id}")

            return {
                "rss_episode_id": str(episode_id),
                # Spotify and Apple URLs propagate within hours via RSS feed
                # RSS.com provides these once indexed
                "spotify_url": ep_data.get("spotify_url"),
                "apple_url": ep_data.get("apple_url"),
            }
