"""
core/rss_uploader.py  —  Cloudflare R2 + GitHub Pages RSS distribution
Uploads the MP3 to R2, injects a new <item> into feed.xml, pushes it to
GitHub so GitHub Pages serves the RSS feed to Spotify & Apple Podcasts.

Flow:
  1. PUT  MP3 → R2 (SigV4 signed)                → public audio URL
  2. GET  feed.xml from GitHub API                → current XML + sha
  3. Inject new <item> into XML
  4. PUT  updated feed.xml → GitHub API
"""
import os
import time
import hmac
import base64
import hashlib
import datetime
from email.utils import formatdate
from pathlib import Path
from typing import Optional

import ssl
import certifi
import aiohttp

from db.database import log_request


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())

GITHUB_API = "https://api.github.com"


# ── AWS Signature Version 4 helpers ───────────────────────────────────────────

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, date_stamp: str, region: str, service: str) -> bytes:
    k = _sign(f"AWS4{secret}".encode("utf-8"), date_stamp)
    k = _sign(k, region)
    k = _sign(k, service)
    return _sign(k, "aws4_request")


def _r2_auth_headers(
    method: str,
    host: str,
    path: str,
    payload: bytes,
    content_type: str = "application/octet-stream",
) -> dict:
    """Return the Authorization + x-amz-* headers for an R2 request."""
    access_key = os.getenv("R2_ACCESS_KEY_ID", "")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "")

    now = datetime.datetime.utcnow()
    amz_date  = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()

    # Headers that will be signed (must be lowercase, sorted)
    to_sign = {
        "content-type":          content_type,
        "host":                  host,
        "x-amz-content-sha256":  payload_hash,
        "x-amz-date":            amz_date,
    }
    canonical_headers  = "".join(f"{k}:{v}\n" for k, v in sorted(to_sign.items()))
    signed_headers_str = ";".join(sorted(to_sign.keys()))

    # Canonical request (empty string for query)
    canonical_request = "\n".join([
        method, path, "",
        canonical_headers, signed_headers_str, payload_hash,
    ])

    # String to sign
    region  = "auto"
    service = "s3"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    # Signature
    sig_key   = _signing_key(secret_key, date_stamp, region, service)
    signature = hmac.new(sig_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers_str}, Signature={signature}"
        ),
        "x-amz-date":            amz_date,
        "x-amz-content-sha256":  payload_hash,
        "Content-Type":          content_type,
    }


# ── Cloudflare R2 upload ──────────────────────────────────────────────────────

async def _upload_r2(
    session: aiohttp.ClientSession, mp3: Path, podcast_id: int
) -> str:
    """Upload MP3 to R2 and return its public URL."""
    account_id    = os.getenv("R2_ACCOUNT_ID", "")
    bucket        = os.getenv("R2_BUCKET_NAME", "")
    public_domain = os.getenv("R2_PUBLIC_DOMAIN", "")

    host    = f"{account_id}.r2.cloudflarestorage.com"
    path    = f"/{bucket}/{mp3.name}"
    payload = mp3.read_bytes()
    headers = _r2_auth_headers("PUT", host, path, payload, "audio/mpeg")

    start = time.monotonic()
    async with session.put(f"https://{host}{path}", data=payload, headers=headers) as resp:
        latency = int((time.monotonic() - start) * 1000)
        ok = resp.status in (200, 204)
        await log_request("r2", "upload", resp.status, ok, podcast_id, latency)
        if not ok:
            body = await resp.text()
            raise RuntimeError(f"R2 upload failed ({resp.status}): {body[:300]}")

    public_url = f"https://{public_domain}/{mp3.name}"
    print(f"[Uploader] MP3 uploaded → {public_url}")
    return public_url


# ── GitHub Pages RSS feed ─────────────────────────────────────────────────────

def _pages_base_url() -> str:
    domain = os.getenv("GITHUB_PAGES_DOMAIN", "").strip()
    if domain:
        return f"https://{domain}"
    username = os.getenv("GITHUB_USERNAME", "")
    repo     = os.getenv("GITHUB_REPO", "")
    return f"https://{username}.github.io/{repo}"


def _empty_feed_xml() -> str:
    base      = _pages_base_url()
    feed_path = os.getenv("GITHUB_FEED_PATH", "feed.xml")
    title     = os.getenv("PODCAST_TITLE",       "AI Podcast")
    desc      = os.getenv("PODCAST_DESCRIPTION", "An AI-generated tech podcast.")
    author    = os.getenv("PODCAST_AUTHOR",      "")
    email     = os.getenv("PODCAST_EMAIL",       "")
    cover = os.getenv("PODCAST_COVER_URL", "")
    cover_tag = f'\n    <itunes:image href="{cover}"/>' if cover else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{title}</title>
    <link>{base}</link>
    <description>{desc}</description>
    <language>en-us</language>{cover_tag}
    <atom:link href="{base}/{feed_path}" rel="self" type="application/rss+xml"/>
    <itunes:author>{author}</itunes:author>
    <itunes:owner>
      <itunes:name>{author}</itunes:name>
      <itunes:email>{email}</itunes:email>
    </itunes:owner>
    <itunes:explicit>false</itunes:explicit>
    <itunes:category text="Technology"/>
  </channel>
