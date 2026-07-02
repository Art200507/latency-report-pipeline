"""
core/topic_generator.py
Uses Groq (free) to:
  1. Pick a fresh, specific podcast topic from a category
  2. Find 3-5 real source URLs for that topic
  3. Generate a title + description after the podcast is made

Falls back to Gemini if GROQ_API_KEY is not set.
"""
import os
import json
import asyncio
import time
from typing import Optional
from db.database import log_request

_MODEL_GROQ   = "llama-3.3-70b-versatile"
_MODEL_GEMINI = "gemini-2.0-flash-lite"

_groq_client   = None
_gemini_client = None


def _get_client():
    """Return (client, 'groq'|'gemini') depending on which key is set."""
    global _groq_client, _gemini_client

    if os.getenv("GROQ_API_KEY"):
        if _groq_client is None:
            from openai import AsyncOpenAI
            _groq_client = AsyncOpenAI(
                api_key=os.getenv("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1",
            )
        return _groq_client, "groq"

    if _gemini_client is None:
        import google.genai as genai
        _gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _gemini_client, "gemini"


async def _call_llm(prompt: str, podcast_id: Optional[int] = None) -> str:
    """Call whichever LLM is configured and return the text response."""
    start = time.monotonic()
    client, provider = _get_client()
    try:
        if provider == "groq":
            response = await client.chat.completions.create(
                model=_MODEL_GROQ,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            text = response.choices[0].message.content.strip()
        else:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=_MODEL_GEMINI,
                contents=prompt,
            )
            text = response.text.strip()

        latency = int((time.monotonic() - start) * 1000)
        await log_request(provider, "generate_content", 200, True, podcast_id, latency)
        return text
    except Exception:
        latency = int((time.monotonic() - start) * 1000)
        await log_request(provider, "generate_content", 500, False, podcast_id, latency)
        raise


async def pick_topic(category: str, used_topics: list[str]) -> str:
    """Ask the LLM to pick a specific, fresh podcast topic within a category."""
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
    topic = await _call_llm(prompt)
    return topic.strip('"\'')


async def find_sources(topic: str, podcast_id: Optional[int] = None) -> list[str]:
    """Ask the LLM to produce 3-5 real, relevant URLs for the topic."""
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
    raw = await _call_llm(prompt, podcast_id)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        urls = json.loads(raw.strip())
        return [u for u in urls if u.startswith("http")][:5]
    except json.JSONDecodeError:
        import re
        return re.findall(r'https?://[^\s\'"]+', raw)[:5]


async def generate_metadata(topic: str, podcast_id: Optional[int] = None) -> dict:
    """Generate a podcast title + description after the episode is created."""
    import datetime
    date_str = datetime.date.today().strftime("%B %d, %Y")

    prompt = f"""You are writing metadata for a podcast episode of 'The Latency Report' about: "{topic}"
The hosts are Jade Kelman (male) and Kristi Campbell (female).

Generate:
1. A short episode name (max 50 characters, just the topic name, no date, no clickbait)
2. A description that starts EXACTLY with:
   "In this podcast, Jade and Kristi will talk about [topic]."
   Then list the full agenda in 3 bullet points:
   - What the topic is and why it matters (plain English)
   - The latest news and developments around it
   - A rapid fire Q&A between Jade and Kristi
   End with one sentence on what the listener will walk away knowing.
   Total description: 100-150 words.

Return ONLY valid JSON in this exact format:
{{
  "name": "...",
  "description": "..."
}}"""
    raw = await _call_llm(prompt, podcast_id)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw.strip())
        name = data.get("name", topic)[:50]
        title = f"{date_str} — {name}"
        return {
            "title": title,
            "description": data.get("description", f"In this podcast, Jade and Kristi will talk about {topic}.")
        }
    except json.JSONDecodeError:
        return {
            "title": f"{date_str} — {topic[:50]}",
            "description": f"In this podcast, Jade and Kristi will talk about {topic}."
        }
