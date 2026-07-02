"""
core/topic_generator.py
Uses Gemini (free tier) to:
  1. Pick a fresh, specific podcast topic from a category
  2. Find 3-5 real source URLs for that topic
  3. Generate a title + description after the podcast is made
"""
import os
import json
import asyncio
import time
import google.generativeai as genai
from typing import Optional
from db.database import log_request

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
_model = genai.GenerativeModel("gemini-1.5-flash")   # free tier model


async def _call_gemini(prompt: str, podcast_id: Optional[int] = None) -> str:
    """Thin async wrapper around the sync Gemini SDK."""
    start = time.monotonic()
    try:
        response = await asyncio.to_thread(_model.generate_content, prompt)
        latency = int((time.monotonic() - start) * 1000)
        await log_request("gemini", "generate_content", 200, True, podcast_id, latency)
        return response.text.strip()
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        await log_request("gemini", "generate_content", 500, False, podcast_id, latency)
        raise


async def pick_topic(category: str, used_topics: list[str]) -> str:
    """Ask Gemini to pick a specific, fresh podcast topic within a category."""
    used_block = "\n".join(f"- {t}" for t in used_topics[-20:]) if used_topics else "None yet"
    prompt = f"""You are a podcast producer. Pick ONE specific, interesting podcast topic
within the category: "{category}".

Rules:
- Be specific (e.g. "How vector databases changed RAG pipelines in 2025" not just "databases")
- Must be different from recently used topics listed below
- Timely and relevant to 2025-2026
- Suitable for a 10-15 minute conversational podcast between two hosts
- Return ONLY the topic string, nothing else

Recently used topics (avoid these):
{used_block}

Topic:"""
    topic = await _call_gemini(prompt)
    # Strip any leading/trailing quotes Gemini sometimes adds
    return topic.strip('"\'')


async def find_sources(topic: str, podcast_id: Optional[int] = None) -> list[str]:
    """Ask Gemini to produce 3-5 real, relevant URLs for the topic."""
    prompt = f"""You are a research assistant for a podcast about: "{topic}"

Find 3 to 5 real, publicly accessible URLs that would make great source material.
Prefer:
- Recent articles (2024-2026)
- Official documentation or research papers
- Well-known tech blogs (Wired, TechCrunch, ArsTechnica, Google Blog, etc.)
- Wikipedia pages for background

Return ONLY a JSON array of URL strings, no explanation.
Example format: ["https://...", "https://...", "https://..."]

URLs:"""
    raw = await _call_gemini(prompt, podcast_id)
    # Extract JSON array even if Gemini wraps it in backticks
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        urls = json.loads(raw.strip())
        return [u for u in urls if u.startswith("http")][:5]
    except json.JSONDecodeError:
        # fallback: extract anything that looks like a URL
        import re
        return re.findall(r'https?://[^\s\'"]+', raw)[:5]


async def generate_metadata(topic: str, podcast_id: Optional[int] = None) -> dict:
    """Generate a podcast title + description after the episode is created."""
    prompt = f"""You are writing metadata for a podcast episode about: "{topic}"

Generate:
1. A compelling episode title (max 80 characters, no clickbait)
2. A podcast description (150-200 words, engaging, SEO-friendly, describes what listeners will learn)

Return ONLY valid JSON in this exact format:
{{
  "title": "...",
  "description": "..."
}}"""
    raw = await _call_gemini(prompt, podcast_id)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw.strip())
        return {
            "title": data.get("title", topic),
            "description": data.get("description", f"A deep dive into {topic}.")
        }
    except json.JSONDecodeError:
        return {
            "title": topic[:80],
            "description": f"An in-depth podcast episode exploring {topic}."
        }
