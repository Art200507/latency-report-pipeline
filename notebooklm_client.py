"""
core/notebooklm_client.py
Wraps notebooklm-py to:
  1. Create a notebook for a topic
  2. Add source URLs
  3. Trigger Audio Overview (podcast) generation
  4. Download the MP3
  5. Clean up the notebook
"""
import asyncio
import os
import time
from pathlib import Path
from typing import Optional

from db.database import log_request, update_podcast

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


async def generate_podcast(
    topic: str,
    sources: list[str],
    podcast_id: int
) -> Optional[str]:
    """
    Full NotebookLM flow. Returns local path to the downloaded MP3, or None on failure.

    Uses notebooklm-py (unofficial Python API).
    Docs: https://github.com/teng-lin/notebooklm-py
    """
    try:
        # Import here so the rest of the app works even if library isn't installed yet
        from notebooklm import NotebookLMClient

        audio_path = OUTPUT_DIR / f"podcast_{podcast_id}.mp3"
        start = time.monotonic()

        async with NotebookLMClient.from_storage() as client:
            # 1. Create notebook
            await update_podcast(podcast_id, status="generating",
                                 notebooklm_id="creating...")
            notebook = await client.notebooks.create(
                f"Podcast: {topic[:60]}"
            )
            nb_id = notebook.id
            await update_podcast(podcast_id, notebooklm_id=nb_id)

            # 2. Add sources (URLs)
            for url in sources:
                try:
                    await client.sources.add_url(nb_id, url, wait=True)
                except Exception as e:
                    print(f"[NotebookLM] Warning: could not add {url}: {e}")

            # 3. Trigger podcast generation
            task = await client.artifacts.generate_audio(
                nb_id,
                instructions=(
                    f"Create an engaging, informative podcast episode about: {topic}. "
                    "Make it conversational, accessible, and suitable for a general tech audience. "
                    "Cover key concepts, recent developments, and practical implications."
                )
            )

            # 4. Wait for completion (polls internally)
            await client.artifacts.wait_for_completion(nb_id, task.task_id)

            # 5. Download MP3
            await client.artifacts.download_audio(nb_id, str(audio_path))

            # 6. Clean up notebook to save quota
            try:
                await client.notebooks.delete(nb_id)
            except Exception:
                pass  # non-fatal

        latency = int((time.monotonic() - start) * 1000)
        await log_request("notebooklm", "generate_audio", 200, True, podcast_id, latency)

        if audio_path.exists():
            print(f"[NotebookLM] Audio saved: {audio_path}")
            return str(audio_path)
        return None

    except ImportError:
        print("[NotebookLM] notebooklm-py not installed. Run: pip install notebooklm-py")
        await log_request("notebooklm", "generate_audio", 500, False, podcast_id)
        return None
    except Exception as e:
        print(f"[NotebookLM] Error: {e}")
        await log_request("notebooklm", "generate_audio", 500, False, podcast_id)
        raise


async def get_audio_duration(audio_path: str) -> Optional[int]:
    """Return duration in seconds using ffprobe if available, else None."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "csv=p=0", audio_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return int(float(stdout.decode().strip()))
    except Exception:
        return None
