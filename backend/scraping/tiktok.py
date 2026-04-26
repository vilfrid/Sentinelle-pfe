"""
TikTok comment scraper using Playwright.
Intercepts /api/comment/list/ endpoint.
"""
import asyncio
import json
import logging
import re
from pathlib import Path

from playwright.async_api import async_playwright
from scraping.base import BaseScraper

logger = logging.getLogger(__name__)

_COMMENT_API = "/api/comment/list/"
_VIDEO_RE = re.compile(r"/video/(\d+)")


class TikTokScraper(BaseScraper):
    platform = "tiktok"

    async def scrape(self, url: str, **kwargs) -> Path:
        m = _VIDEO_RE.search(url)
        aweme_id = m.group(1) if m else url.split("/")[-1]
        out_path = self._get_output_path(aweme_id)
        captured = 0

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context()
            page = await ctx.new_page()

            async def intercept(response):
                nonlocal captured
                if _COMMENT_API in response.url:
                    try:
                        body = await response.json()
                        self._append_record(out_path, body, aweme_id)
                        captured += 1
                    except Exception:
                        pass

            page.on("response", intercept)
            await page.goto(url, wait_until="networkidle", timeout=30_000)

            for _ in range(8):
                await page.mouse.wheel(0, 3000)
                await asyncio.sleep(1.8)

            await browser.close()

        logger.info("TikTok: saved %d batches → %s", captured, out_path)
        return out_path
