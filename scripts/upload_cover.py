"""
scripts/upload_cover.py
Upload cover.png to Cloudflare R2 and update feed.xml on GitHub.
Usage: python scripts/upload_cover.py
"""
import os, sys, ssl, hmac, base64, hashlib, datetime, asyncio
from pathlib import Path

import certifi
import aiohttp
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

COVER_FILE = ROOT / "cover.png"

def _ssl():
    return ssl.create_default_context(cafile=certifi.where())

# ── SigV4 ─────────────────────────────────────────────────────────────────────

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()

def _signing_key(secret, date_stamp, region, service):
    k = _sign(f"AWS4{secret}".encode(), date_stamp)
    k = _sign(k, region); k = _sign(k, service)
    return _sign(k, "aws4_request")

def _r2_auth_headers(method, host, path, payload, content_type="image/png"):
    access_key = os.getenv("R2_ACCESS_KEY_ID", "")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "")
    now = datetime.datetime.utcnow()
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()
    to_sign = {"content-type": content_type, "host": host,
               "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
    canon_hdrs    = "".join(f"{k}:{v}\n" for k, v in sorted(to_sign.items()))
    signed_hdrs   = ";".join(sorted(to_sign.keys()))
    canon_request = "\n".join([method, path, "", canon_hdrs, signed_hdrs, payload_hash])
    region, service = "auto", "s3"
    cred_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, cred_scope,
                                  hashlib.sha256(canon_request.encode()).hexdigest()])
    sig = _sign(_signing_key(secret_key, date_stamp, region, service), string_to_sign).hex()
    auth = (f"AWS4-HMAC-SHA256 Credential={access_key}/{cred_scope},"
            f"SignedHeaders={signed_hdrs},Signature={sig}")
    return {"Authorization": auth, "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash, "content-type": content_type}

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    account_id = os.getenv("R2_ACCOUNT_ID", "")
    bucket     = os.getenv("R2_BUCKET_NAME", "")
    pub_domain = os.getenv("R2_PUBLIC_DOMAIN", "").rstrip("/")
    gh_user    = os.getenv("GITHUB_USERNAME", "")
    gh_repo    = os.getenv("GITHUB_REPO", "")
    gh_token   = os.getenv("GITHUB_TOKEN", "")
    gh_path    = os.getenv("GITHUB_FEED_PATH", "feed.xml")
    pages_url  = os.getenv("GITHUB_PAGES_DOMAIN") or f"https://{gh_user}.github.io/{gh_repo}"

    if not COVER_FILE.exists():
        print(f"❌ cover.png not found at {COVER_FILE}")
        sys.exit(1)

    data = COVER_FILE.read_bytes()
    cover_url = f"https://{pub_domain}/cover.png"

    connector = aiohttp.TCPConnector(ssl=_ssl())
    async with aiohttp.ClientSession(connector=connector) as session:

        # ── 1. Upload to R2 ───────────────────────────────────────────────────
        host = f"{account_id}.r2.cloudflarestorage.com"
        path = f"/{bucket}/cover.png"
        headers = _r2_auth_headers("PUT", host, path, data)
        headers["content-length"] = str(len(data))

        print(f"Uploading cover.png ({len(data)//1024} KB) to R2…")
        async with session.put(f"https://{host}{path}", headers=headers, data=data) as r:
            if r.status not in (200, 201, 204):
                body = await r.text()
                print(f"❌ Upload failed (HTTP {r.status}): {body}")
                sys.exit(1)

        # Verify public URL
        async with session.head(cover_url) as r:
            if r.status == 200:
                print(f"✅ Cover art live at: {cover_url}")
            else:
                print(f"❌ Upload failed — public URL returned HTTP {r.status}")
                sys.exit(1)

        # ── 2. Fetch current feed.xml from GitHub ─────────────────────────────
        gh_headers = {"Authorization": f"Bearer {gh_token}",
                      "Accept": "application/vnd.github+json"}
        api_url = f"https://api.github.com/repos/{gh_user}/{gh_repo}/contents/{gh_path}"

        print("Fetching current feed.xml from GitHub…")
        async with session.get(api_url, headers=gh_headers) as r:
            if r.status != 200:
                print(f"❌ GitHub GET failed (HTTP {r.status})")
                sys.exit(1)
            info = await r.json()
            sha = info["sha"]
            xml = base64.b64decode(info["content"]).decode("utf-8")

        # ── 3. Patch the XML ──────────────────────────────────────────────────
        image_tag   = f'<itunes:image href="{cover_url}"/>'
        image_block = (f'{image_tag}\n'
                       f'    <image>\n'
                       f'      <url>{cover_url}</url>\n'
                       f'      <title>The Latency Report</title>\n'
                       f'      <link>{pages_url}</link>\n'
                       f'    </image>')

        # Replace existing itunes:image line (keep any leading whitespace)
        import re
        xml = re.sub(r'[ \t]*<itunes:image[^>]*/>', image_block, xml)

        # ── 4. Push updated feed.xml ──────────────────────────────────────────
        body = {"message": "fix: update podcast cover art",
                "content": base64.b64encode(xml.encode()).decode(),
                "sha": sha}

        print("Pushing updated feed.xml to GitHub…")
        async with session.put(api_url, headers=gh_headers, json=body) as r:
            if r.status in (200, 201):
                print("✅ feed.xml updated on GitHub")
            else:
                text = await r.text()
                print(f"❌ GitHub push failed (HTTP {r.status}): {text}")
                sys.exit(1)

    # ── 5. Final instructions ─────────────────────────────────────────────────
    print()
    print("✅ Done! Now go to Apple Podcasts Connect:")
    print("  1. Go to https://podcastsconnect.apple.com")
    print("  2. Click Refresh next to your RSS feed URL")
    print("  3. The artwork error should clear")
    print("  4. Click Publish")

asyncio.run(main())
