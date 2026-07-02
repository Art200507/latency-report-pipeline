#!/usr/bin/env python3
"""
scripts/setup_distribution.py
One-time setup validator for Cloudflare R2 + GitHub Pages distribution.

Run from the project root with the venv activated:
  python3 scripts/setup_distribution.py

Checks:
  1. All required env vars are present
  2. R2 connection: upload 1-byte test file, verify public URL, delete it
  3. GitHub connection: repo exists and is reachable
  4. feed.xml: creates initial feed if it doesn't exist yet

Prints the final RSS feed URL and exact submission steps for Spotify + Apple.
"""
import asyncio
import base64
import datetime
import hashlib
import hmac
import os
import sys
from pathlib import Path

# ── Bootstrap: load .env from project root ────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass  # dotenv optional; user may have exported vars manually

import ssl
import certifi
import aiohttp  # noqa: E402  (after sys.path insert)

def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())

GITHUB_API = "https://api.github.com"

REQUIRED_VARS = [
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
    "R2_PUBLIC_DOMAIN",
    "GITHUB_USERNAME",
    "GITHUB_REPO",
    "GITHUB_TOKEN",
    "GITHUB_FEED_PATH",
]


# ── SigV4 helpers (duplicated from rss_uploader for standalone use) ───────────

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
    access_key = os.getenv("R2_ACCESS_KEY_ID", "")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "")

    now        = datetime.datetime.utcnow()
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()

    to_sign = {
        "content-type":         content_type,
        "host":                 host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date":           amz_date,
    }
    canonical_headers  = "".join(f"{k}:{v}\n" for k, v in sorted(to_sign.items()))
    signed_headers_str = ";".join(sorted(to_sign.keys()))

    canonical_request = "\n".join([
        method, path, "",
        canonical_headers, signed_headers_str, payload_hash,
    ])

    region  = "auto"
    service = "s3"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    sig = hmac.new(
        _signing_key(secret_key, date_stamp, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers_str}, Signature={sig}"
        ),
        "x-amz-date":            amz_date,
        "x-amz-content-sha256":  payload_hash,
        "Content-Type":          content_type,
    }


# ── Feed helpers ──────────────────────────────────────────────────────────────

def _pages_base_url() -> str:
    domain = os.getenv("GITHUB_PAGES_DOMAIN", "").strip()
    if domain:
        return f"https://{domain}"
    return (
        f"https://{os.getenv('GITHUB_USERNAME', '')}"
        f".github.io/{os.getenv('GITHUB_REPO', '')}"
    )


def _empty_feed_xml() -> str:
    base      = _pages_base_url()
    feed_path = os.getenv("GITHUB_FEED_PATH", "feed.xml")
    title     = os.getenv("PODCAST_TITLE",       "AI Podcast")
    desc      = os.getenv("PODCAST_DESCRIPTION", "An AI-generated tech podcast.")
    author    = os.getenv("PODCAST_AUTHOR",      "")
    email     = os.getenv("PODCAST_EMAIL",       "")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"\n'
        '     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"\n'
        '     xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{title}</title>\n"
        f"    <link>{base}</link>\n"
        f"    <description>{desc}</description>\n"
        "    <language>en-us</language>\n"
        f'    <atom:link href="{base}/{feed_path}" rel="self" type="application/rss+xml"/>\n'
        f"    <itunes:author>{author}</itunes:author>\n"
        "    <itunes:owner>\n"
        f"      <itunes:name>{author}</itunes:name>\n"
        f"      <itunes:email>{email}</itunes:email>\n"
        "    </itunes:owner>\n"
        "    <itunes:explicit>false</itunes:explicit>\n"
        '    <itunes:category text="Technology"/>\n'
        "  </channel>\n"
        "</rss>"
    )


def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
    }


# ── Check steps ───────────────────────────────────────────────────────────────

def check_env() -> bool:
    print("── [1/4] Checking environment variables ──────────────────────")
    missing = [v for v in REQUIRED_VARS if not os.getenv(v, "").strip()]
    if missing:
        for v in missing:
            print(f"  ✗ Missing: {v}")
        return False
    print(f"  ✓ All {len(REQUIRED_VARS)} required variables present")
    return True


async def test_r2(session: aiohttp.ClientSession) -> bool:
    print("── [2/4] Testing Cloudflare R2 ───────────────────────────────")
    account_id    = os.getenv("R2_ACCOUNT_ID", "")
    bucket        = os.getenv("R2_BUCKET_NAME", "")
    public_domain = os.getenv("R2_PUBLIC_DOMAIN", "")

    host          = f"{account_id}.r2.cloudflarestorage.com"
    test_key      = "_setup_test.txt"
    test_payload  = b"ok"
    path          = f"/{bucket}/{test_key}"

    # Upload
    headers = _r2_auth_headers("PUT", host, path, test_payload, "text/plain")
    async with session.put(f"https://{host}{path}", data=test_payload, headers=headers) as resp:
        if resp.status not in (200, 204):
            print(f"  ✗ Upload failed: HTTP {resp.status}")
            print(f"    Body: {await resp.text()}")
            print("    → Check R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME")
            return False
    print("  ✓ R2 upload successful")

    # Verify public URL
    public_url = f"https://{public_domain}/{test_key}"
    async with session.get(public_url) as resp:
        if resp.status != 200:
            print(f"  ✗ Public URL not accessible: {public_url} → HTTP {resp.status}")
            print("    → Enable public access: R2 bucket → Settings → Public Access → Allow Access")
            return False
    print(f"  ✓ Public URL accessible: https://{public_domain}/...")

    # Delete test file
    del_headers = _r2_auth_headers("DELETE", host, path, b"", "text/plain")
    async with session.delete(f"https://{host}{path}", headers=del_headers) as _:
        pass  # non-fatal
    print("  ✓ Test file cleaned up")
    return True


