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

logger = logging.getLogger(__name__)

_COMMENT_API = "/api/comment/list/"
_VIDEO_RE = re.compile(r"/video/(\d+)")

_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    window.chrome = { runtime: {} };
"""


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
                nonlocal captured
                if _COMMENT_API in response.url:
                    try:
                        body = await response.json()
                        self._append_record(out_path, body, aweme_id)
                        captured += 1
                    except Exception:
                        pass

            page.on("response", intercept)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                pass
            await asyncio.sleep(5)

            for _ in range(12):
                await page.mouse.wheel(0, 3000)
                await asyncio.sleep(2)

            await browser.close()

        logger.info("TikTok: saved %d batches → %s", captured, out_path)
        return out_path
