"""
YouTube comment scraper using Playwright.
Intercepts /youtubei/v1/next POST responses.
"""
import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.async_api import async_playwright
from scraping.base import BaseScraper

logger = logging.getLogger(__name__)

_NEXT_API = "/youtubei/v1/next"
_VIDEO_RE = re.compile(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})")


class YouTubeScraper(BaseScraper):
    platform = "youtube"

    async def scrape(self, url: str, max_scrolls: int = 20, **kwargs) -> Path:
        m = _VIDEO_RE.search(url)
        video_id = m.group(1) if m else "unknown"
        out_path = self._get_output_path(video_id)
        captured = 0
        no_new = 0

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            async def intercept(response):
                nonlocal captured
                if _NEXT_API in response.url:
                    try:
                        body = await response.json()
                        self._append_record(out_path, body, video_id)
                        captured += 1
                    except Exception:
                        pass

            page.on("response", intercept)
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await asyncio.sleep(3)

            prev = 0
            for _ in range(max_scrolls):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)
                if captured == prev:
                    no_new += 1
                    if no_new >= 5:
                        break
                else:
                    no_new = 0
                prev = captured

            await browser.close()

        logger.info("YouTube: saved %d batches → %s", captured, out_path)
        return out_path
