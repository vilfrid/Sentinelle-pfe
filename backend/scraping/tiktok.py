"""
TikTok comment scraper using Playwright.
Intercepts /api/comment/list/ endpoint with stealth to bypass bot detection.
"""
import asyncio
import logging
import re
from pathlib import Path

from playwright.async_api import async_playwright
from scraping.base import BaseScraper
from scraping.profile_scraper import _parse_tiktok_cookies

logger = logging.getLogger(__name__)

_VIDEO_RE = re.compile(r"/video/(\d+)")

# Match any TikTok comment API variant
_COMMENT_API_PATTERNS = ("/api/comment/list", "/api/v1/comment/list", "/comment/list")

_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    window.chrome = { runtime: {} };
"""


class TikTokScraper(BaseScraper):
    platform = "tiktok"

    async def scrape(self, url: str, **kwargs) -> Path:
        from app.config import settings
        m = _VIDEO_RE.search(url)
        aweme_id = m.group(1) if m else url.split("/")[-1]
        out_path = self._get_output_path(aweme_id)
        captured = 0

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
            page = await ctx.new_page()

            async def intercept(response):
                nonlocal captured
                resp_url = response.url
                if any(p in resp_url for p in _COMMENT_API_PATTERNS):
                    logger.info("TikTok comment API hit: %s (status %d)", resp_url[:120], response.status)
                    try:
                        body = await response.json()
                        comments_in_batch = len(body.get("comments") or [])
                        logger.info("TikTok batch: %d comments, has_more=%s", comments_in_batch, body.get("has_more"))
                        self._append_record(out_path, body, aweme_id)
                        captured += 1
                    except Exception as exc:
                        logger.warning("TikTok: failed to parse comment response: %s", exc)
                elif "tiktok.com/api" in resp_url:
                    logger.debug("TikTok API (non-comment): %s", resp_url[:100])

            page.on("response", intercept)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                pass
            await asyncio.sleep(6)

            logger.info("TikTok: page loaded for %s, starting scroll", aweme_id)
            for i in range(15):
                await page.mouse.wheel(0, 3000)
                await asyncio.sleep(2)
                if i == 4:
                    logger.info("TikTok: captured %d batches so far after %d scrolls", captured, i + 1)

            await browser.close()

        logger.info("TikTok: saved %d batches → %s", captured, out_path)
        return out_path
