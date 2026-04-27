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

_IG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "X-IG-App-ID": "936619743392459",
    "Accept": "*/*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.instagram.com/",
    "Origin": "https://www.instagram.com",
}

# ── helpers ──────────────────────────────────────────────────────────────────

def _normalize(username: str) -> str:
    return username.lstrip("@").strip()


# ── Instagram — intercept the GraphQL query Instagram web actually uses ────────

async def discover_instagram(username_or_url: str, session_id: str = "") -> Dict:
    username = _normalize(username_or_url.rstrip("/").split("/")[-1])
    profile_url = f"https://www.instagram.com/{username}/"
    posts: List[Dict] = []
    page_title = ""

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1280,900",
            ],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="fr-FR",
            timezone_id="Africa/Tunis",
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        if session_id:
            await ctx.add_cookies([{
                "name": "sessionid", "value": session_id,
                "domain": ".instagram.com", "path": "/",
                "httpOnly": True, "secure": True,
            }])
        page = await ctx.new_page()

        async def intercept(response):
            if "/graphql/query" not in response.url:
                return
            try:
                body = await response.json()
                # modern web: xdt_api__v1__feed__user_timeline_graphql_connection
                edges = (
                    body.get("data", {})
                    .get("xdt_api__v1__feed__user_timeline_graphql_connection", {})
                    .get("edges", [])
                )
                for edge in edges:
                    node = edge.get("node", {})
                    pk   = str(node.get("pk") or node.get("id", ""))
                    code = node.get("code")
                    if pk:
                        url = f"https://www.instagram.com/p/{code}/" if code else f"https://www.instagram.com/p/{pk}/"
                        if not any(p["external_id"] == pk for p in posts):
                            posts.append({"url": url, "external_id": pk})
                            logger.debug("Instagram found post: %s", url)
            except Exception:
                pass

        page.on("response", intercept)

        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            pass
        await asyncio.sleep(4)
        page_title = await page.title()

        # scroll to trigger more GraphQL loads
        for _ in range(6):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)

        await browser.close()

    logger.info("Instagram @%s: found %d posts (page: %s)", username, len(posts), page_title)
    return {"posts": posts, "page_title": page_title}


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
        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            pass
        await asyncio.sleep(3)
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
        try:
            await page.goto(channel_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            pass
        await asyncio.sleep(3)
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


# ── dispatcher ────────────────────────────────────────────────────────────────

async def discover_posts(platform: str, identifier: str, **kwargs):
    dispatch = {
        "instagram": discover_instagram,
        "tiktok": discover_tiktok,
        "youtube": discover_youtube,
    }
    fn = dispatch.get(platform)
    if not fn:
        raise ValueError(f"Unsupported platform: {platform}")
    return await fn(identifier, **kwargs)
