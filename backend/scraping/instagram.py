"""
Instagram comment scraper — uses Instagram's private API directly.
No browser needed: converts post shortcode → media ID, then paginates
GET /api/v1/media/{media_id}/comments/ with the session cookie.

Requires sessionid cookie. On startup we fetch csrftoken from the
homepage so Instagram treats us as a fully authenticated browser session
instead of falling back to "preview mode" (only ~12 top comments, no cursor).
"""
import asyncio
import logging
import random
import re
from pathlib import Path

import httpx

from scraping.base import BaseScraper
from app.config import settings

logger = logging.getLogger(__name__)

_POST_RE = re.compile(r"/p/([A-Za-z0-9_-]+)/")
_REEL_RE = re.compile(r"/reels?/([A-Za-z0-9_-]+)/")

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

_COMMENTS_URL = "https://www.instagram.com/api/v1/media/{media_id}/comments/"
_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "X-IG-App-ID": "936619743392459",
    "Accept": "*/*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.instagram.com/",
    "Origin": "https://www.instagram.com",
}


def _shortcode_to_media_id(shortcode: str) -> str:
    n = 0
    for char in shortcode:
        n = n * 64 + _ALPHABET.index(char)
    return str(n)


async def _build_headers(client: httpx.AsyncClient, session_id: str) -> dict:
    """Fetch csrftoken from Instagram homepage so the session is fully authenticated."""
    cookie = f"sessionid={session_id}"
    try:
        resp = await client.get(
            "https://www.instagram.com/",
            headers={**_BASE_HEADERS, "Cookie": cookie},
            timeout=15,
        )
        csrf = resp.cookies.get("csrftoken", "")
        if csrf:
            cookie = f"sessionid={session_id}; csrftoken={csrf}"
            logger.debug("Instagram: csrftoken acquired")
        else:
            logger.warning("Instagram: csrftoken not found in homepage response")
    except Exception as exc:
        logger.warning("Instagram: failed to fetch csrftoken: %s", exc)
        csrf = ""

    return {
        **_BASE_HEADERS,
        "Cookie": cookie,
        "X-CSRFToken": csrf,
    }


class InstagramScraper(BaseScraper):
    platform = "instagram"

    async def scrape(self, url: str, session_id: str = "", **kwargs) -> Path:
        session_id = session_id or settings.INSTAGRAM_SESSION_ID
        is_reel   = bool(_REEL_RE.search(url))
        m         = _REEL_RE.search(url) or _POST_RE.search(url)
        shortcode  = m.group(1) if m else url.rstrip("/").split("/")[-1]
        post_type  = "reels" if is_reel else "posts"
        out_path   = self._get_output_path(f"{post_type}_{shortcode}")

        try:
            media_id = _shortcode_to_media_id(shortcode)
        except (ValueError, IndexError) as exc:
            logger.warning("Instagram: cannot decode shortcode %s: %s", shortcode, exc)
            return out_path

        total       = 0
        page        = 0
        cursor      = None
        cursor_key  = None  # Will be "min_id" or "max_id"

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            headers = await _build_headers(client, session_id)

            while True:
                params: dict = {
                    "can_support_threading": "true",
                    "permalink_enabled": "false",
                }
                
                # Apply the correct pagination parameter based on the previous response
                if cursor and cursor_key:
                    params[cursor_key] = cursor

                try:
                    resp = await client.get(
                        _COMMENTS_URL.format(media_id=media_id),
                        headers=headers,
                        params=params,
                    )
                except Exception as exc:
                    logger.warning("Instagram API error for %s: %s", shortcode, exc)
                    break

                if resp.status_code == 401:
                    logger.warning("Instagram 401 — session expired (shortcode: %s)", shortcode)
                    break
                if resp.status_code == 404:
                    logger.warning("Instagram 404 — post private or deleted (shortcode: %s)", shortcode)
                    break
                if resp.status_code == 429:
                    wait = random.uniform(10, 20)
                    logger.warning("Instagram 429 rate-limit on %s — waiting %.1fs", shortcode, wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code != 200:
                    logger.warning("Instagram HTTP %d for %s — body: %s",
                                   resp.status_code, shortcode, resp.text[:300])
                    break

                try:
                    data = resp.json()
                except Exception:
                    break

                comments = data.get("comments", [])
                for comment in comments:
                    self._append_record(out_path, comment, shortcode)
                    total += 1

                # Check for BOTH possible pagination tokens
                next_min_id = data.get("next_min_id")
                next_max_id = data.get("next_max_id")
                
                # The boolean flags can come in two variations for comments
                has_more = data.get("has_more_comments", False) or data.get("has_more_headload_comments", False)
                comment_count = data.get("comment_count", "?")
                page += 1

                # Update the cursor state dynamically
                if next_min_id:
                    cursor = next_min_id
                    cursor_key = "min_id"
                elif next_max_id:
                    cursor = next_max_id
                    cursor_key = "max_id"
                else:
                    cursor = None

                logger.info(
                    "Instagram %s page %d: %d comments (total so far: %d / %s) cursor=%s has_more=%s",
                    shortcode, page, len(comments), total, comment_count, cursor, has_more,
                )

                # Break only when NO cursor is returned, or if no comments are left
                if not cursor or not comments:
                    break

                await asyncio.sleep(random.uniform(1.5, 3.0))

        logger.info("Instagram %s %s: %d comments across %d page(s) → %s",
                    post_type, shortcode, total, page, out_path)
        return out_path