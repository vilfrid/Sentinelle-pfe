"""
Profile scrapers: given a creator username or profile URL,
discover all available post/video URLs for that platform.
Returns a list of dicts: [{"url": str, "external_id": str}, ...]
"""
import asyncio
import logging
import re
from typing import List, Dict

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    window.chrome = { runtime: {} };
"""

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
            except Exception:
                pass

        page.on("response", intercept)

        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            pass
        await asyncio.sleep(4)
        page_title = await page.title()

        prev = 0
        no_new = 0
        for _ in range(20):
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
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
        )
        await ctx.add_init_script(_STEALTH_SCRIPT)
        page = await ctx.new_page()

        async def intercept(response):
            if "/api/post/item_list/" in response.url or "/api/user/post" in response.url:
                try:
                    body = await response.json()
                    for item in body.get("itemList", []):
                        aweme_id = item.get("id") or item.get("aweme_id")
                        if aweme_id and not any(p["external_id"] == str(aweme_id) for p in posts):
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
        await asyncio.sleep(5)
        for _ in range(10):
            await page.mouse.wheel(0, 3000)
            await asyncio.sleep(2)
        await browser.close()

    logger.info("TikTok profile %s: found %d videos", username, len(posts))
    return posts


# ── YouTube — use yt-dlp (no browser needed) ──────────────────────────────────

async def discover_youtube(channel_url: str) -> List[Dict]:
    import yt_dlp

    if not channel_url.startswith("http"):
        channel_url = f"https://www.youtube.com/@{channel_url}/videos"
    elif "/videos" not in channel_url:
        channel_url = channel_url.rstrip("/") + "/videos"

    ydl_opts = {
        "skip_download": True,
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "playlistend": 30,
    }

    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(channel_url, download=False)

    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(None, _extract)
    except Exception as exc:
        logger.error("yt-dlp channel discovery failed for %s: %s", channel_url, exc)
        return []

    posts = []
    if info:
        for entry in info.get("entries", []):
            if entry and entry.get("id"):
                vid_id = entry["id"]
                posts.append({
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                    "external_id": vid_id,
                })

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
