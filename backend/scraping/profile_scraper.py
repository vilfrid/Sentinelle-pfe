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
    views_by_pk: Dict[str, int] = {}   # play_count from reels tab
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

            # ── User profile info ──────────────────────────────────────────────
            if "web_profile_info" in url or ("/api/v1/users/" in url and "/info" in url) or "/api/graphql" in url:
                try:
                    body = await response.json()
                    user = (
                        (body.get("data") or {}).get("user")
                        or body.get("user")
                        or {}
                    )
                    if user and not creator_info:
                        follower_count = (
                            user.get("follower_count")
                            or (user.get("edge_followed_by") or {}).get("count")
                        )
                        if user.get("pk") or user.get("id"):
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

            if "/api/graphql" not in url and "/graphql/query" not in url:
                return
            try:
                body = await response.json()
                edges = (
                    (body.get("data") or {})
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

                    caption_obj = node.get("caption")
                    if isinstance(caption_obj, dict):
                        caption = caption_obj.get("text", "")
                    elif isinstance(caption_obj, str):
                        caption = caption_obj
                    else:
                        caption_edges = (node.get("edge_media_to_caption") or {}).get("edges", [])
                        caption = caption_edges[0].get("node", {}).get("text", "") if caption_edges else ""

                    thumbnail_url = ""
                    img2 = node.get("image_versions2") or {}
                    candidates = img2.get("candidates") or []
                    if candidates:
                        thumbnail_url = candidates[0].get("url", "")

                    posts.append({
                        "url": url,
                        "external_id": pk,
                        "likes": (
                            node.get("like_count")
                            or (node.get("edge_liked_by") or {}).get("count")
                            or 0
                        ),
                        "views": (
                            node.get("view_count")
                            or node.get("play_count")
                            or node.get("ig_play_count")
                            or node.get("video_view_count")
                            or 0
                        ),
                        "shares": (
                            node.get("media_repost_count")
                            or node.get("reshare_count")
                            or 0
                        ),
                        "comment_count": (
                            node.get("comment_count")
                            or (node.get("edge_media_to_comment") or {}).get("count")
                            or 0
                        ),
                        "caption": caption[:500],
                        "posted_at": node.get("taken_at") or node.get("taken_at_timestamp"),
                        "thumbnail_url": thumbnail_url,
                        "media_type": node.get("media_type", 1),
                    })
                # Reels tab — captures play_count for video posts
                reel_edges = (
                    (body.get("data") or {})
                    .get("xdt_api__v1__clips__user__connection_v2", {})
                    .get("edges", [])
                )
                for redge in reel_edges:
                    rnode = redge.get("node") or {}
                    media = rnode.get("media") or rnode
                    rpk = str(media.get("pk") or media.get("id") or "")
                    play_count = media.get("play_count") or media.get("ig_play_count") or 0
                    if rpk and play_count:
                        views_by_pk[rpk] = int(play_count)
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

        # Visit the reels tab to collect play_count for video posts
        reels_url = f"https://www.instagram.com/{username}/reels/"
        try:
            await page.goto(reels_url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            pass
        await asyncio.sleep(3)
        for _ in range(10):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)

        for post in posts:
            pk = post["external_id"]
            if pk in views_by_pk and views_by_pk[pk] > 0:
                post["views"] = views_by_pk[pk]

        await browser.close()

    logger.info("Instagram @%s: found %d posts (page: %s)", username, len(posts), page_title)
    return {"posts": posts, "page_title": page_title, "creator_info": creator_info}


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
        channel_bio = (info.get("description") or "").strip()
        creator_info = {
            "display_name":   info.get("channel") or info.get("uploader"),
            "follower_count": info.get("channel_follower_count"),
            "avatar_url":     info.get("thumbnail"),
            "bio":            channel_bio,
            "channel_id":     info.get("channel_id"),
            "uploader_id":    info.get("uploader_id"),
        }

        def _yt_posted_at(entry: dict):
            ts = entry.get("timestamp")
            if ts:
                return ts
            ud = entry.get("upload_date")
            if ud and len(ud) == 8:
                try:
                    from datetime import datetime, timezone
                    return int(datetime(
                        int(ud[:4]), int(ud[4:6]), int(ud[6:8]),
                        tzinfo=timezone.utc
                    ).timestamp())
                except Exception:
                    pass
            return None

        for entry in info.get("entries", []):
            if entry and entry.get("id"):
                vid_id = entry["id"]
                thumb = (
                    entry.get("thumbnail")
                    or f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
                )
                posts.append({
                    "url":           f"https://www.youtube.com/watch?v={vid_id}",
                    "external_id":   vid_id,
                    "views":         entry.get("view_count", 0) or 0,
                    "likes":         entry.get("like_count", 0) or 0,
                    "shares":        0,
                    "comment_count": entry.get("comment_count", 0) or 0,
                    "caption":       (entry.get("title") or "")[:500],
                    "posted_at":     _yt_posted_at(entry),
                    "thumbnail_url": thumb,
                })

    logger.info("YouTube channel %s: found %d videos, %s subscribers",
                channel_url, len(posts), creator_info.get("follower_count", "?"))
    return {"posts": posts, "creator_info": creator_info}


# ── dispatcher ────────────────────────────────────────────────────────────────

async def discover_posts(platform: str, identifier: str, **kwargs):
    dispatch = {
        "instagram": discover_instagram,
        "youtube":   discover_youtube,
    }
    fn = dispatch.get(platform)
    if not fn:
        raise ValueError(f"Unsupported platform: {platform}")
    return await fn(identifier, **kwargs)
