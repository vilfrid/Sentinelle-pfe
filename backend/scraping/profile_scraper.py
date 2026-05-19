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


def _parse_tiktok_cookies(raw: str) -> list:
    """Parse a raw browser cookie string into Playwright cookie dicts."""
    cookies = []
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".tiktok.com",
                "path": "/",
            })
    return cookies


# ── Instagram — intercept the GraphQL query Instagram web actually uses ────────

async def discover_instagram(username_or_url: str, session_id: str = "") -> Dict:
    username = _normalize(username_or_url.rstrip("/").split("/")[-1])
    profile_url = f"https://www.instagram.com/{username}/"
    posts: List[Dict] = []
    page_title = ""
    creator_info: Dict = {}

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
            url = response.url

            # ── User profile info (/api/v1/users/web_profile_info/ or /userinfo/) ──
            if "web_profile_info" in url or ("/api/v1/users/" in url and "/info" in url):
                try:
                    body = await response.json()
                    # Two possible shapes: {data: {user: {...}}} or {user: {...}}
                    user = (
                        body.get("data", {}).get("user")
                        or body.get("user")
                        or {}
                    )
                    if user and not creator_info:
                        # Private API shape: follower_count, biography, full_name
                        # GraphQL shape: edge_followed_by.count, biography, full_name
                        follower_count = (
                            user.get("follower_count")
                            or (user.get("edge_followed_by") or {}).get("count")
                        )
                        creator_info.update({
                            "follower_count":  follower_count,
                            "bio":             user.get("biography", ""),
                            "display_name":    user.get("full_name", ""),
                            "is_verified":     bool(user.get("is_verified", False)),
                            "avatar_url":      user.get("profile_pic_url", ""),
                            "media_count":     user.get("media_count") or (user.get("edge_owner_to_timeline_media") or {}).get("count"),
                        })
                        logger.info("Instagram: profile info captured — %s followers", follower_count)
                except Exception:
                    pass

            if "/graphql/query" not in url:
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
                    if not pk:
                        continue
                    url = f"https://www.instagram.com/p/{code}/" if code else f"https://www.instagram.com/p/{pk}/"
                    if any(p["external_id"] == pk for p in posts):
                        continue

                    caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
                    caption = caption_edges[0].get("node", {}).get("text", "") if caption_edges else ""

                    posts.append({
                        "url": url,
                        "external_id": pk,
                        "likes": node.get("like_count") or node.get("edge_liked_by", {}).get("count", 0) or 0,
                        "views": node.get("video_view_count") or node.get("play_count") or 0,
                        "shares": 0,
                        "comment_count": node.get("edge_media_to_comment", {}).get("count", 0) or 0,
                        "caption": caption[:500],
                        "posted_at": node.get("taken_at_timestamp"),
                    })
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
    return {"posts": posts, "page_title": page_title, "creator_info": creator_info}


# ── TikTok ────────────────────────────────────────────────────────────────────

async def discover_tiktok(username_or_url: str) -> Dict:
    from app.config import settings
    username = _normalize(username_or_url.rstrip("/").split("/")[-1])
    profile_url = f"https://www.tiktok.com/@{username}"
    posts: List[Dict] = []
    creator_info: Dict = {}

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
        if settings.TIKTOK_COOKIES:
            await ctx.add_cookies(_parse_tiktok_cookies(settings.TIKTOK_COOKIES))
            logger.info("TikTok: injected %d cookies", len(_parse_tiktok_cookies(settings.TIKTOK_COOKIES)))
        else:
            logger.warning("TikTok: TIKTOK_COOKIES not set — running without session")
        page = await ctx.new_page()

        async def intercept(response):
            url = response.url
            # Log every tiktok.com API call so we can see what's happening
            if "tiktok.com/api" in url:
                logger.info("TikTok API response: %d %s", response.status, url[:120])
            if "/api/post/item_list/" in url or "/api/user/post" in url:
                try:
                    body = await response.json()
                    items = body.get("itemList", [])
                    logger.info("TikTok item_list: %d items, hasMore=%s", len(items), body.get("hasMore"))
                    for item in items:
                        aweme_id = item.get("id") or item.get("aweme_id")
                        if aweme_id and not any(p["external_id"] == str(aweme_id) for p in posts):
                            stats = item.get("stats", {})
                            posts.append({
                                "url": f"https://www.tiktok.com/@{username}/video/{aweme_id}",
                                "external_id": str(aweme_id),
                                "likes":         stats.get("diggCount", 0) or 0,
                                "views":         stats.get("playCount", 0) or 0,
                                "shares":        stats.get("shareCount", 0) or 0,
                                "comment_count": stats.get("commentCount", 0) or 0,
                                "collects":      stats.get("collectCount", 0) or 0,
                                "caption":       (item.get("desc", "") or "")[:500],
                                "posted_at":     item.get("createTime"),
                            })
                        # Extract creator profile from author field (same data on every item)
                        if not creator_info and items:
                            author = items[0].get("author", {})
                            if author:
                                creator_info.update({
                                    "follower_count": author.get("followerCount", 0),
                                    "bio":            author.get("signature", ""),
                                    "display_name":   author.get("nickname", ""),
                                    "is_verified":    bool(author.get("verified", False)),
                                    "total_likes":    author.get("heartCount", 0),
                                    "video_count":    author.get("videoCount", 0),
                                })
                except Exception as exc:
                    logger.warning("TikTok: failed to parse item_list response: %s", exc)

        page.on("response", intercept)
        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            logger.warning("TikTok: page.goto error: %s", exc)

        page_title = await page.title()
        logger.info("TikTok: page loaded — title: %r", page_title)

        await asyncio.sleep(5)
        for _ in range(10):
            await page.mouse.wheel(0, 3000)
            await asyncio.sleep(2)
        await browser.close()

    logger.info("TikTok profile %s: found %d videos", username, len(posts))
    return {"posts": posts, "creator_info": creator_info}


# ── YouTube — use yt-dlp (no browser needed) ──────────────────────────────────

async def discover_youtube(channel_url: str) -> Dict:
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
        return {"posts": [], "creator_info": {}}

    posts = []
    creator_info: Dict = {}

    if info:
        # Channel-level metadata available from the playlist info
        creator_info = {
            "display_name":    info.get("channel") or info.get("uploader"),
            "follower_count":  info.get("channel_follower_count"),
            "avatar_url":      info.get("thumbnail"),
            "channel_id":      info.get("channel_id"),
            "uploader_id":     info.get("uploader_id"),  # @handle
        }
        # Per-video: flat extraction gives id, title, view_count, duration
        for entry in info.get("entries", []):
            if entry and entry.get("id"):
                vid_id = entry["id"]
                posts.append({
                    "url":          f"https://www.youtube.com/watch?v={vid_id}",
                    "external_id":  vid_id,
                    "views":        entry.get("view_count", 0) or 0,
                    "likes":        0,   # not available in flat mode
                    "shares":       0,
                    "caption":      (entry.get("title") or "")[:500],
                    "posted_at":    entry.get("timestamp"),
                })

    logger.info("YouTube channel %s: found %d videos, %s subscribers",
                channel_url, len(posts), creator_info.get("follower_count", "?"))
    return {"posts": posts, "creator_info": creator_info}


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