</rss>"""


def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
    }


async def _fetch_feed(
    session: aiohttp.ClientSession, podcast_id: int
) -> tuple[str, Optional[str]]:
    """Return (xml_content, sha_or_None). Creates empty feed if file absent."""
    username  = os.getenv("GITHUB_USERNAME", "")
    repo      = os.getenv("GITHUB_REPO", "")
    feed_path = os.getenv("GITHUB_FEED_PATH", "feed.xml")
    url = f"{GITHUB_API}/repos/{username}/{repo}/contents/{feed_path}"

    start = time.monotonic()
    async with session.get(url, headers=_gh_headers()) as resp:
        latency = int((time.monotonic() - start) * 1000)
        if resp.status == 404:
            await log_request("github", "get_feed", 404, True, podcast_id, latency)
            return _empty_feed_xml(), None
        ok = resp.status == 200
        await log_request("github", "get_feed", resp.status, ok, podcast_id, latency)
        resp.raise_for_status()
        data = await resp.json()

    xml = base64.b64decode(data["content"]).decode("utf-8")
    return xml, data["sha"]


async def _push_feed(
    session: aiohttp.ClientSession,
    xml: str,
    sha: Optional[str],
    podcast_id: int,
) -> None:
    """PUT the updated feed.xml back to GitHub."""
    username  = os.getenv("GITHUB_USERNAME", "")
    repo      = os.getenv("GITHUB_REPO", "")
    feed_path = os.getenv("GITHUB_FEED_PATH", "feed.xml")
    url = f"{GITHUB_API}/repos/{username}/{repo}/contents/{feed_path}"

    body: dict = {
        "message": "chore: add podcast episode",
        "content": base64.b64encode(xml.encode("utf-8")).decode("utf-8"),
        "branch":  "main",
    }
    if sha:
        body["sha"] = sha

    start = time.monotonic()
    async with session.put(url, json=body, headers=_gh_headers()) as resp:
        latency = int((time.monotonic() - start) * 1000)
        ok = resp.status in (200, 201)
        await log_request("github", "push_feed", resp.status, ok, podcast_id, latency)
        if not ok:
            text = await resp.text()
            raise RuntimeError(f"GitHub feed push failed ({resp.status}): {text[:300]}")


def _make_item(
    title: str,
    description: str,
    audio_url: str,
    file_size: int,
    episode_guid: str,
    duration_sec: Optional[int],
) -> str:
    pub_date = formatdate(usegmt=True)
    duration_tag = (
        f"\n      <itunes:duration>{duration_sec}</itunes:duration>"
        if duration_sec else ""
    )
    return (
        f"  <item>\n"
        f"      <title>{title}</title>\n"
        f"      <description><![CDATA[{description}]]></description>\n"
        f'      <enclosure url="{audio_url}" length="{file_size}" type="audio/mpeg"/>\n'
        f'      <guid isPermaLink="false">{episode_guid}</guid>\n'
        f"      <pubDate>{pub_date}</pubDate>{duration_tag}\n"
        f"      <itunes:explicit>false</itunes:explicit>\n"
        f"      <itunes:episodeType>full</itunes:episodeType>\n"
        f"    </item>"
    )


def _inject_item(feed_xml: str, item_xml: str) -> str:
    """Insert episode before first <item> (newest-first) or before </channel>."""
    if "<item>" in feed_xml:
        return feed_xml.replace("<item>", item_xml + "\n\n  <item>", 1)
    return feed_xml.replace("</channel>", item_xml + "\n</channel>")


# ── Public interface ──────────────────────────────────────────────────────────

async def upload_episode(
    audio_path: str,
    title: str,
    description: str,
    podcast_id: int,
    duration_sec: Optional[int] = None,
    season: int = 1,
) -> Optional[dict]:
    """
    Upload MP3 to Cloudflare R2 and publish via GitHub Pages RSS feed.
    Returns result dict on success, None on any failure.
    """
    mp3 = Path(audio_path)
    if not mp3.exists():
        print(f"[Uploader] Audio file not found: {audio_path}")
        return None

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=_ssl_context())) as session:
        try:
            # 1. Upload MP3 to R2
            audio_url = await _upload_r2(session, mp3, podcast_id)

            # 2. Fetch current feed (or generate empty template)
            feed_xml, sha = await _fetch_feed(session, podcast_id)

            # 3. Build episode item and inject into feed
            episode_guid = f"episode-{podcast_id}-{int(time.time())}"
            item_xml = _make_item(
                title=title,
                description=description,
                audio_url=audio_url,
                file_size=mp3.stat().st_size,
                episode_guid=episode_guid,
                duration_sec=duration_sec,
            )
            updated_xml = _inject_item(feed_xml, item_xml)

            # 4. Push updated feed to GitHub
            await _push_feed(session, updated_xml, sha, podcast_id)

            feed_path = os.getenv("GITHUB_FEED_PATH", "feed.xml")
            feed_url  = f"{_pages_base_url()}/{feed_path}"
            print(f"[Uploader] RSS feed updated → {feed_url}")

            return {
                "rss_episode_id": episode_guid,
                "feed_url":       feed_url,
                "audio_url":      audio_url,
                "spotify_url":    None,
                "apple_url":      None,
            }

        except Exception as e:
            print(f"[Uploader] Distribution failed: {e}")
            await log_request("uploader", "upload_episode", 500, False, podcast_id)
            return None