async def test_github(session: aiohttp.ClientSession) -> bool:
    print("── [3/4] Testing GitHub connection ───────────────────────────")
    username = os.getenv("GITHUB_USERNAME", "")
    repo     = os.getenv("GITHUB_REPO", "")

    async with session.get(
        f"{GITHUB_API}/repos/{username}/{repo}", headers=_gh_headers()
    ) as resp:
        if resp.status == 401:
            print("  ✗ Token invalid or expired — check GITHUB_TOKEN")
            return False
        if resp.status == 404:
            print(f"  ✗ Repo '{username}/{repo}' not found")
            print("    → Create a public repo and enable GitHub Pages:")
            print("      Settings → Pages → Source: Deploy from branch → main / root")
            return False
        if resp.status != 200:
            print(f"  ✗ Unexpected HTTP {resp.status}")
            return False
        data = await resp.json()

    if data.get("private"):
        print("  ⚠ Repo is private — GitHub Pages requires public repo on free plan")
    else:
        print(f"  ✓ Repo found: {data['full_name']} (public)")

    if not data.get("has_pages"):
        print("  ⚠ GitHub Pages not yet enabled for this repo")
        print("    → Settings → Pages → Source: Deploy from branch → main / root")
    else:
        print("  ✓ GitHub Pages is enabled")
    return True


async def create_feed_if_missing(session: aiohttp.ClientSession) -> bool:
    print("── [4/4] Initialising feed.xml ───────────────────────────────")
    username  = os.getenv("GITHUB_USERNAME", "")
    repo      = os.getenv("GITHUB_REPO", "")
    feed_path = os.getenv("GITHUB_FEED_PATH", "feed.xml")
    url = f"{GITHUB_API}/repos/{username}/{repo}/contents/{feed_path}"

    async with session.get(url, headers=_gh_headers()) as resp:
        if resp.status == 200:
            print(f"  ✓ {feed_path} already exists — skipping creation")
            return True
        if resp.status != 404:
            print(f"  ✗ Unexpected HTTP {resp.status} when checking feed")
            return False

    # Create initial feed
    xml  = _empty_feed_xml()
    body = {
        "message": "chore: initialise podcast RSS feed",
        "content": base64.b64encode(xml.encode("utf-8")).decode("utf-8"),
        "branch":  "main",
    }
    async with session.put(url, json=body, headers=_gh_headers()) as resp:
        if resp.status not in (200, 201):
            text = await resp.text()
            print(f"  ✗ Failed to create {feed_path}: HTTP {resp.status}")
            print(f"    {text[:200]}")
            return False

    print(f"  ✓ {feed_path} created in {username}/{repo}")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║      AI Podcast — Distribution Setup Check          ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    if not check_env():
        print()
        print("✗ Fix missing env vars in .env and re-run.")
        sys.exit(1)
    print()

    connector = aiohttp.TCPConnector(ssl=_ssl_context())
    async with aiohttp.ClientSession(connector=connector) as session:
        r2_ok   = await test_r2(session)
        print()
        gh_ok   = await test_github(session)
        print()
        feed_ok = await create_feed_if_missing(session) if gh_ok else False
        print()

    if not (r2_ok and gh_ok and feed_ok):
        print("✗ Setup incomplete — fix the errors above and re-run.")
        sys.exit(1)

    feed_path = os.getenv("GITHUB_FEED_PATH", "feed.xml")
    feed_url  = f"{_pages_base_url()}/{feed_path}"

    print("╔══════════════════════════════════════════════════════╗")
    print("║               ✓  Setup Complete!                    ║")
    print("╠══════════════════════════════════════════════════════╣")
    print("║                                                      ║")
    print("║  Your RSS feed URL:                                  ║")
    print(f"║  {feed_url:<52}║")
    print("║                                                      ║")
    print("║  ONE-TIME manual steps (do these once only):         ║")
    print("║                                                      ║")
    print("║  1. Submit to Spotify:                               ║")
    print("║     https://podcasters.spotify.com                   ║")
    print("║     → Add podcast → paste your RSS feed URL above    ║")
    print("║                                                      ║")
    print("║  2. Submit to Apple Podcasts:                        ║")
    print("║     https://podcastsconnect.apple.com                ║")
    print("║     → + → paste your RSS feed URL above              ║")
    print("║                                                      ║")
    print("║  3. Wait 24-48 hours for approval.                   ║")
    print("║                                                      ║")
    print("║  After approval: python main.py handles everything   ║")
    print("║  forever. Every new episode auto-appears on both     ║")
    print("║  platforms. You never touch this again.              ║")
    print("║                                                      ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()


if __name__ == "__main__":
    asyncio.run(main())
