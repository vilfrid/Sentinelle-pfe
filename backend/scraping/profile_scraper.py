"""
Profile scrapers: given a creator username or profile URL,
discover all available post/video URLs for that platform.
Returns a list of dicts: [{"url": str, "external_id": str}, ...]
"""
import asyncio
import json
import logging
import re
from typing import List, Dict

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────

def _normalize(username: str) -> str:
    return username.lstrip("@").strip()


# ── Instagram ─────────────────────────────────────────────────────────────────

async def discover_instagram(username_or_url: str, session_id: str = "") -> List[Dict]:
    username = _normalize(username_or_url.rstrip("/").split("/")[-1])
    profile_url = f"https://www.instagram.com/{username}/"
    posts: List[Dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        if session_id:
            await ctx.add_cookies([{
                "name": "sessionid", "value": session_id,
                "domain": ".instagram.com", "path": "/",
            }])
        page = await ctx.new_page()

        async def intercept(response):
            if "/api/v1/feed/user/" in response.url or "PolarisProfilePostsQuery" in response.url:
                try:
                    body = await response.json()
                    items = body.get("items", []) or []
                    for item in items:
                        pk = item.get("pk") or item.get("id")
                        code = item.get("code")
                        media_type = item.get("media_type", 1)
                        if pk:
                            url = f"https://www.instagram.com/p/{code}/" if code else f"https://www.instagram.com/p/{pk}/"
                            posts.append({"url": url, "external_id": str(pk)})
                except Exception:
                    pass

        page.on("response", intercept)
        await page.goto(profile_url, wait_until="networkidle", timeout=30_000)
        for _ in range(6):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
        await browser.close()

    logger.info("Instagram profile %s: found %d posts", username, len(posts))
    return posts


# ── TikTok ────────────────────────────────────────────────────────────────────

async def discover_tiktok(username_or_url: str) -> List[Dict]:
    username = _normalize(username_or_url.rstrip("/").split("/")[-1])
    profile_url = f"https://www.tiktok.com/@{username}"
    posts: List[Dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context()
        page = await ctx.new_page()

        async def intercept(response):
            if "/api/post/item_list/" in response.url or "/api/user/post" in response.url:
                try:
                    body = await response.json()
                    for item in body.get("itemList", []):
                        aweme_id = item.get("id") or item.get("aweme_id")
                        if aweme_id:
                            posts.append({
                                "url": f"https://www.tiktok.com/@{username}/video/{aweme_id}",
                                "external_id": str(aweme_id),
                            })
                except Exception:
                    pass

        page.on("response", intercept)
        await page.goto(profile_url, wait_until="networkidle", timeout=30_000)
        for _ in range(8):
            await page.mouse.wheel(0, 3000)
            await asyncio.sleep(1.5)
        await browser.close()

    logger.info("TikTok profile %s: found %d videos", username, len(posts))
    return posts


# ── YouTube ───────────────────────────────────────────────────────────────────

_YT_VIDEO_RE = re.compile(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"')
_YT_TITLE_RE = re.compile(r'"title"\s*:\s*\{\s*"runs"\s*:\s*\[\s*\{\s*"text"\s*:\s*"([^"]+)"')


async def discover_youtube(channel_url: str) -> List[Dict]:
    if not channel_url.startswith("http"):
        channel_url = f"https://www.youtube.com/@{channel_url}/videos"
    elif "/videos" not in channel_url:
        channel_url = channel_url.rstrip("/") + "/videos"

    posts: List[Dict] = []
    seen: set = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        async def intercept(response):
            if "/youtubei/v1/browse" in response.url:
                try:
                    text = await response.text()
                    for vid_id in _YT_VIDEO_RE.findall(text):
                        if vid_id not in seen:
                            seen.add(vid_id)
                            posts.append({
                                "url": f"https://www.youtube.com/watch?v={vid_id}",
                                "external_id": vid_id,
                            })
                except Exception:
                    pass

        page.on("response", intercept)
        await page.goto(channel_url, wait_until="networkidle", timeout=30_000)
        no_new = 0
        prev = 0
        for _ in range(15):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            if len(posts) == prev:
                no_new += 1
                if no_new >= 4:
                    break
            else:
                no_new = 0
            prev = len(posts)
        await browser.close()

    logger.info("YouTube channel %s: found %d videos", channel_url, len(posts))
    return posts


# ── Facebook ──────────────────────────────────────────────────────────────────

async def discover_facebook(page_url: str, cookies: list = None) -> List[Dict]:
    if not page_url.startswith("http"):
        page_url = f"https://www.facebook.com/{page_url}"
    posts: List[Dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        if cookies:
            await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        async def intercept(response):
            if "/api/graphql/" in response.url:
                try:
                    text = await response.text()
                    for match in re.finditer(r'"post_id"\s*:\s*"(\d+)"', text):
                        pid = match.group(1)
                        url = f"https://www.facebook.com/permalink.php?story_fbid={pid}"
                        if not any(p["external_id"] == pid for p in posts):
                            posts.append({"url": url, "external_id": pid})
                except Exception:
                    pass

        page.on("response", intercept)
        await page.goto(page_url, wait_until="networkidle", timeout=30_000)
        for _ in range(8):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
        await browser.close()

    logger.info("Facebook page %s: found %d posts", page_url, len(posts))
    return posts


# ── dispatcher ────────────────────────────────────────────────────────────────

async def discover_posts(platform: str, identifier: str, **kwargs) -> List[Dict]:
    dispatch = {
        "instagram": discover_instagram,
        "tiktok": discover_tiktok,
        "youtube": discover_youtube,
        "facebook": discover_facebook,
    }
    fn = dispatch.get(platform)
    if not fn:
        raise ValueError(f"Unsupported platform: {platform}")
    return await fn(identifier, **kwargs)
